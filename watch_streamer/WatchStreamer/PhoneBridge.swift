import Combine
import Foundation
import WatchConnectivity

class PhoneBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let SERVER_IP = "10.233.10.41"   // ← change me

    @Published var isConnected = false
    @Published var sampleCount = 0

    override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func session(_ session: WCSession,
                 activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {}
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) { session.activate() }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard let batch = message["batch"] as? [[String: Any]] else { return }
        DispatchQueue.main.async { self.sampleCount += batch.count }
        guard let url = URL(string: "http://\(Self.SERVER_IP):8000/watch"),
              let body = try? JSONSerialization.data(withJSONObject: batch) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        URLSession.shared.dataTask(with: req).resume()
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.isConnected = session.isReachable }
    }
}
