import Combine
import CoreMotion
import Foundation
import HealthKit
import WatchConnectivity

enum StreamMode: String, CaseIterable {
    case auto       = "Auto"
    case directOnly = "Direct"
    case phoneOnly  = "Phone"
}

class MotionManager: NSObject, ObservableObject {
    private enum Config {
        static let sampleRateHz = 50.0
        static let batchSize = 10
        static let maxBufferedSamples = 3000
        static let defaultServerIP = "192.168.178.147"
        static let statusPollInterval = 2.0
    }

    private let cm = CMMotionManager()
    private let healthStore = HKHealthStore()
    private let sessionId = UUID().uuidString
    private let urlSession: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 4
        configuration.timeoutIntervalForResource = 8
        configuration.waitsForConnectivity = false
        return URLSession(configuration: configuration)
    }()

    private var buffer: [[String: Any]] = []
    private var nextSequence = 0
    private var runStartedAt: Date?
    private var directUploadInFlight = false
    private var pendingForceFlush = false
    private var statusPollTimer: Timer?
    private var statusPollInFlight = false
    private var workoutSession: HKWorkoutSession?
    private var workoutBuilder: HKLiveWorkoutBuilder?
    private var finishingWorkout = false
    private var lastWorkoutRestartAttempt: Date?

    @Published private(set) var sampleCount = 0
    @Published private(set) var deliveredSampleCount = 0
    @Published private(set) var backgroundQueuedSampleCount = 0
    @Published private(set) var failedBatchCount = 0
    @Published private(set) var droppedSampleCount = 0
    @Published private(set) var queuedSampleCount = 0
    @Published private(set) var isRunning = false
    @Published private(set) var isReachable = false
    @Published private(set) var serverReachable = false
    @Published private(set) var serverSessionId: String?
    @Published private(set) var serverIP: String
    @Published private(set) var uploadMode = "Offline"
    @Published var preferredMode: StreamMode {
        didSet { UserDefaults.standard.set(preferredMode.rawValue, forKey: "streamMode") }
    }
    @Published private(set) var workoutStatus = "Workout idle"
    @Published private(set) var actualSampleRateHz = 0.0
    @Published private(set) var lastAccelerationMagnitude = 0.0
    @Published private(set) var lastGyroscopeMagnitude = 0.0
    @Published private(set) var status = "Idle"

    override init() {
        self.serverIP = UserDefaults.standard.string(forKey: "serverIP") ?? Config.defaultServerIP
        let rawMode = UserDefaults.standard.string(forKey: "streamMode") ?? StreamMode.auto.rawValue
        self.preferredMode = StreamMode(rawValue: rawMode) ?? .auto
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
        startStatusPolling()
    }

    deinit {
        statusPollTimer?.invalidate()
        urlSession.invalidateAndCancel()
    }

    func start(sessionId newServerSessionId: String? = nil) {
        guard !isRunning else { return }
        guard cm.isDeviceMotionAvailable else {
            status = "Motion unavailable"
            return
        }

        if let newServerSessionId, !newServerSessionId.isEmpty {
            serverSessionId = newServerSessionId
        }
        resetRunCounters()
        startWorkoutSessionIfNeeded()
        isRunning = true
        runStartedAt = Date()
        status = "Research recording active"
        uploadMode = serverReachable ? "Direct" : "Offline"
        cm.deviceMotionUpdateInterval = 1.0 / Config.sampleRateHz
        cm.startDeviceMotionUpdates(to: .main) { [weak self] motion, _ in
            guard let self, let motion else { return }
            let ts = Self.currentTimestampMillis()
            let accMag = sqrt(
                pow(motion.userAcceleration.x, 2) +
                pow(motion.userAcceleration.y, 2) +
                pow(motion.userAcceleration.z, 2)
            )
            let gyroMag = sqrt(
                pow(motion.rotationRate.x, 2) +
                pow(motion.rotationRate.y, 2) +
                pow(motion.rotationRate.z, 2)
            )
            self.buffer.append([
                "ts": ts,
                "ax": motion.userAcceleration.x,
                "ay": motion.userAcceleration.y,
                "az": motion.userAcceleration.z,
                "rx": motion.rotationRate.x,
                "ry": motion.rotationRate.y,
                "rz": motion.rotationRate.z
            ])
            self.sampleCount += 1
            self.lastAccelerationMagnitude = accMag
            self.lastGyroscopeMagnitude = gyroMag
            if let runStartedAt = self.runStartedAt {
                let elapsed = max(0.001, Date().timeIntervalSince(runStartedAt))
                self.actualSampleRateHz = Double(self.sampleCount) / elapsed
            }
            self.trimBufferIfNeeded()
            self.queuedSampleCount = self.buffer.count
            self.flushBuffer(force: false)
        }
    }

    func stop() {
        guard isRunning || workoutSession != nil else { return }
        cm.stopDeviceMotionUpdates()
        isRunning = false
        flushBuffer(force: true)
        if buffer.isEmpty && !directUploadInFlight {
            status = "Stopped"
        }
        endWorkoutSessionIfNeeded()
    }

    private func resetRunCounters() {
        buffer.removeAll()
        nextSequence = 0
        sampleCount = 0
        deliveredSampleCount = 0
        backgroundQueuedSampleCount = 0
        failedBatchCount = 0
        droppedSampleCount = 0
        queuedSampleCount = 0
        actualSampleRateHz = 0
        lastAccelerationMagnitude = 0
        lastGyroscopeMagnitude = 0
        pendingForceFlush = false
    }

    private func flushBuffer(force: Bool) {
        if directUploadInFlight {
            pendingForceFlush = pendingForceFlush || force
            return
        }

        let shouldForce = force || pendingForceFlush
        pendingForceFlush = false
        guard buffer.count >= Config.batchSize || (shouldForce && !buffer.isEmpty) else { return }

        let sampleCountToSend = shouldForce ? buffer.count : Config.batchSize
        let samples = Array(buffer.prefix(sampleCountToSend))
        buffer.removeFirst(sampleCountToSend)
        queuedSampleCount = buffer.count
        nextSequence += 1

        if preferredMode == .phoneOnly {
            let envelope = makeEnvelope(samples: samples, source: "watch_phone_bridge", transport: "watchconnectivity")
            if !sendViaPhoneFallback(envelope: envelope, samples: samples) {
                uploadMode = "Offline"
                buffer.insert(contentsOf: samples, at: 0)
                trimBufferIfNeeded()
                queuedSampleCount = buffer.count
            }
        } else {
            let envelope = makeEnvelope(samples: samples, source: "watch_direct", transport: "urlsession")
            uploadDirect(envelope: envelope, samples: samples)
        }
    }

    private func makeEnvelope(samples: [[String: Any]], source: String, transport: String) -> [String: Any] {
        [
            "type": "watch_motion_batch",
            "sessionId": serverSessionId ?? sessionId,
            "sequence": nextSequence,
            "sampleRateHz": Config.sampleRateHz,
            "watchSentAt": Self.currentTimestampMillis(),
            "source": source,
            "transport": transport,
            "samples": samples
        ]
    }

    private func uploadDirect(envelope: [String: Any], samples: [[String: Any]]) {
        guard let url = serverURL(path: "/watch") else {
            handleDirectUploadFailure(envelope: envelope, samples: samples, reason: "Invalid server URL")
            return
        }
        guard let body = try? JSONSerialization.data(withJSONObject: envelope) else {
            handleDirectUploadFailure(envelope: envelope, samples: samples, reason: "Could not encode direct batch")
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        directUploadInFlight = true
        uploadMode = "Direct"
        urlSession.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.directUploadInFlight = false

                if let error {
                    self.handleDirectUploadFailure(envelope: envelope, samples: samples, reason: error.localizedDescription)
                    return
                }

                let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard (200..<300).contains(statusCode) else {
                    self.handleDirectUploadFailure(envelope: envelope, samples: samples, reason: "Server HTTP \(statusCode)")
                    return
                }

                self.serverReachable = true
                self.deliveredSampleCount += samples.count
                self.status = self.isRunning ? "Direct streaming" : "Stopped"
                self.uploadMode = "Direct"

                if let data,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    self.applyRemoteSessionStatus(json)
                }

                self.flushBuffer(force: self.pendingForceFlush)
            }
        }.resume()
    }

    private func handleDirectUploadFailure(envelope: [String: Any], samples: [[String: Any]], reason: String) {
        failedBatchCount += 1
        serverReachable = false
        status = reason

        if preferredMode != .directOnly {
            var fallbackEnvelope = envelope
            fallbackEnvelope["source"] = "watch_phone_fallback"
            fallbackEnvelope["transport"] = "watchconnectivity_fallback"
            if sendViaPhoneFallback(envelope: fallbackEnvelope, samples: samples) {
                flushBuffer(force: pendingForceFlush)
                return
            }
        }

        uploadMode = "Offline"
        buffer.insert(contentsOf: samples, at: 0)
        trimBufferIfNeeded()
        queuedSampleCount = buffer.count
    }

    @discardableResult
    private func sendViaPhoneFallback(envelope: [String: Any], samples: [[String: Any]]) -> Bool {
        guard let payloadData = try? JSONSerialization.data(withJSONObject: envelope) else {
            return false
        }
        let message: [String: Any] = ["payload": payloadData]
        uploadMode = "Phone fallback"
        backgroundQueuedSampleCount += samples.count

        if WCSession.default.isReachable {
            WCSession.default.sendMessage(message, replyHandler: { [weak self] _ in
                DispatchQueue.main.async {
                    self?.deliveredSampleCount += samples.count
                    self?.status = self?.isRunning == true ? "Phone fallback" : "Stopped"
                }
            }, errorHandler: { [weak self] error in
                DispatchQueue.main.async {
                    self?.handlePhoneFallbackFailure(samples: samples, reason: error.localizedDescription)
                }
            })
        } else {
            WCSession.default.transferUserInfo(message)
            status = "Queued for phone fallback"
        }
        return true
    }

    private func handlePhoneFallbackFailure(samples: [[String: Any]], reason: String) {
        failedBatchCount += 1
        status = reason
        uploadMode = "Offline"
        buffer.insert(contentsOf: samples, at: 0)
        trimBufferIfNeeded()
        queuedSampleCount = buffer.count
    }

    private func startStatusPolling() {
        statusPollTimer?.invalidate()
        let timer = Timer(timeInterval: Config.statusPollInterval, repeats: true) { [weak self] _ in
            self?.fetchServerStatus()
        }
        timer.tolerance = 0.5
        RunLoop.main.add(timer, forMode: .common)
        statusPollTimer = timer
        fetchServerStatus()
    }

    func refreshServerStatus() { fetchServerStatus() }

    private func fetchServerStatus() {
        guard !statusPollInFlight, let url = serverURL(path: "/watch/ping") else { return }
        statusPollInFlight = true

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 3

        urlSession.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.statusPollInFlight = false

                guard error == nil,
                      let http = response as? HTTPURLResponse,
                      (200..<300).contains(http.statusCode),
                      let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    self.serverReachable = false
                    if !self.isRunning {
                        self.uploadMode = self.isReachable ? "Phone fallback" : "Offline"
                    }
                    return
                }

                self.serverReachable = true
                self.applyRemoteSessionStatus(json)
            }
        }.resume()
    }

    private func applyRemoteSessionStatus(_ json: [String: Any]) {
        let sessionActive = json["session_active"] as? Bool ?? false
        let remoteSessionId = json["session_id"] as? String

        if sessionActive, let remoteSessionId, !remoteSessionId.isEmpty {
            if !isRunning {
                start(sessionId: remoteSessionId)
            } else if serverSessionId != remoteSessionId {
                serverSessionId = remoteSessionId
            }
        } else if isRunning && serverSessionId != nil {
            stop()
            serverSessionId = nil
        }
    }

    private func updateServerIP(_ newValue: String) {
        let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != serverIP else { return }
        serverIP = trimmed
        UserDefaults.standard.set(trimmed, forKey: "serverIP")
        fetchServerStatus()
    }

    private func serverBaseURLString() -> String {
        let trimmed = serverIP
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return trimmed
        }
        return trimmed.contains(":") ? "http://\(trimmed)" : "http://\(trimmed):8000"
    }

    private func serverURL(path: String) -> URL? {
        URL(string: serverBaseURLString() + path)
    }

    private func trimBufferIfNeeded() {
        guard buffer.count > Config.maxBufferedSamples else { return }
        let overflow = buffer.count - Config.maxBufferedSamples
        buffer.removeFirst(overflow)
        droppedSampleCount += overflow
    }

    private static func currentTimestampMillis() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }
}

extension MotionManager: WCSessionDelegate {
    func session(_ session: WCSession,
                 activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async {
            self.isReachable = session.isReachable
            if let contextIP = session.receivedApplicationContext["server_ip"] as? String {
                self.updateServerIP(contextIP)
            }
            if let error {
                self.status = error.localizedDescription
            }
        }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            self.isReachable = session.isReachable
        }
    }

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            if let serverIP = applicationContext["server_ip"] as? String {
                self.updateServerIP(serverIP)
            }
        }
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        DispatchQueue.main.async {
            if let serverIP = userInfo["server_ip"] as? String {
                self.updateServerIP(serverIP)
            }
            // Handle queued commands (sent via transferUserInfo when Watch was not reachable).
            if userInfo["command"] != nil {
                _ = self.handleCommand(userInfo)
            }
        }
    }

    @discardableResult
    private func handleCommand(_ message: [String: Any]) -> [String: Any] {
        if let serverIP = message["server_ip"] as? String {
            updateServerIP(serverIP)
        }

        guard let command = message["command"] as? String else {
            return ["ok": false, "error": "Missing command"]
        }
        switch command {
        case "start":
            let sid = message["session_id"] as? String
            start(sessionId: sid)
        case "stop":
            stop()
            serverSessionId = nil
        default:
            return ["ok": false, "error": "Unknown command", "command": command]
        }
        return [
            "ok": true,
            "command": command,
            "isRunning": isRunning,
            "session_id": serverSessionId ?? "",
            "sampleCount": sampleCount,
            "server_ip": serverIP,
            "uploadMode": uploadMode
        ]
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async { _ = self.handleCommand(message) }
    }

    func session(_ session: WCSession,
                 didReceiveMessage message: [String: Any],
                 replyHandler: @escaping ([String: Any]) -> Void) {
        DispatchQueue.main.async {
            let reply = self.handleCommand(message)
            replyHandler(reply)
        }
    }
}

extension MotionManager: HKWorkoutSessionDelegate, HKLiveWorkoutBuilderDelegate {
    private func startWorkoutSessionIfNeeded() {
        guard workoutSession == nil else { return }
        guard HKHealthStore.isHealthDataAvailable() else {
            workoutStatus = "HealthKit unavailable"
            return
        }

        let shareTypes: Set<HKSampleType> = [HKObjectType.workoutType()]
        healthStore.requestAuthorization(toShare: shareTypes, read: []) { [weak self] success, error in
            DispatchQueue.main.async {
                guard let self else { return }
                if let error {
                    self.workoutStatus = error.localizedDescription
                    return
                }
                guard success else {
                    self.workoutStatus = "Workout permission denied"
                    return
                }
                self.beginWorkoutSession()
            }
        }
    }

    private func beginWorkoutSession() {
        guard workoutSession == nil else { return }
        let configuration = HKWorkoutConfiguration()
        configuration.activityType = .other
        configuration.locationType = .unknown

        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: configuration)
            // Builder keeps the session alive more robustly (watchOS respects active data
            // collection); finishWorkout() is intentionally never called so nothing saves to Health.
            let builder = session.associatedWorkoutBuilder()
            builder.dataSource = HKLiveWorkoutDataSource(healthStore: healthStore,
                                                          workoutConfiguration: configuration)
            session.delegate = self
            builder.delegate = self
            workoutSession = session
            workoutBuilder = builder
            let now = Date()
            session.startActivity(with: now)
            builder.beginCollection(withStart: now) { [weak self] _, _ in
                DispatchQueue.main.async { self?.workoutStatus = "Workout background active" }
            }
        } catch {
            workoutStatus = error.localizedDescription
        }
    }

    private func endWorkoutSessionIfNeeded() {
        guard let workoutSession else { return }
        workoutStatus = "Ending workout"
        workoutSession.stopActivity(with: Date())
    }

    private func finishWorkout(at date: Date, for endedSession: HKWorkoutSession, then: (() -> Void)? = nil) {
        guard !finishingWorkout else { return }
        finishingWorkout = true
        // Call end() without builder.finishWorkout() — data is intentionally not saved to Health.
        endedSession.end()
        if workoutSession === endedSession {
            workoutSession = nil
            workoutBuilder = nil
        }
        finishingWorkout = false
        workoutStatus = "Workout ended"
        then?()
    }

    private func restartWorkoutIfNeeded() {
        guard isRunning else { return }
        // Backoff: at most one restart attempt every 15 seconds
        if let last = lastWorkoutRestartAttempt, Date().timeIntervalSince(last) < 15 { return }
        lastWorkoutRestartAttempt = Date()
        workoutStatus = "Workout restarting…"
        beginWorkoutSession()
    }

    func workoutSession(_ workoutSession: HKWorkoutSession,
                        didChangeTo toState: HKWorkoutSessionState,
                        from fromState: HKWorkoutSessionState,
                        date: Date) {
        DispatchQueue.main.async {
            switch toState {
            case .running:
                self.workoutStatus = "Workout background active"
            case .paused:
                // watchOS auto-pauses on wrist-off or inactivity — immediately resume.
                self.workoutStatus = "Workout paused – resuming"
                workoutSession.resume()
            case .stopped:
                self.workoutStatus = "Workout stopped – finishing"
                self.finishWorkout(at: date, for: workoutSession) {
                    self.restartWorkoutIfNeeded()
                }
            case .ended:
                // Only clear our ref if this is still the session that just ended.
                // If a restart already created a new session, leave it untouched.
                if self.workoutSession === workoutSession {
                    self.workoutSession = nil
                    self.workoutBuilder = nil
                    self.finishingWorkout = false
                }
                self.workoutStatus = "Workout ended – restarting"
                self.restartWorkoutIfNeeded()
            default:
                self.workoutStatus = "Workout state: \(toState.rawValue)"
            }
        }
    }

    func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        DispatchQueue.main.async {
            self.workoutStatus = "Workout error: \(error.localizedDescription)"
            self.restartWorkoutIfNeeded()
        }
    }

    func workoutBuilder(_ workoutBuilder: HKLiveWorkoutBuilder, didCollectDataOf collectedTypes: Set<HKSampleType>) {}
    func workoutBuilderDidCollectEvent(_ workoutBuilder: HKLiveWorkoutBuilder) {}
}
