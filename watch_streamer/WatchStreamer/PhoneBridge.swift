import Combine
import Foundation
import WatchConnectivity

class PhoneBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneBridge()

    static var serverBaseURL: String {
        let raw = UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147"
        let trimmed = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return trimmed
        }
        return trimmed.contains(":") ? "http://\(trimmed)" : "http://\(trimmed):8000"
    }

    static var serverAddress: String {
        "\(serverBaseURL)/watch"
    }

    /// True while WCSession.isReachable (debounced: 4 s grace period on drop to avoid flicker).
    @Published var isConnected = false
    /// True when the Watch is paired and the Watch app is installed — structural, not live.
    @Published var isBridgeCapable = false
    @Published var receivedSampleCount = 0
    @Published var uploadedSampleCount = 0
    @Published var queuedBatchCount = 0
    @Published var failedUploadCount = 0
    @Published var lastError = ""

    private var uploadQueue: [[String: Any]] = []
    private var isUploading = false
    private var disconnectDebounce: DispatchWorkItem?

    private override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    // MARK: – Connectivity helpers (must be called on main thread)

    private func applyReachability(_ session: WCSession) {
        isBridgeCapable = session.activationState == .activated
            && session.isPaired
            && session.isWatchAppInstalled

        if session.isReachable {
            disconnectDebounce?.cancel()
            disconnectDebounce = nil
            isConnected = true
        } else {
            guard isConnected, disconnectDebounce == nil else { return }
            let item = DispatchWorkItem { [weak self] in
                self?.isConnected = false
                self?.disconnectDebounce = nil
            }
            disconnectDebounce = item
            DispatchQueue.main.asyncAfter(deadline: .now() + 4.0, execute: item)
        }
    }

    private func forceDisconnect() {
        disconnectDebounce?.cancel()
        disconnectDebounce = nil
        isConnected = false
        isBridgeCapable = false
    }

    func session(_ session: WCSession,
                 activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async {
            self.applyReachability(session)
            if let error {
                self.lastError = error.localizedDescription
            }
            self.syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }
    func sessionDidBecomeInactive(_ session: WCSession) {
        DispatchQueue.main.async { self.forceDisconnect() }
    }
    func sessionDidDeactivate(_ session: WCSession) {
        DispatchQueue.main.async { self.forceDisconnect() }
        session.activate()
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard message["type"] as? String != "command_poll" else { return }
        receivePayload(message, source: "message")
    }

    func session(_ session: WCSession,
                 didReceiveMessage message: [String: Any],
                 replyHandler: @escaping ([String: Any]) -> Void) {
        if message["type"] as? String == "command_poll" {
            let reply = ServerCommandListener.shared.handleWatchCommandPoll(message)
            replyHandler(reply)
            return
        }
        let accepted = receivePayload(message, source: "message")
        replyHandler(["ok": accepted])
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        receivePayload(userInfo, source: "background")
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            self.applyReachability(session)
            self.syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }

    func syncServerIP(_ ip: String) {
        let trimmed = ip.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        UserDefaults.standard.set(trimmed, forKey: "serverIP")
        guard WCSession.default.activationState == .activated else { return }
        do {
            var context = ServerCommandListener.shared.currentWatchCommandPayload()
            context["server_ip"] = trimmed
            try WCSession.default.updateApplicationContext(context)
        } catch {
            lastError = "Could not sync server IP: \(error.localizedDescription)"
        }
    }

    func reactivateSession() {
        WCSession.default.delegate = self
        WCSession.default.activate()
        applyReachability(WCSession.default)
        syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
        ServerCommandListener.shared.sendPhoneStatus()
    }

    func resyncWatchContext() {
        syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
        ServerCommandListener.shared.refreshWatchContext()
    }

    func retryUploadQueue() {
        guard !uploadQueue.isEmpty else {
            lastError = ""
            queuedBatchCount = 0
            return
        }
        lastError = ""
        uploadNextIfNeeded()
    }

    func clearDiagnostics() {
        lastError = ""
        failedUploadCount = 0
    }


    @discardableResult
    private func receivePayload(_ payload: [String: Any], source: String) -> Bool {
        guard let normalized = normalizePayload(payload, source: source),
              let samples = normalized["samples"] as? [[String: Any]] else {
            DispatchQueue.main.async { self.lastError = "Invalid watch payload" }
            return false
        }

        DispatchQueue.main.async {
            self.receivedSampleCount += samples.count
            self.uploadQueue.append(normalized)
            self.queuedBatchCount = self.uploadQueue.count
            self.lastError = ""

            // Feed real IMU magnitudes to the live chart.
            let accValues  = samples.map { s -> Double in
                let ax = s["ax"] as? Double ?? 0
                let ay = s["ay"] as? Double ?? 0
                let az = s["az"] as? Double ?? 0
                return sqrt(ax*ax + ay*ay + az*az)
            }
            let gyroValues = samples.map { s -> Double in
                let rx = s["rx"] as? Double ?? 0
                let ry = s["ry"] as? Double ?? 0
                let rz = s["rz"] as? Double ?? 0
                return sqrt(rx*rx + ry*ry + rz*rz)
            }
            IMUDataStore.shared.pushBatch(accValues: accValues, gyroValues: gyroValues)

            self.uploadNextIfNeeded()
        }
        return true
    }

    private func normalizePayload(_ payload: [String: Any], source: String) -> [String: Any]? {
        var decodedPayload = payload
        if let payloadData = payload["payload"] as? Data,
           let decoded = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any] {
            decodedPayload = decoded
        }

        let samples = decodedPayload["samples"] as? [[String: Any]]
            ?? decodedPayload["batch"] as? [[String: Any]]
        guard let samples else { return nil }

        var normalized = decodedPayload
        normalized["type"] = decodedPayload["type"] as? String ?? "watch_motion_batch"
        normalized["source"] = decodedPayload["source"] as? String ?? source
        normalized["transport"] = decodedPayload["transport"] as? String ?? "watchconnectivity"
        normalized["phoneReceivedAt"] = Self.currentTimestampMillis()
        normalized["samples"] = samples
        return normalized
    }

    private func uploadNextIfNeeded() {
        guard !isUploading, let payload = uploadQueue.first else { return }
        guard let url = URL(string: Self.serverAddress) else {
            lastError = "Invalid server URL"
            return
        }
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            failedUploadCount += 1
            lastError = "Could not encode payload"
            uploadQueue.removeFirst()
            queuedBatchCount = uploadQueue.count
            uploadNextIfNeeded()
            return
        }

        isUploading = true
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body

        URLSession.shared.dataTask(with: req) { _, response, error in
            DispatchQueue.main.async {
                self.isUploading = false

                if let error {
                    self.failedUploadCount += 1
                    self.lastError = error.localizedDescription
                    self.scheduleRetry()
                    return
                }

                let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard (200..<300).contains(statusCode) else {
                    self.failedUploadCount += 1
                    self.lastError = "Server HTTP \(statusCode)"
                    self.scheduleRetry()
                    return
                }

                let samples = payload["samples"] as? [[String: Any]]
                self.uploadedSampleCount += samples?.count ?? 0
                self.uploadQueue.removeFirst()
                self.queuedBatchCount = self.uploadQueue.count
                self.lastError = ""
                self.uploadNextIfNeeded()
            }
        }.resume()
    }

    private func scheduleRetry() {
        queuedBatchCount = uploadQueue.count
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            self.uploadNextIfNeeded()
        }
    }

    private static func currentTimestampMillis() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }
}
