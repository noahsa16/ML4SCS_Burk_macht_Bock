import Combine
import CoreMotion
import Foundation
import WatchConnectivity

class MotionManager: NSObject, ObservableObject {
    private enum Config {
        static let sampleRateHz = 50.0
        static let batchSize = 10
        static let maxBufferedSamples = 500
    }

    private let cm = CMMotionManager()
    private let sessionId = UUID().uuidString
    private var buffer: [[String: Any]] = []
    private var nextSequence = 0

    @Published private(set) var sampleCount = 0
    @Published private(set) var deliveredSampleCount = 0
    @Published private(set) var backgroundQueuedSampleCount = 0
    @Published private(set) var failedBatchCount = 0
    @Published private(set) var droppedSampleCount = 0
    @Published private(set) var queuedSampleCount = 0
    @Published private(set) var isRunning = false
    @Published private(set) var isReachable = false
    @Published private(set) var serverSessionId: String?
    @Published private(set) var status = "Idle"

    override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func start() {
        guard !isRunning else { return }
        guard cm.isDeviceMotionAvailable else {
            status = "Motion unavailable"
            return
        }

        isRunning = true
        status = "Recording"
        cm.deviceMotionUpdateInterval = 1.0 / Config.sampleRateHz
        cm.startDeviceMotionUpdates(to: .main) { [weak self] motion, _ in
            guard let self, let motion else { return }
            let ts = Self.currentTimestampMillis()
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
            self.trimBufferIfNeeded()
            self.queuedSampleCount = self.buffer.count
            self.flushBuffer(force: false)
        }
    }

    func stop() {
        guard isRunning else { return }
        cm.stopDeviceMotionUpdates()
        isRunning = false
        flushBuffer(force: true)
        if buffer.isEmpty {
            status = "Stopped"
        }
    }

    private func flushBuffer(force: Bool) {
        guard buffer.count >= Config.batchSize || (force && !buffer.isEmpty) else { return }

        let sampleCountToSend = force ? buffer.count : Config.batchSize
        let samples = Array(buffer.prefix(sampleCountToSend))
        buffer.removeFirst(sampleCountToSend)
        queuedSampleCount = buffer.count

        let envelope: [String: Any] = [
            "type": "watch_motion_batch",
            "sessionId": sessionId,
            "sequence": nextSequence,
            "sampleRateHz": Config.sampleRateHz,
            "watchSentAt": Self.currentTimestampMillis(),
            "samples": samples
        ]
        nextSequence += 1

        guard let payloadData = try? JSONSerialization.data(withJSONObject: envelope) else {
            failedBatchCount += 1
            status = "Could not encode batch"
            return
        }

        let message: [String: Any] = [
            "payload": payloadData
        ]

        if WCSession.default.isReachable {
            WCSession.default.sendMessage(message, replyHandler: { [weak self] _ in
                DispatchQueue.main.async {
                    self?.deliveredSampleCount += samples.count
                    self?.status = self?.isRunning == true ? "Recording" : "Stopped"
                }
            }, errorHandler: { [weak self] error in
                DispatchQueue.main.async {
                    self?.handleSendFailure(samples: samples, error: error)
                }
            })
        } else {
            WCSession.default.transferUserInfo(message)
            backgroundQueuedSampleCount += samples.count
            status = "Queued for phone"
        }
    }

    private func handleSendFailure(samples: [[String: Any]], error: Error) {
        failedBatchCount += 1
        buffer.insert(contentsOf: samples, at: 0)
        trimBufferIfNeeded()
        queuedSampleCount = buffer.count
        status = error.localizedDescription
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

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard let command = message["command"] as? String else { return }
        DispatchQueue.main.async {
            switch command {
            case "start":
                self.serverSessionId = message["session_id"] as? String
                self.start()
            case "stop":
                self.stop()
                self.serverSessionId = nil
            default:
                break
            }
        }
    }
}
