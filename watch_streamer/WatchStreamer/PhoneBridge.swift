import Combine
import Foundation
import WatchConnectivity

class PhoneBridge: NSObject, ObservableObject, WCSessionDelegate {
    static var serverAddress: String {
        let ip = UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147"
        return "http://\(ip):8000/watch"
    }

    @Published var isConnected = false
    @Published var receivedSampleCount = 0
    @Published var uploadedSampleCount = 0
    @Published var queuedBatchCount = 0
    @Published var failedUploadCount = 0
    @Published var lastError = ""

    private var uploadQueue: [[String: Any]] = []
    private var isUploading = false

    override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func session(_ session: WCSession,
                 activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async {
            self.isConnected = session.isReachable
            if let error {
                self.lastError = error.localizedDescription
            }
        }
    }
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { session.activate() }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        receivePayload(message, source: "message")
    }

    func session(_ session: WCSession,
                 didReceiveMessage message: [String: Any],
                 replyHandler: @escaping ([String: Any]) -> Void) {
        let accepted = receivePayload(message, source: "message")
        replyHandler(["ok": accepted])
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        receivePayload(userInfo, source: "background")
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.isConnected = session.isReachable }
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
        normalized["source"] = source
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
