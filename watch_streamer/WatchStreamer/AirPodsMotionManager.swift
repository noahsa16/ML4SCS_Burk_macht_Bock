import Combine
import CoreMotion
import Foundation

/// Captures head-motion data from AirPods (Pro/Max/3rd Gen) via
/// `CMHeadphoneMotionManager` and POSTs batches to the FastAPI server's
/// `/airpods` endpoint.
///
/// Architecture mirrors `PhoneBridge` for the watch path, but simpler:
/// - No WatchConnectivity (AirPods talk directly to iPhone).
/// - In-memory upload queue only (no on-disk persistence yet — sessions are
///   short and the failure mode if iPhone crashes is "lose this session",
///   which is acceptable for now).
/// - Single batching policy: ship every `batchSize` samples or every
///   `batchInterval` seconds, whichever comes first.
///
/// Connection state is surfaced via the delegate — `isHeadphonesConnected`
/// flips before any motion data flows, so the dashboard can show "AirPods
/// connected · streaming idle" without needing samples first.
///
/// Requires Privacy → Motion & Fitness permission. Handled via
/// `INFOPLIST_KEY_NSMotionUsageDescription` in the iPhone build settings.
@MainActor
final class AirPodsMotionManager: NSObject, ObservableObject {
    static let shared = AirPodsMotionManager()

    // MARK: - Tuning

    /// `CMHeadphoneMotionManager` always streams at 25 Hz on supported
    /// devices — there is no `setUpdateInterval` API for headphones.
    private let nominalRateHz: Double = 25.0

    /// Ship every 25 samples → ~1 batch/sec at 25 Hz, matches the watch
    /// path's cadence and keeps server-side merge windows aligned.
    private let batchSize = 25

    /// Hard upper bound on time between uploads, even if `batchSize` not
    /// reached (e.g. user pauses head movement and updates slow down — they
    /// shouldn't, but defensive).
    private let batchInterval: TimeInterval = 1.5

    /// Drop oldest when queue exceeds this many batches. ~30 s backlog.
    private let maxQueueSize = 30

    // MARK: - Published

    /// Whether `CMHeadphoneMotionManager` reports motion APIs are available
    /// at all (false on iPhone simulators and pre-iOS-14 devices).
    @Published private(set) var isAvailable = false

    /// Whether AirPods with motion capability are currently paired/connected
    /// (driven by the delegate, not by sample arrival — flips immediately
    /// when AirPods come in/out of range).
    @Published private(set) var isHeadphonesConnected = false

    /// Whether `start()` has been called and we're listening for samples.
    /// True even if `isHeadphonesConnected` is false — Core Motion will
    /// queue updates as soon as the user puts the AirPods on.
    @Published private(set) var isStreaming = false

    @Published private(set) var sampleCount = 0
    @Published private(set) var uploadedCount = 0
    @Published private(set) var queuedBatchCount = 0
    @Published private(set) var failedUploadCount = 0
    @Published private(set) var droppedBatchCount = 0
    @Published private(set) var lastError = ""

    // MARK: - Private

    private let manager = CMHeadphoneMotionManager()
    private var buffer: [[String: Any]] = []
    private var sequence: Int = 0
    private var firstSampleInBatchAt: Date?
    private var flushTimer: Timer?

    private var uploadQueue: [[String: Any]] = []
    private var isUploading = false

    // Why: capped exponential backoff for upload retries (mirrors PhoneBridge);
    // reset to base after a successful upload.
    private static let uploadRetryMaxDelay: TimeInterval = 30.0
    private var uploadRetryDelay: TimeInterval = 2.0

    private override init() {
        super.init()
        isAvailable = manager.isDeviceMotionAvailable
        manager.delegate = self
    }

    // MARK: - Public API

    func start() {
        guard manager.isDeviceMotionAvailable else {
            lastError = "AirPods motion not available — needs Pro / Max / 3rd Gen and iOS 14+."
            return
        }
        guard !isStreaming else { return }

        sequence = 0
        sampleCount = 0
        uploadedCount = 0
        failedUploadCount = 0
        droppedBatchCount = 0
        lastError = ""
        isStreaming = true

        // Core Motion handler is invoked on `OperationQueue.main`, which runs
        // on the main thread — so it's safe to hop to the main actor.
        // Wrapping in `Task { @MainActor in }` keeps Swift 6 concurrency
        // checking happy without forcing a runtime hop.
        manager.startDeviceMotionUpdates(to: .main) { [weak self] motion, error in
            Task { @MainActor in
                guard let self else { return }
                if let error {
                    self.lastError = error.localizedDescription
                    return
                }
                guard let motion else { return }
                self.ingest(motion)
            }
        }
        scheduleFlushTimer()
    }

    func stop() {
        guard isStreaming else { return }
        manager.stopDeviceMotionUpdates()
        flushTimer?.invalidate()
        flushTimer = nil
        flush(force: true)
        isStreaming = false
    }

    // MARK: - Ingest

    private func ingest(_ motion: CMDeviceMotion) {
        let tsMs = Int(motion.timestamp * 1000)  // seconds since boot → ms

        let sample: [String: Any] = [
            "ts": tsMs,
            "ax": motion.userAcceleration.x,
            "ay": motion.userAcceleration.y,
            "az": motion.userAcceleration.z,
            "rx": motion.rotationRate.x,
            "ry": motion.rotationRate.y,
            "rz": motion.rotationRate.z,
            "qw": motion.attitude.quaternion.w,
            "qx": motion.attitude.quaternion.x,
            "qy": motion.attitude.quaternion.y,
            "qz": motion.attitude.quaternion.z,
            "gx": motion.gravity.x,
            "gy": motion.gravity.y,
            "gz": motion.gravity.z,
        ]
        if buffer.isEmpty {
            firstSampleInBatchAt = Date()
        }
        buffer.append(sample)
        sampleCount += 1

        if buffer.count >= batchSize {
            flush(force: false)
        }
    }

    private func scheduleFlushTimer() {
        flushTimer?.invalidate()
        // Timer fires on the current run loop (main, since we schedule from
        // the main actor). The block is non-isolated, so we hop back via Task.
        let timer = Timer(timeInterval: batchInterval / 2, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                guard let started = self.firstSampleInBatchAt,
                      !self.buffer.isEmpty,
                      Date().timeIntervalSince(started) >= self.batchInterval else { return }
                self.flush(force: false)
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        flushTimer = timer
    }

    private func flush(force: Bool) {
        guard !buffer.isEmpty else {
            if force { firstSampleInBatchAt = nil }
            return
        }
        sequence += 1

        let nowMs = Int64(Date().timeIntervalSince1970 * 1000)
        // Why: phoneReceivedAt mirrors airpodsSentAt on purpose — AirPods motion
        // originates on this device, so capture and receipt share one clock and
        // one instant. Kept (not dropped) because the server's /airpods schema
        // has a phone_received_at column.
        let envelope: [String: Any] = [
            "samples": buffer,
            "sequence": sequence,
            "sampleRateHz": nominalRateHz,
            "airpodsSentAt": nowMs,
            "phoneReceivedAt": nowMs,
            "source": "airpods",
        ]
        buffer.removeAll(keepingCapacity: true)
        firstSampleInBatchAt = nil

        if uploadQueue.count >= maxQueueSize {
            let drop = uploadQueue.count - maxQueueSize + 1
            uploadQueue.removeFirst(drop)
            droppedBatchCount += drop
        }
        uploadQueue.append(envelope)
        queuedBatchCount = uploadQueue.count
        uploadNextIfNeeded()
    }

    // MARK: - Upload

    private var serverURL: URL? {
        let raw = UserDefaults.standard.string(forKey: "serverIP") ?? ServerConfig.defaultIP
        let trimmed = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !trimmed.isEmpty else { return nil }
        let base: String
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            base = trimmed
        } else if trimmed.contains(":") {
            base = "http://\(trimmed)"
        } else {
            base = "http://\(trimmed):8000"
        }
        return URL(string: "\(base)/airpods")
    }

    private func uploadNextIfNeeded() {
        guard !isUploading, let payload = uploadQueue.first else { return }
        guard let url = serverURL else {
            lastError = "Invalid server URL"
            return
        }

        isUploading = true
        let body: Data
        do {
            body = try JSONSerialization.data(withJSONObject: payload)
        } catch {
            failedUploadCount += 1
            lastError = "Encode failed: \(error.localizedDescription)"
            if !uploadQueue.isEmpty { uploadQueue.removeFirst() }
            queuedBatchCount = uploadQueue.count
            isUploading = false
            uploadNextIfNeeded()
            return
        }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        req.timeoutInterval = 8

        URLSession.shared.dataTask(with: req) { [weak self] _, response, error in
            Task { @MainActor in
                guard let self else { return }
                self.isUploading = false

                if let error {
                    self.failedUploadCount += 1
                    self.lastError = error.localizedDescription
                    self.scheduleRetry()
                    return
                }
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard (200..<300).contains(code) else {
                    self.failedUploadCount += 1
                    self.lastError = "Server HTTP \(code)"
                    self.scheduleRetry()
                    return
                }

                let samples = payload["samples"] as? [[String: Any]]
                self.uploadedCount += samples?.count ?? 0
                if !self.uploadQueue.isEmpty { self.uploadQueue.removeFirst() }
                self.queuedBatchCount = self.uploadQueue.count
                self.lastError = ""
                self.uploadRetryDelay = 2.0
                self.uploadNextIfNeeded()
            }
        }.resume()
    }

    private func scheduleRetry() {
        let delay = uploadRetryDelay
        uploadRetryDelay = min(uploadRetryDelay * 2, Self.uploadRetryMaxDelay)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            Task { @MainActor in
                self?.uploadNextIfNeeded()
            }
        }
    }
}

// MARK: - CMHeadphoneMotionManagerDelegate

extension AirPodsMotionManager: CMHeadphoneMotionManagerDelegate {
    nonisolated func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        Task { @MainActor in
            self.isHeadphonesConnected = true
            self.lastError = ""
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }

    nonisolated func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        Task { @MainActor in
            self.isHeadphonesConnected = false
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }
}
