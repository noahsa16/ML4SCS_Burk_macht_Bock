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
    private var runStartedAt: Date?

    @Published private(set) var sampleCount = 0
    @Published private(set) var deliveredSampleCount = 0
    @Published private(set) var backgroundQueuedSampleCount = 0
    @Published private(set) var failedBatchCount = 0
    @Published private(set) var droppedSampleCount = 0
    @Published private(set) var queuedSampleCount = 0
    @Published private(set) var isRunning = false
    @Published private(set) var isReachable = false
    @Published private(set) var serverSessionId: String?
    @Published private(set) var actualSampleRateHz = 0.0
    @Published private(set) var lastAccelerationMagnitude = 0.0
    @Published private(set) var lastGyroscopeMagnitude = 0.0
    @Published private(set) var status = "Idle"

    override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
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
        isRunning = true
        runStartedAt = Date()
        status = "Recording"
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
        guard isRunning else { return }
        cm.stopDeviceMotionUpdates()
        isRunning = false
        flushBuffer(force: true)
        if buffer.isEmpty {
            status = "Stopped"
        }
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
    }

    private func flushBuffer(force: Bool) {
        guard buffer.count >= Config.batchSize || (force && !buffer.isEmpty) else { return }

        let sampleCountToSend = force ? buffer.count : Config.batchSize
        let samples = Array(buffer.prefix(sampleCountToSend))
        buffer.removeFirst(sampleCountToSend)
        queuedSampleCount = buffer.count

        let envelope: [String: Any] = [
            "type": "watch_motion_batch",
            "sessionId": serverSessionId ?? sessionId,
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

    @discardableResult
    private func handleCommand(_ message: [String: Any]) -> [String: Any] {
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
            "sampleCount": sampleCount
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
