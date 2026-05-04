import Combine
import CoreMotion
import Foundation
import HealthKit
import WatchConnectivity

class MotionManager: NSObject, ObservableObject {
    private enum Config {
        static let sampleRateHz = 50.0
        static let batchSize = 10
        static let maxBufferedSamples = 3000
    }

    private let cm = CMMotionManager()
    private let healthStore = HKHealthStore()
    private let sessionId = UUID().uuidString

    private var buffer: [[String: Any]] = []
    private var nextSequence = 0
    private var runStartedAt: Date?
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
    @Published private(set) var serverSessionId: String?
    @Published private(set) var uploadMode = "Offline"
    @Published private(set) var workoutStatus = "Workout idle"
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
        startWorkoutSessionIfNeeded()
        isRunning = true
        runStartedAt = Date()
        status = "Recording"
        uploadMode = isReachable ? "Bridge" : "Offline"
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
        if buffer.isEmpty {
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
    }

    private func flushBuffer(force: Bool) {
        guard buffer.count >= Config.batchSize || (force && !buffer.isEmpty) else { return }

        let sampleCountToSend = force ? buffer.count : Config.batchSize
        let samples = Array(buffer.prefix(sampleCountToSend))
        buffer.removeFirst(sampleCountToSend)
        queuedSampleCount = buffer.count
        nextSequence += 1

        let envelope = makeEnvelope(samples: samples)
        if !sendViaBridge(envelope: envelope, samples: samples) {
            uploadMode = "Offline"
            buffer.insert(contentsOf: samples, at: 0)
            trimBufferIfNeeded()
            queuedSampleCount = buffer.count
        }
    }

    private func makeEnvelope(samples: [[String: Any]]) -> [String: Any] {
        [
            "type": "watch_motion_batch",
            "sessionId": serverSessionId ?? sessionId,
            "sequence": nextSequence,
            "sampleRateHz": Config.sampleRateHz,
            "watchSentAt": Self.currentTimestampMillis(),
            "source": "watch_phone_bridge",
            "transport": "watchconnectivity",
            "samples": samples
        ]
    }

    @discardableResult
    private func sendViaBridge(envelope: [String: Any], samples: [[String: Any]]) -> Bool {
        guard let payloadData = try? JSONSerialization.data(withJSONObject: envelope) else {
            return false
        }
        let message: [String: Any] = ["payload": payloadData]
        backgroundQueuedSampleCount += samples.count

        if WCSession.default.isReachable {
            uploadMode = "Bridge"
            WCSession.default.sendMessage(message, replyHandler: { [weak self] _ in
                DispatchQueue.main.async {
                    self?.deliveredSampleCount += samples.count
                    self?.backgroundQueuedSampleCount -= samples.count
                    self?.status = self?.isRunning == true ? "Recording" : "Stopped"
                    self?.uploadMode = "Bridge"
                }
            }, errorHandler: { [weak self] error in
                DispatchQueue.main.async {
                    self?.handleBridgeFailure(samples: samples, reason: error.localizedDescription)
                }
            })
        } else {
            WCSession.default.transferUserInfo(message)
            uploadMode = "Bridge (queued)"
            status = "Queued for bridge"
        }
        return true
    }

    private func handleBridgeFailure(samples: [[String: Any]], reason: String) {
        failedBatchCount += 1
        backgroundQueuedSampleCount -= samples.count
        status = reason
        uploadMode = "Offline"
        buffer.insert(contentsOf: samples, at: 0)
        trimBufferIfNeeded()
        queuedSampleCount = buffer.count
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

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        // Server IP context updates from iPhone — no action needed on watch-only bridge mode
        _ = applicationContext
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        DispatchQueue.main.async {
            if userInfo["command"] != nil {
                _ = self.handleCommand(userInfo)
            }
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
            "sampleCount": sampleCount,
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
