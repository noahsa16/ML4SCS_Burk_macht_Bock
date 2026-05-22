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

    // H3 — effektive Sample-Rate / Batch-Größe. Default = Config; per
    // applyMotionConfig() vom iPhone (Phone-App-Setting, über den 1-s-Poll)
    // überschreibbar, in UserDefaults persistiert. Wirkt ab dem nächsten
    // start() — die Rate mitten in einer Aufnahme zu ändern wäre unsauber.
    private lazy var effectiveHz: Double = {
        let stored = UserDefaults.standard.double(forKey: "effectiveHz")
        return (10...200).contains(stored) ? stored : Config.requestedHz
    }()
    private lazy var effectiveBatchSize: Int = {
        let stored = UserDefaults.standard.integer(forKey: "effectiveBatchSize")
        return (1...200).contains(stored) ? stored : Config.batchSize
    }()

    private var buffer: [[String: Any]] = []
    private var nextSequence = 0
    // Why: WCSession-Race — replyHandler kann auch nach errorHandler eintreffen
    // (Reply-Timeout, aber iPhone hatte die Message). Set hält fest, welche
    // Sequenzen noch unbestätigt sind; der zuerst feuernde Handler entfernt
    // die seq und macht die Aktion (deliver oder fallback) — der zweite no-op.
    private var inFlightSequences: Set<Int> = []
    private var workoutSession: HKWorkoutSession?
    private var workoutBuilder: HKLiveWorkoutBuilder?
    private var finishingWorkout = false
    private var lastWorkoutRestartAttempt: Date?
    private var commandPollTimer: Timer?
    private var commandPollInFlight = false
    private var commandPollSentAt: Date?
    private var lastHandledCommandKey: String?

    // H1 — Disk-Spill. Was sonst gedroppt würde (Buffer-Overflow oder volle
    // transferUserInfo-Queue), geht als JSON-Zeile auf die Watch-Disk und wird
    // per Drain-Timer über den Live-Pfad nachgeliefert. Die Datei ist die
    // Source of Truth: eine Zeile verlässt sie erst nach bestätigtem
    // replyHandler. Übersteht App-Kill/Crash. Serielle Queue → keine Races
    // zwischen Append und Rewrite.
    private let spillQueue = DispatchQueue(label: "com.watchstreamer.motion.spill",
                                           qos: .utility)
    private var spillTimer: Timer?
    private var spillDrainInFlight = false
    private lazy var spillFileURL: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("watch_spill.jsonl")
    }()

    // Backing counters — updated per sample on main; published to SwiftUI at batch rate only.
    private var rawSampleCount = 0
    private var rawLastAccMag = 0.0
    private var rawLastGyroMag = 0.0

    @Published private(set) var sampleCount = 0
    @Published private(set) var deliveredSampleCount = 0
    @Published private(set) var backgroundQueuedSampleCount = 0
    @Published private(set) var failedBatchCount = 0
    @Published private(set) var droppedSampleCount = 0
    @Published private(set) var spilledSampleCount = 0
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
        spilledSampleCount = countSpilledSamples()
        startSpillDrain()
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
        spillTimer?.invalidate()
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
        cm.deviceMotionUpdateInterval = 1.0 / effectiveHz
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
        inFlightSequences.removeAll()
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
        guard buffer.count >= effectiveBatchSize || (force && !buffer.isEmpty) else { return }

        // Publish UI counters at batch rate (~5 Hz) instead of per-sample.
        sampleCount = rawSampleCount
        lastAccelerationMagnitude = rawLastAccMag
        lastGyroscopeMagnitude = rawLastGyroMag
        queuedSampleCount = buffer.count
        if let runStartedAt {
            actualSampleRateHz = Double(rawSampleCount) / max(0.001, Date().timeIntervalSince(runStartedAt))
        }

        let sampleCountToSend = force ? buffer.count : effectiveBatchSize
        let samples = Array(buffer.prefix(sampleCountToSend))
        buffer.removeFirst(sampleCountToSend)
        queuedSampleCount = buffer.count
        nextSequence += 1

        let envelope = makeEnvelope(samples: samples)
        if !sendViaBridge(envelope: envelope, samples: samples) {
            // WCSession nicht aktiviert — nicht zurück in den RAM-Buffer
            // (der liefe bei 500 über), sondern direkt auf Disk spillen.
            uploadMode = "Offline"
            spillEnvelope(envelope)
        }
    }

    private func makeEnvelope(samples: [[String: Any]]) -> [String: Any] {
        [
            "type": "watch_motion_batch",
            "sessionId": serverSessionId ?? sessionId,
            "sequence": nextSequence,
            "sampleRateHz": actualSampleRateHz > 1.0 ? actualSampleRateHz : effectiveHz,
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
        let seq = nextSequence
        inFlightSequences.insert(seq)
        backgroundQueuedSampleCount += samples.count

        WCSession.default.sendMessage(message, replyHandler: { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                // Why: wenn errorHandler bereits gefeuert hat (Reply-Timeout-Race),
                // ist seq weg und der Fallback wurde schon angestoßen. Dann nur
                // den UI-Counter aktualisieren, nicht doppelt zählen.
                let stillInFlight = self.inFlightSequences.remove(seq) != nil
                self.deliveredSampleCount += samples.count
                self.backgroundQueuedSampleCount = max(0, self.backgroundQueuedSampleCount - samples.count)
                self.status = self.isRunning ? "Recording" : "Stopped"
                self.uploadMode = "Bridge"
                _ = stillInFlight
            }
        }, errorHandler: { [weak self] error in
            DispatchQueue.main.async {
                guard let self else { return }
                // Why: nur fallback'n, wenn replyHandler noch nicht gewonnen hat.
                // Verhindert die zweite Lieferung desselben Batches via
                // transferUserInfo, wenn das iPhone die Message schon hatte.
                guard self.inFlightSequences.remove(seq) != nil else {
                    return
                }
                self.queueBridgeTransfer(message, envelope: envelope,
                                         reason: error.localizedDescription)
            }
        })
        return true
    }

    private func queueBridgeTransfer(_ message: [String: Any],
                                     envelope: [String: Any],
                                     reason: String) {
        let pending = WCSession.default.outstandingUserInfoTransfers.count
        guard pending < 8 else {
            // Queue voll — nicht droppen, sondern auf Disk spillen (H1).
            let n = Self.sampleCount(from: message)
            backgroundQueuedSampleCount = max(0, backgroundQueuedSampleCount - n)
            uploadMode = "Bridge (spilling)"
            spillEnvelope(envelope)
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
            "spilled_samples": spilledSampleCount,
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
        // Letzte Sicherung (sollte mit H1-Spill praktisch nie greifen):
        // Overflow nicht verwerfen, sondern als eigenes Envelope spillen.
        let overflowSamples = Array(buffer.prefix(overflow))
        buffer.removeFirst(overflow)
        nextSequence += 1
        spillEnvelope(makeEnvelope(samples: overflowSamples))
    }

    // MARK: - H1 Disk-Spill

    /// Hängt ein Envelope als JSON-Zeile an die Spill-Datei. Aufruf, wenn der
    /// Live-/Queue-Pfad gesättigt ist — verworfen wird dadurch nichts mehr.
    private func spillEnvelope(_ envelope: [String: Any]) {
        guard let line = try? JSONSerialization.data(withJSONObject: envelope) else { return }
        let n = (envelope["samples"] as? [[String: Any]])?.count ?? 0
        spilledSampleCount += n
        let url = spillFileURL
        spillQueue.async {
            if !FileManager.default.fileExists(atPath: url.path) {
                FileManager.default.createFile(atPath: url.path, contents: nil)
            }
            guard let handle = try? FileHandle(forWritingTo: url) else { return }
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            var blob = line
            blob.append(0x0A)
            try? handle.write(contentsOf: blob)
        }
    }

    /// Zählt die Samples in der Spill-Datei — beim Launch, für den UI-Counter.
    private func countSpilledSamples() -> Int {
        guard let data = try? Data(contentsOf: spillFileURL), !data.isEmpty else { return 0 }
        var total = 0
        for line in data.split(separator: 0x0A, omittingEmptySubsequences: true) {
            if let env = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any],
               let samples = env["samples"] as? [[String: Any]] {
                total += samples.count
            }
        }
        return total
    }

    private func startSpillDrain() {
        spillTimer?.invalidate()
        let timer = Timer(timeInterval: 3.0, repeats: true) { [weak self] _ in
            self?.drainSpill()
        }
        spillTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    /// Liest die älteste Spill-Zeile und schickt sie über den Live-Pfad neu.
    /// Seriell (`spillDrainInFlight`) — Spill passiert nur bei Stau, danach
    /// reicht eine Zeile pro 3-s-Tick.
    private func drainSpill() {
        guard !spillDrainInFlight,
              WCSession.default.activationState == .activated,
              WCSession.default.isReachable else { return }
        spillDrainInFlight = true
        let url = spillFileURL
        spillQueue.async { [weak self] in
            guard let self else { return }
            let firstEnvelope: [String: Any]? = {
                guard let data = try? Data(contentsOf: url), !data.isEmpty,
                      let first = data.split(separator: 0x0A,
                                             omittingEmptySubsequences: true).first
                else { return nil }
                return (try? JSONSerialization.jsonObject(with: Data(first))) as? [String: Any]
            }()
            DispatchQueue.main.async {
                if let envelope = firstEnvelope {
                    self.sendSpilled(envelope)
                } else {
                    // Datei leer/korrupt — wegwerfen, Flag freigeben.
                    self.spillQueue.async { try? FileManager.default.removeItem(at: url) }
                    self.spillDrainInFlight = false
                }
            }
        }
    }

    /// Sendet ein gespilltes Envelope via sendMessage. Erfolg → erste Zeile
    /// entfernen. Fehler → Zeile bleibt liegen, nächster Tick retryt.
    private func sendSpilled(_ envelope: [String: Any]) {
        guard WCSession.default.activationState == .activated,
              let payloadData = try? JSONSerialization.data(withJSONObject: envelope) else {
            spillDrainInFlight = false
            return
        }
        let n = (envelope["samples"] as? [[String: Any]])?.count ?? 0
        WCSession.default.sendMessage(["payload": payloadData], replyHandler: { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.deliveredSampleCount += n
                self.spilledSampleCount = max(0, self.spilledSampleCount - n)
                self.dropFirstSpillLine()
                self.spillDrainInFlight = false
            }
        }, errorHandler: { [weak self] _ in
            DispatchQueue.main.async { self?.spillDrainInFlight = false }
        })
    }

    /// Entfernt die erste Zeile der Spill-Datei. Re-liest frisch — Appends
    /// landen nur am Ende, also geht zwischenzeitlich Gespilltes nicht verloren.
    private func dropFirstSpillLine() {
        let url = spillFileURL
        spillQueue.async {
            guard let data = try? Data(contentsOf: url), !data.isEmpty else { return }
            var lines = data.split(separator: 0x0A, omittingEmptySubsequences: true)
                .map { Data($0) }
            guard !lines.isEmpty else {
                try? FileManager.default.removeItem(at: url)
                return
            }
            lines.removeFirst()
            if lines.isEmpty {
                try? FileManager.default.removeItem(at: url)
                return
            }
            var blob = Data()
            for line in lines {
                blob.append(line)
                blob.append(0x0A)
            }
            try? blob.write(to: url, options: [.atomic])
        }
    }

    private static func currentTimestampMillis() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }

    // MARK: - H3 Motion-Config

    /// Uebernimmt Sample-Rate / Batch-Groesse aus einer iPhone-Nachricht
    /// (Command / Context / Poll-Reply — alle laufen durch handleCommand).
    /// Schreibt nur bei Aenderung. Wirkt ab dem naechsten start().
    private func applyMotionConfig(from message: [String: Any]) {
        if let hz = Self.doubleValue(message["requested_hz"]),
           (10.0...200.0).contains(hz), hz != effectiveHz {
            effectiveHz = hz
            UserDefaults.standard.set(hz, forKey: "effectiveHz")
        }
        if let batch = Self.intValue(message["batch_size"]),
           (1...200).contains(batch), batch != effectiveBatchSize {
            effectiveBatchSize = batch
            UserDefaults.standard.set(batch, forKey: "effectiveBatchSize")
        }
    }

    private static func doubleValue(_ any: Any?) -> Double? {
        if let d = any as? Double { return d }
        if let i = any as? Int { return Double(i) }
        return nil
    }

    private static func intValue(_ any: Any?) -> Int? {
        if let i = any as? Int { return i }
        if let d = any as? Double { return Int(d) }
        return nil
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
        // H3: jede iPhone-Nachricht kann requested_hz / batch_size tragen.
        applyMotionConfig(from: message)
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
