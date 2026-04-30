import Combine
import CoreMotion
import Foundation
import WatchConnectivity

class MotionManager: NSObject, ObservableObject {
    private let cm = CMMotionManager()
    @Published var sampleCount = 0
    private var buffer: [[String: Any]] = []

    override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func start() {
        cm.deviceMotionUpdateInterval = 1.0 / 50.0
        cm.startDeviceMotionUpdates(to: .main) { [weak self] motion, _ in
            guard let self, let motion else { return }
            let ts = Int64(Date().timeIntervalSince1970 * 1000)
            self.buffer.append([
                "ts": ts, "ax": motion.userAcceleration.x,
                "ay": motion.userAcceleration.y, "az": motion.userAcceleration.z,
                "rx": motion.rotationRate.x, "ry": motion.rotationRate.y,
                "rz": motion.rotationRate.z
            ])
            self.sampleCount += 1
            if self.buffer.count >= 10 {
                WCSession.default.sendMessage(["batch": self.buffer], replyHandler: nil)
                self.buffer.removeAll()
            }
        }
    }

    func stop() { cm.stopDeviceMotionUpdates() }
}

extension MotionManager: WCSessionDelegate {
    func session(_ session: WCSession,
                 activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {}
}
