import Combine
import CoreMotion
import Foundation
import HealthKit
import WatchConnectivity
import WatchKit

class MotionManager: NSObject, ObservableObject {
    private enum Config {
        static let requestedHz = 50.0
        static let batchSize = 10
        static let maxBufferedSamples = 500
    }

    private let cm = CMMotionManager()
    private let healthStore = HKHealthStore()
    private let sessionId = UUID().uuidString

    private var buffer: [[String: Any]] = []
    private var nextSequence = 0
    private var workoutSession: HKWorkoutSession?
    private var workoutBuilder: HKLiveWorkoutBuilder?
    private var finishingWorkout = false
    private var lastWorkoutRestartAttempt: Date?
    private var commandPollTimer: Timer?
    private var commandPollInFlight = false
    private var commandPollSentAt: Date?
    private var lastHandledCommandKey: String?

    // Backing counters — updated per sample on main; published to SwiftUI at batch rate only.
    private var rawSampleCount = 0
    private var rawLastAccMag = 0.0
    private var rawLastGyroMag = 0.0

    @Published private(set) var sampleCount = 0
    @Published private(set) var deliveredSampleCount = 0
    @Published private(set) var backgroundQueuedSampleCount = 0
    @Published private(set) var failedBatchCount = 0
    @Published private(set) var droppedSampleCount = 0
    @Published private(set) var queuedSampleCount = 0
    @Published private(set) var isRunning = false
    @Published private(set) var runStartedAt: Date?
    @Published private(set) var isReachable = false
    @Published private(set) var serverSessionId: String?
    @Published private(set) var uploadMode = "Offline"
    @Published private(set) var workoutStatus = "Workout idle"
    @Published private(set) var lastCommandPollStatus = "No poll yet"
    @Published private(set) var lastCommandId: String?
    @Published private(set) var actualSampleRateHz = 0.0
    @Published private(set) var lastAccelerationMagnitude = 0.0
    @Published private(set) var lastGyroscopeMagnitude = 0.0
    @Published private(set) var status = "Idle"

    override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()
        cancelStaleUserInfoTransfers()
        startCommandPolling()
    }

    /// Cancel any leftover `transferUserInfo` packets from previous app launches.
    /// Without this, undelivered transfers (e.g. from a session where the iPhone was off)
    /// pile up in WCSession's queue and block new uploads with "Bridge (queue full)".
    private func cancelStaleUserInfoTransfers() {
        let outstanding = WCSession.default.outstandingUserInfoTransfers
        guard !outstanding.isEmpty else { return }
        for transfer in outstanding {
            transfer.cancel()
        }
    }

    deinit {
        commandPollTimer?.invalidate()
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
        uploadMode = isReachable ? "Bridge" : "Bridge (polling)"
        cm.deviceMotionUpdateInterval = 1.0 / Config.requestedHz
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
            self.rawSampleCount += 1
            self.rawLastAccMag = accMag
            self.rawLastGyroMag = gyroMag
            self.trimBufferIfNeeded()
            self.flushBuffer(force: false)
        }
    }

    func stop() {
        guard isRunning || workoutSession != nil else { return }
        cm.stopDeviceMotionUpdates()
        isRunning = false
        runStartedAt = nil
        flushBuffer(force: true)
        if buffer.isEmpty {
            status = "Stopped"
        }
        endWorkoutSessionIfNeeded()
    }

    private func resetRunCounters() {
        buffer.removeAll()
        nextSequence = 0
        rawSampleCount = 0
        rawLastAccMag = 0
        rawLastGyroMag = 0
        sampleCount = 0
        deliveredSampleCount = 0
        backgroundQueuedSampleCount = 0
        failedBatchCount = 0
        droppedSampleCount = 0
        queuedSampleCount = 0
        actualSampleRateHz = 0
        lastAccelerationMagnitude = 0
        lastGyroscopeMagnitude = 0
        runStartedAt = nil
    }

    private func flushBuffer(force: Bool) {
        guard buffer.count >= Config.batchSize || (force && !buffer.isEmpty) else { return }

        // Publish UI counters at batch rate (~5 Hz) instead of per-sample.
        sampleCount = rawSampleCount
        lastAccelerationMagnitude = rawLastAccMag
        lastGyroscopeMagnitude = rawLastGyroMag
        queuedSampleCount = buffer.count
        if let runStartedAt {
            actualSampleRateHz = Double(rawSampleCount) / max(0.001, Date().timeIntervalSince(runStartedAt))
        }

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
            "sampleRateHz": actualSampleRateHz > 1.0 ? actualSampleRateHz : Config.requestedHz,
            "watchSentAt": Self.currentTimestampMillis(),
            "source": "watch_phone_bridge",
            "transport": "watchconnectivity",
            "commandId": lastCommandId ?? "",
            "samples": samples
        ]
    }

    @discardableResult
    private func sendViaBridge(envelope: [String: Any], samples: [[String: Any]]) -> Bool {
        guard WCSession.default.activationState == .activated else {
            return false
        }
        guard let payloadData = try? JSONSerialization.data(withJSONObject: envelope) else {
            return false
        }
        let message: [String: Any] = ["payload": payloadData]
        backgroundQueuedSampleCount += samples.count

        WCSession.default.sendMessage(message, replyHandler: { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.deliveredSampleCount += samples.count
                self.backgroundQueuedSampleCount = max(0, self.backgroundQueuedSampleCount - samples.count)
                self.status = self.isRunning ? "Recording" : "Stopped"
                self.uploadMode = "Bridge"
            }
        }, errorHandler: { [weak self] error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.queueBridgeTransfer(message, reason: error.localizedDescription)
            }
        })
        return true
    }

    private func queueBridgeTransfer(_ message: [String: Any], reason: String) {
        let pending = WCSession.default.outstandingUserInfoTransfers.count
        guard pending < 8 else {
            // Queue full — drop this batch rather than letting it grow unbounded.
            let n = Self.sampleCount(from: message)
            let firstDrop = droppedSampleCount == 0
            droppedSampleCount += n
            backgroundQueuedSampleCount = max(0, backgroundQueuedSampleCount - n)
            uploadMode = "Bridge (queue full)"
            if firstDrop { WKInterfaceDevice.current().play(.failure) }
            return
        }
        WCSession.default.transferUserInfo(message)
        uploadMode = pending > 0 ? "Bridge (queued \(pending + 1))" : "Bridge (queued)"
        status = "Queued for bridge: \(reason)"
    }

    private func startCommandPolling() {
        commandPollTimer?.invalidate()
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.pollPhoneForCommand()
        }
        commandPollTimer = timer
        RunLoop.main.add(timer, forMode: .common)
        pollPhoneForCommand()
    }

    private func pollPhoneForCommand() {
        // Watchdog: if a poll has been in-flight for >3 s without a reply, force-clear the flag.
        if commandPollInFlight, let sentAt = commandPollSentAt,
           Date().timeIntervalSince(sentAt) > 3.0 {
            commandPollInFlight = false
        }
        guard WCSession.default.activationState == .activated, !commandPollInFlight else { return }
        commandPollInFlight = true
        commandPollSentAt = Date()
        let message: [String: Any] = [
            "type": "command_poll",
            "is_running": isRunning,
            "session_id": serverSessionId ?? "",
            "sample_count": sampleCount,
            "queued_samples": queuedSampleCount,
            "delivered_samples": deliveredSampleCount,
            "failed_batches": failedBatchCount,
            "last_command_id": lastCommandId ?? "",
            "upload_mode": uploadMode
        ]

        WCSession.default.sendMessage(message, replyHandler: { [weak self] reply in
            DispatchQueue.main.async {
                guard let self else { return }
                self.commandPollInFlight = false
                self.isReachable = true
                self.lastCommandPollStatus = "Phone replied"
                _ = self.handleCommand(reply)
                if self.isRunning && self.status.hasPrefix("Phone bridge") {
                    self.status = "Recording"
                }
            }
        }, errorHandler: { [weak self] error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.commandPollInFlight = false
                self.isReachable = false
                self.lastCommandPollStatus = error.localizedDescription
                // Fallback: push status via transferUserInfo (background-safe, doesn't need isReachable).
                // Throttled by queue size to prevent buildup if iPhone is unreachable for a while.
                if WCSession.default.outstandingUserInfoTransfers.count < 4 {
                    var pollUserInfo = message
                    pollUserInfo["fallback"] = true
                    WCSession.default.transferUserInfo(pollUserInfo)
                }
                if !self.isRunning {
                    self.status = "Phone bridge unavailable: \(error.localizedDescription)"
                }
            }
        })
    }

    private func noteFinishedBackgroundTransfer(_ userInfo: [String: Any], error: Error?) {
        let sampleCount = Self.sampleCount(from: userInfo)
        if let error {
            failedBatchCount += 1
            status = "Queued bridge failed: \(error.localizedDescription)"
            return
        }
        deliveredSampleCount += sampleCount
        backgroundQueuedSampleCount = max(0, backgroundQueuedSampleCount - sampleCount)
        uploadMode = isReachable ? "Bridge" : "Bridge (queued)"
        status = isRunning ? "Recording" : "Stopped"
    }

    private static func sampleCount(from userInfo: [String: Any]) -> Int {
        guard let payloadData = userInfo["payload"] as? Data,
              let decoded = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any],
              let samples = decoded["samples"] as? [[String: Any]]
        else { return 0 }
        return samples.count
    }

    private func trimBufferIfNeeded() {
        guard buffer.count > Config.maxBufferedSamples else { return }
        let overflow = buffer.count - Config.maxBufferedSamples
        let firstDrop = droppedSampleCount == 0
        buffer.removeFirst(overflow)
        droppedSampleCount += overflow
        if firstDrop {
            // One haptic so the user notices even when not looking at the stats page.
            WKInterfaceDevice.current().play(.failure)
        }
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
        DispatchQueue.main.async {
            if applicationContext["command"] != nil {
                _ = self.handleCommand(applicationContext)
            }
        }
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        DispatchQueue.main.async {
            if userInfo["command"] != nil {
                _ = self.handleCommand(userInfo)
            }
        }
    }

    @discardableResult
    fileprivate func handleCommand(_ message: [String: Any]) -> [String: Any] {
        guard let command = message["command"] as? String else {
            return ["ok": false, "error": "Missing command"]
        }
        let sid = message["session_id"] as? String
        let commandId = message["command_id"] as? String
        let commandKey = "\(command)|\(sid ?? "")|\(commandId ?? "")"
        if lastHandledCommandKey == commandKey {
            let alreadyApplied =
                (command == "start" && isRunning && (sid == nil || sid == serverSessionId)) ||
                (command == "stop" && !isRunning)
            if alreadyApplied {
                return [
                    "ok": true,
                    "command": command,
                    "command_id": lastCommandId ?? "",
                    "duplicate": true,
                    "isRunning": isRunning,
                    "session_id": serverSessionId ?? "",
                    "sampleCount": sampleCount,
                    "uploadMode": uploadMode
                ]
            }
        }

        switch command {
        case "start":
            if isRunning, let sid, !sid.isEmpty, sid != serverSessionId {
                stop()
            }
            if !isRunning {
                start(sessionId: sid)
            } else if let sid, !sid.isEmpty {
                serverSessionId = sid
            }
        case "stop":
            stop()
            serverSessionId = nil
        default:
            return ["ok": false, "error": "Unknown command", "command": command]
        }
        let applied =
            (command == "start" && isRunning && (sid == nil || sid == serverSessionId)) ||
            (command == "stop" && !isRunning)
        guard applied else {
            return [
                "ok": false,
                "command": command,
                "command_id": commandId ?? "",
                "isRunning": isRunning,
                "session_id": serverSessionId ?? "",
                "sampleCount": sampleCount,
                "uploadMode": uploadMode,
                "error": status
            ]
        }
        if let commandId, !commandId.isEmpty {
            lastCommandId = commandId
        }
        lastHandledCommandKey = commandKey
        return [
            "ok": true,
            "command": command,
            "command_id": lastCommandId ?? "",
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

    func session(_ session: WCSession,
                 didFinish userInfoTransfer: WCSessionUserInfoTransfer,
                 error: Error?) {
        DispatchQueue.main.async {
            self.noteFinishedBackgroundTransfer(userInfoTransfer.userInfo, error: error)
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
