import Combine
import Foundation
import UIKit
import WatchConnectivity

/// Maintains a WebSocket connection to the FastAPI server.
/// Forwards "start" / "stop" commands to the Watch via WatchConnectivity.
class ServerCommandListener: NSObject, ObservableObject {
    static let shared = ServerCommandListener()

    @Published var isConnected = false
    @Published var currentSessionId: String?
    @Published var currentPersonId: String?
    @Published var currentCommandId: String?
    // Why: read by makePhoneStatus, which also runs on the WCSession background
    // thread via the poll path. Mirror every write under the poll lock so that
    // read gets a consistent value instead of racing the main-thread setter.
    @Published var lastWatchCommandStatus = "No command sent" {
        didSet {
            let value = lastWatchCommandStatus
            pollStateLock.withLock { _lastCommandStatusMirror = value }
        }
    }
    @Published var lastWatchPollStatus = "No Watch poll yet"
    @Published var watchPolling = false
    @Published var watchPollAgeMs: Int?
    @Published var watchRunning = false
    @Published var watchSessionId = ""
    @Published var watchSampleCount = 0
    @Published var watchQueuedSamples = 0
    @Published var watchDeliveredSamples = 0
    @Published var watchFailedBatches = 0
    @Published var watchLastCommandId = ""
    @Published var watchUploadMode = "Offline"
    @Published var watchActualHz: Double = 0
    // Why this exists: without it, a focus session whose HKWorkoutSession
    // failed to start (e.g. a denied permission prompt) looks identical to a
    // healthy one — isRunning stays true, but the stream dies the moment the
    // wrist lowers. No retry or UI is built on this yet; it only makes the
    // failure observable.
    @Published var watchWorkoutFailed = false
    @Published var liveInference: LiveInferencePayload?

    private var reconnectWorkItem: DispatchWorkItem?
    private var pollAgeTimer: Timer?

    // MARK: – WebSocket generation state
    //
    // Why locked: `connect()` runs on main while receive/send callbacks run on
    // URLSession's delegate queue. The epoch exists to reject stale callbacks,
    // but reading `connectionEpoch` and `task` as separate unsynchronized
    // fields meant a callback could observe a torn pair — a new epoch with the
    // old task, or the reverse — so the guard could not do the job it was
    // written for. Every access now goes through one lock, and the epoch check
    // and task read happen in the same critical section.
    private let socketStateLock = NSLock()
    private var _task: URLSessionWebSocketTask?
    /// Identifies the current WebSocket "generation". Each connect() bumps this.
    /// Stale receive/send callbacks check their captured epoch and bail out if
    /// the current epoch has moved on — so a cancelled task's failure handler
    /// can never schedule a reconnect against the live connection.
    private var _connectionEpoch: Int = 0
    private var _sentHello = false

    /// Installs a new generation. Returns the epoch the caller must carry.
    private func beginConnection(_ newTask: URLSessionWebSocketTask?) -> Int {
        socketStateLock.withLock {
            _connectionEpoch &+= 1
            _task = newTask
            _sentHello = false
            return _connectionEpoch
        }
    }

    /// The live task, but only while `epoch` is still current.
    private func liveTask(forEpoch epoch: Int) -> URLSessionWebSocketTask? {
        socketStateLock.withLock { epoch == _connectionEpoch ? _task : nil }
    }

    private func socketSnapshot() -> (task: URLSessionWebSocketTask?, epoch: Int) {
        socketStateLock.withLock { (_task, _connectionEpoch) }
    }

    /// Compare-and-set: exactly one caller per generation may send the hello
    /// frame, even when two messages arrive back to back.
    private func claimHello(epoch: Int) -> Bool {
        socketStateLock.withLock {
            guard epoch == _connectionEpoch, !_sentHello else { return false }
            _sentHello = true
            return true
        }
    }

    /// Guarded by `pollStateLock` — `confirmCommandFromWatchPoll` runs on the
    /// WCSession background thread, so an unsynchronized check-then-set let two
    /// overlapping polls both emit the same `watch_ack`.
    private var _lastPollAckKey: String?

    /// Atomically claims an acknowledgement key. Returns true for the first
    /// caller only, so the duplicate-suppression is a real compare-and-set.
    private func claimPollAck(_ key: String) -> Bool {
        pollStateLock.withLock {
            guard _lastPollAckKey != key else { return false }
            _lastPollAckKey = key
            return true
        }
    }
    // Protected by pollStateLock — written from WCSession bg thread, read from main-thread timer.
    private let pollStateLock = NSLock()
    private var _lastWatchPollAt: Date?
    private var _lastWatchSnapshot: [String: Any] = [:]
    private var _lastCommandStatusMirror = "No command sent"
    /// Background-safe snapshot of `lastWatchCommandStatus`.
    private var lastCommandStatusSnapshot: String {
        pollStateLock.withLock { _lastCommandStatusMirror }
    }
    private var lastWatchPollAt: Date? {
        get { pollStateLock.withLock { _lastWatchPollAt } }
        set { pollStateLock.withLock { _lastWatchPollAt = newValue } }
    }
    private var lastWatchSnapshot: [String: Any] {
        get { pollStateLock.withLock { _lastWatchSnapshot } }
        set { pollStateLock.withLock { _lastWatchSnapshot = newValue } }
    }

    // Why: poll-freshness threshold (ms). A Watch poll older than this counts as
    // "not polling". Was a bare 3000 literal at three call sites.
    private static let pollFreshMs = 3000

    // Why: currentSessionId/currentPersonId/currentCommandId are @Published (main
    // thread, for the UI) but are read on the WCSession bg thread in the poll path
    // (handleWatchCommandPoll → currentWatchCommandPayload / confirmCommandFromWatchPoll,
    // plus sendPhoneStatus via the listenLoop receive callback). Mirror them under a
    // lock so the bg read gets a consistent snapshot instead of racing the setters.
    private let sessionStateLock = NSLock()
    private var _sessionSnapshot: (sessionId: String?, personId: String?, commandId: String?) = (nil, nil, nil)
    private func syncSessionStateSnapshot() {
        let snap: (sessionId: String?, personId: String?, commandId: String?) =
            (currentSessionId, currentPersonId, currentCommandId)
        sessionStateLock.withLock { _sessionSnapshot = snap }
    }
    private func sessionStateSnapshot() -> (sessionId: String?, personId: String?, commandId: String?) {
        sessionStateLock.withLock { _sessionSnapshot }
    }

    private var serverIP: String { ServerConfig.configuredIP }
    private var serverWebSocketURL: URL? { ServerConfig.endpoint?.webSocket }

    private override init() {
        super.init()
        connect()
        startPollAgeTimer()
        NotificationCenter.default.addObserver(
            self, selector: #selector(appWillEnterForeground),
            name: UIApplication.willEnterForegroundNotification, object: nil)
    }

    /// Why: iOS can silently tear down a backgrounded WebSocket without a read/send
    /// error firing, so the failure-driven reconnect never triggers. Proactively
    /// reconnect on return to foreground instead of waiting for the next failed I/O.
    @objc private func appWillEnterForeground() {
        reconnectAndRefresh()
    }

    func connect() {
        reconnectWorkItem?.cancel()
        reconnectWorkItem = nil
        socketSnapshot().task?.cancel(with: .goingAway, reason: nil)

        guard let url = serverWebSocketURL else {
            // Why: still bump the generation so callbacks from the cancelled
            // task cannot mistake themselves for current.
            _ = beginConnection(nil)
            isConnected = false
            return
        }
        let newTask = URLSession.shared.webSocketTask(with: url)
        let epoch = beginConnection(newTask)
        newTask.resume()
        isConnected = false
        listenLoop(epoch: epoch)
    }

    private func listenLoop(epoch: Int) {
        guard let task = liveTask(forEpoch: epoch) else { return }
        task.receive { [weak self] result in
            guard let self, self.liveTask(forEpoch: epoch) != nil else { return }
            switch result {
            case .failure:
                DispatchQueue.main.async { self.isConnected = false }
                self.scheduleReconnect()
            case .success(let msg):
                DispatchQueue.main.async { self.isConnected = true }
                if self.claimHello(epoch: epoch) {
                    self.sendServerEvent(["type": "hello", "client": "iphone"])
                    self.sendPhoneStatus()
                }
                self.handle(msg)
                self.listenLoop(epoch: epoch)
            }
        }
    }

    // Live-Inference rides on the 1 Hz status broadcast as a nested object.
    // A missing/null live_inference (predict() returned None this tick) keeps
    // the last value rather than flickering the UI off.
    private func updateLiveInference(from json: [String: Any]) {
        guard let dict = json["live_inference"] as? [String: Any],
              let data = try? JSONSerialization.data(withJSONObject: dict),
              let payload = try? JSONDecoder().decode(LiveInferencePayload.self, from: data) else {
            return
        }
        DispatchQueue.main.async { self.liveInference = payload }
    }

    private func handle(_ message: URLSessionWebSocketTask.Message) {
        let text: String
        switch message {
        case .string(let s):  text = s
        case .data(let d):    text = String(data: d, encoding: .utf8) ?? ""
        @unknown default:     return
        }

        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let type = json["type"] as? String ?? text.trimmingCharacters(in: .whitespaces)

        updateLiveInference(from: json)

        DispatchQueue.main.async {
            if type == "start" {
                let sid = json["session_id"] as? String
                let pid = json["person_id"] as? String
                let commandId = self.extractCommandId(from: json)
                self.currentSessionId = sid
                self.currentPersonId  = pid
                self.currentCommandId = commandId
                self.forwardToWatch(self.watchPayload(command: "start",
                                                      sessionId: sid,
                                                      personId: pid,
                                                      commandId: commandId))
            } else if type == "stop" {
                let commandId = self.extractCommandId(from: json)
                self.currentCommandId = commandId
                self.forwardToWatch(self.watchPayload(command: "stop",
                                                      sessionId: json["session_id"] as? String,
                                                      personId: nil,
                                                      commandId: commandId))
                self.currentSessionId = nil
                self.currentPersonId  = nil
            } else if type == "status" {
                let active = json["session_active"] as? Bool ?? false
                let commandId = self.extractCommandId(from: json)
                if let hz = json["watch_rate_hz"] as? Double, hz > 0 {
                    self.watchActualHz = hz
                }
                if active, let sid = json["session_id"] as? String {
                    let pid = json["person_id"] as? String
                    let shouldForward = self.currentSessionId != sid ||
                        (commandId != nil && commandId != self.currentCommandId)
                    if shouldForward {
                        self.currentCommandId = commandId
                        self.forwardToWatch(self.watchPayload(command: "start",
                                                              sessionId: sid,
                                                              personId: pid,
                                                              commandId: commandId))
                    }
                    self.currentSessionId = sid
                    self.currentPersonId = pid
                } else if self.currentSessionId != nil {
                    self.currentCommandId = commandId
                    self.forwardToWatch(self.watchPayload(command: "stop",
                                                          sessionId: self.currentSessionId,
                                                          personId: nil,
                                                          commandId: commandId))
                    self.currentSessionId = nil
                    self.currentPersonId = nil
                }
                self.sendPhoneStatus()
            }
            // Why: mirror the just-applied session/command state for the bg poll path.
            self.syncSessionStateSnapshot()
        }
    }

    private func extractCommandId(from json: [String: Any]) -> String? {
        if let commandId = json["command_id"] as? String, !commandId.isEmpty {
            return commandId
        }
        if let watchCommand = json["watch_command"] as? [String: Any],
           let commandId = watchCommand["command_id"] as? String,
           !commandId.isEmpty {
            return commandId
        }
        return nil
    }

    private func watchPayload(command: String,
                              sessionId: String?,
                              personId: String?,
                              commandId: String?) -> [String: Any] {
        var payload: [String: Any] = [WatchPayloadKey.command: command,
                                      WatchPayloadKey.serverIP: serverIP]
        if let sessionId, !sessionId.isEmpty { payload["session_id"] = sessionId }
        if let personId, !personId.isEmpty { payload["person_id"] = personId }
        if let commandId, !commandId.isEmpty { payload["command_id"] = commandId }
        // H3: Motion-Config aus den Phone-App-Settings mitgeben. Die Watch
        // liest sie in handleCommand() — auch via 1-s-Poll-Reply, also ohne
        // dass ein expliziter Push nötig wäre.
        let hz = UserDefaults.standard.double(forKey: CaptureSettings.requestedHzKey)
        if CaptureSettings.isValidHz(hz) { payload[WatchPayloadKey.requestedHz] = hz }
        let batch = UserDefaults.standard.integer(forKey: CaptureSettings.batchSizeKey)
        if CaptureSettings.isValidBatchSize(batch) { payload[WatchPayloadKey.batchSize] = batch }
        return payload
    }

    func currentWatchCommandPayload() -> [String: Any] {
        // Why: read the lock-protected snapshot — this also runs on the WCSession
        // bg thread via handleWatchCommandPoll.
        let snap = sessionStateSnapshot()
        if let sid = snap.sessionId {
            return watchPayload(command: "start",
                                sessionId: sid,
                                personId: snap.personId,
                                commandId: snap.commandId)
        }
        return watchPayload(command: "stop",
                            sessionId: nil,
                            personId: nil,
                            commandId: snap.commandId)
    }

    func handleWatchCommandPoll(_ message: [String: Any]) -> [String: Any] {
        lastWatchPollAt = Date()
        lastWatchSnapshot = message
        var payload = currentWatchCommandPayload()
        let command = payload["command"] as? String ?? "unknown"
        let watchRunning = message["is_running"] as? Bool ?? false
        let watchSessionId = message["session_id"] as? String ?? ""
        let watchLastCommandId = message["last_command_id"] as? String ?? ""
        payload["ok"] = true
        payload["source"] = "iphone_command_poll"
        payload["server_connected"] = isConnected
        let pollStatus = "poll \(command)"
        DispatchQueue.main.async {
            self.lastWatchPollStatus = pollStatus
        }
        updatePublishedWatchStatus(from: message, pollAgeMs: 0)
        confirmCommandFromWatchPoll(command: command,
                                    watchRunning: watchRunning,
                                    watchSessionId: watchSessionId,
                                    watchLastCommandId: watchLastCommandId)
        // Why: a poll just arrived, so the Watch is reachable and polling (age 0).
        sendServerEvent(makePhoneStatus(watchInfo: message,
                                        reachable: true,
                                        polling: true,
                                        pollAgeMs: 0,
                                        pollStatus: pollStatus))
        return payload
    }

    func refreshWatchContext() {
        forwardToWatch(currentWatchCommandPayload())
    }

    func reconnectAndRefresh() {
        connect()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            self.refreshWatchContext()
            self.sendPhoneStatus()
        }
    }

    /// „Spill jetzt senden": die Watch drained ihren persistenten Buffer im
    /// Burst statt 1 Zeile/3 s. Nicht-destruktiv.
    func drainWatchSpill() {
        forwardToWatch([WatchPayloadKey.command: WatchCommandName.drainSpill.rawValue,
                        WatchPayloadKey.serverIP: serverIP])
    }

    /// „Spill verwerfen": die Watch löscht ihren persistenten Buffer. Die Watch
    /// verweigert das während einer laufenden Aufnahme (Schutz des Live-Staus).
    func clearWatchSpill() {
        forwardToWatch([WatchPayloadKey.command: WatchCommandName.clearSpill.rawValue,
                        WatchPayloadKey.serverIP: serverIP])
    }

    /// Asks the Watch to begin a focus session.
    ///
    /// Why a deadline: `sendMessage` does not guarantee that either handler
    /// runs. Without it the caller waits forever and the screen sits in
    /// `starting` with no way back — the failure this project already shipped
    /// once on pull-to-refresh.
    func startFocusSession(timeout: TimeInterval = 8) async -> Bool {
        await withCheckedContinuation { continuation in
            var resumed = false
            let deadline = DispatchWorkItem {
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: false)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout, execute: deadline)
            forwardToWatch([WatchPayloadKey.command: WatchCommandName.focusStart.rawValue,
                            WatchPayloadKey.commandID: UUID().uuidString]) { reply in
                guard !resumed else { return }
                resumed = true
                deadline.cancel()
                continuation.resume(returning: reply[WatchPayloadKey.ok] as? Bool ?? false)
            }
        }
    }

    /// Asks the Watch to end a focus session and restore its previous rate.
    ///
    /// Bounded for the same reason as the start, and the answer matters more:
    /// the Watch streams raw sensors until it hears this, so a caller that
    /// waited forever would have no way to report that the stream may still
    /// be running.
    ///
    /// - Returns: whether the Watch confirmed the stop.
    func stopFocusSession(timeout: TimeInterval = 8) async -> Bool {
        await withCheckedContinuation { continuation in
            var resumed = false
            let deadline = DispatchWorkItem {
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: false)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout, execute: deadline)
            forwardToWatch([WatchPayloadKey.command: WatchCommandName.focusStop.rawValue,
                            WatchPayloadKey.commandID: UUID().uuidString]) { reply in
                guard !resumed else { return }
                resumed = true
                deadline.cancel()
                continuation.resume(returning: reply[WatchPayloadKey.ok] as? Bool ?? false)
            }
        }
    }

    @Published var sensorProbeVerdict: SensorProbeVerdict?
    @Published var sensorProbeRaw: String?
    /// Wall-Zeit, die `SensorProbe.report()` fuer den CMSensorRecorder-Read
    /// gebraucht hat — Diagnose-Gold fuer einen Schritt, der nur wenige Male
    /// laufen kann: unterscheidet einen langsamen, aber funktionierenden Read
    /// von einem, der in den sendMessage-Timeout gelaufen ist.
    @Published var sensorProbeReadDuration: Double?
    @Published var parityResult: String?
    @Published var parityRaw: String?

    /// Status of the most recent probe-start attempt, in the operator's words.
    @Published var sensorProbeStartStatus: String?

    func startSensorProbe(durationSeconds: Double) {
        // Why: a stale verdict/raw from a previous probe left standing while
        // this one runs is the worst outcome for a step the operator can
        // only repeat a few times — reset before the new run, not after.
        sensorProbeVerdict = nil
        sensorProbeRaw = nil
        sensorProbeReadDuration = nil
        sensorProbeStartStatus = nil
        // Why: a stable per-attempt identity makes the start idempotent on the
        // Watch. Without it a duplicate delivery restarted the recorder and
        // discarded a run already in progress — for the 12-hour probe that is
        // half a day of hardware time.
        let operationID = UUID().uuidString
        forwardToWatch([WatchPayloadKey.command: WatchCommandName.sensorProbeStart.rawValue,
                        WatchPayloadKey.durationSeconds: durationSeconds,
                        WatchPayloadKey.operationID: operationID]) { [weak self] reply in
            self?.sensorProbeRaw = String(describing: reply)
            self?.sensorProbeStartStatus = Self.probeStartStatus(from: reply)
        }
    }

    /// Translates a probe-start reply into a line the operator can act on.
    static func probeStartStatus(from reply: [String: Any]) -> String {
        let ok = WatchPayloadValue.bool(reply[WatchPayloadKey.ok]) ?? false
        guard ok else {
            let error = reply[WatchPayloadKey.error] as? String ?? "unknown error"
            if let remaining = WatchPayloadValue.double(reply["remainingSeconds"]) {
                return "\(error) — noch \(Int(remaining.rounded())) s"
            }
            return error
        }
        if WatchPayloadValue.bool(reply["alreadyStarted"]) == true {
            return "Läuft bereits (dieselbe Anforderung, nicht neu gestartet)"
        }
        let requested = WatchPayloadValue.double(reply["requestedSeconds"]) ?? 0
        return "Gestartet für \(Int(requested.rounded())) s"
    }

    func fetchSensorProbeReport() {
        sensorProbeVerdict = nil
        sensorProbeRaw = nil
        sensorProbeReadDuration = nil
        forwardToWatch([WatchPayloadKey.command: WatchCommandName.sensorProbeReport.rawValue]) { [weak self] reply in
            self?.sensorProbeRaw = String(describing: reply)
            self?.sensorProbeReadDuration = reply["readDurationSeconds"] as? Double
            self?.sensorProbeVerdict = Self.verdict(from: reply)
        }
    }

    /// P3 — stösst die Golden-Vektor-Paritätsprüfung des Passiv-Modells auf
    /// der Watch an (WatchParityCheck.run()) und übersetzt die Antwort in
    /// einen lesbaren Status für das Admin-Panel.
    func runWatchParityCheck() {
        parityResult = nil
        parityRaw = nil
        forwardToWatch([WatchPayloadKey.command: WatchCommandName.parityCheck.rawValue]) { [weak self] reply in
            self?.parityRaw = String(describing: reply)
            let ok = (reply["ok"] as? Bool) ?? true
            guard ok else {
                self?.parityResult = "Fehler: " + ((reply["error"] as? String) ?? "unbekannt")
                return
            }
            let total = (reply["total"] as? Int) ?? 0
            let passed = (reply["passed"] as? Int) ?? 0
            let maxDiff = (reply["maxAbsDiff"] as? Double) ?? .nan
            let mismatch = (reply["classMismatches"] as? Int) ?? -1
            var text = String(
                format: "%d/%d bestanden, max |Δ| = %.2e, Klassenwechsel: %d",
                passed, total, maxDiff, mismatch)
            if passed < total, let failedIds = reply["failedIds"] as? [String], !failedIds.isEmpty {
                text += " — fehlgeschlagen: " + failedIds.joined(separator: ", ")
            }
            self?.parityResult = text
        }
    }

    /// Uebersetzt die Watch-Antwort in SensorProbeStats und bewertet sie.
    /// Why: WCSession erlaubt keine Int-Schluessel, das Histogramm kommt als
    /// [String: Int] und wird hier zurueckgemappt.
    static func verdict(from reply: [String: Any]) -> SensorProbeVerdict? {
        guard let count = reply["sampleCount"] as? Int else { return nil }
        let rawBuckets = (reply["intervalBucketsMs"] as? [String: Int]) ?? [:]
        var buckets: [Int: Int] = [:]
        for (k, v) in rawBuckets { if let key = Int(k) { buckets[key] = v } }
        let requestedSeconds = (reply["requestedSeconds"] as? Double) ?? 0
        let stats = SensorProbeStats(
            sampleCount: count,
            firstTimestamp: (reply["firstTimestamp"] as? Double) ?? 0,
            lastTimestamp: (reply["lastTimestamp"] as? Double) ?? 0,
            requestedSeconds: requestedSeconds,
            // Why: older replies without the field default to "fully
            // elapsed" so coverage falls back to the pre-fix behaviour
            // rather than silently reading 0.
            actualSpanSeconds: (reply["actualSpanSeconds"] as? Double) ?? requestedSeconds,
            intervalBucketsMs: buckets,
            maxGapSeconds: (reply["maxGapSeconds"] as? Double) ?? 0,
            nonMonotonicCount: (reply["nonMonotonicCount"] as? Int) ?? 0,
            fetchReturnedNil: (reply["fetchReturnedNil"] as? Bool) ?? false
        )
        return SensorProbeEvaluator.evaluate(stats)
    }

    private func updatePublishedWatchStatus(from message: [String: Any], pollAgeMs: Int?) {
        DispatchQueue.main.async {
            self.watchPolling = (pollAgeMs ?? 0) < Self.pollFreshMs
            self.watchPollAgeMs = pollAgeMs
            self.watchRunning = message["is_running"] as? Bool ?? false
            self.watchSessionId = message["session_id"] as? String ?? ""
            self.watchSampleCount = message["sample_count"] as? Int ?? 0
            self.watchQueuedSamples = message["queued_samples"] as? Int ?? 0
            self.watchDeliveredSamples = message["delivered_samples"] as? Int ?? 0
            self.watchFailedBatches = message["failed_batches"] as? Int ?? 0
            self.watchLastCommandId = message["last_command_id"] as? String ?? ""
            self.watchUploadMode = message["upload_mode"] as? String ?? "Offline"
            self.watchWorkoutFailed = message["workout_failed"] as? Bool ?? false
        }
    }

    private func confirmCommandFromWatchPoll(command: String,
                                             watchRunning: Bool,
                                             watchSessionId: String,
                                             watchLastCommandId: String) {
        let snap = sessionStateSnapshot()
        let expectedSessionId = snap.sessionId ?? ""
        let expectedCommandId = snap.commandId ?? ""
        let commandIdMatches = expectedCommandId.isEmpty || watchLastCommandId == expectedCommandId
        let commandApplied = commandIdMatches && (
            (command == "start" && watchRunning && watchSessionId == expectedSessionId) ||
            (command == "stop" && !watchRunning)
        )
        guard commandApplied else { return }

        let ackKey = "\(command)|\(expectedSessionId)|\(watchRunning)|\(expectedCommandId)"
        guard claimPollAck(ackKey) else { return }
        let status = "\(command): confirmed by Watch poll"
        DispatchQueue.main.async {
            self.lastWatchCommandStatus = status
        }
        sendServerEvent([
            "type": "watch_ack",
            "ok": true,
            "command": command,
            "session_id": expectedSessionId,
            "command_id": expectedCommandId,
            "detail": "Watch confirmed command via iPhone poll",
            "reply": [
                "isRunning": watchRunning,
                "session_id": watchSessionId,
                "last_command_id": watchLastCommandId
            ]
        ])
    }

    func forwardToWatch(_ payload: [String: Any],
                        onReply: (([String: Any]) -> Void)? = nil) {
        let command = payload[WatchPayloadKey.command] as? String ?? "unknown"
        let sessionId = payload[WatchPayloadKey.sessionID] as? String
        let commandId = payload[WatchPayloadKey.commandID] as? String

        // Why: the transport class decides which delivery paths may be used.
        // An unrecognised command is treated as non-durable — the destructive
        // steps below must be opt-in, never a default for something we cannot
        // classify.
        let route = WatchCommandName(rawValue: command)
        let mayReplaceDurableState = route?.mayReplaceDurableState ?? false
        let mayFallBackToUserInfo = route?.mayFallBackToUserInfo ?? false

        if mayReplaceDurableState {
            // Why: ein neuer Befehl macht alle gequeueten älteren obsolet. Ohne
            // Cancel stellt die transferUserInfo-FIFO Minuten-alte stop/start-
            // Paare mitten in eine laufende Session zu (S044, 2026-06-12).
            // Spiegelbild von cancelStaleUserInfoTransfers() auf der Watch-Seite;
            // phone-seitig laufen über transferUserInfo ausschließlich Commands.
            //
            // Gated on the transport class since 2026-08-29: this ran for every
            // command, so a read-only probe report or parity check erased
            // pending start/stop recovery state on its way out.
            for transfer in WCSession.default.outstandingUserInfoTransfers {
                transfer.cancel()
            }

            // Push when possible, but the MVP does not depend on this path:
            // the Watch also pulls the latest command via command_poll.
            do {
                try WCSession.default.updateApplicationContext(payload)
            } catch {
                lastWatchCommandStatus = "\(command): context failed"
            }
        }

        WCSession.default.sendMessage(payload, replyHandler: { [weak self] reply in
            DispatchQueue.main.async {
                let replyOk = reply["ok"] as? Bool ?? true
                self?.lastWatchCommandStatus = replyOk ? "\(command): acknowledged" : "\(command): failed"
                self?.sendServerEvent([
                    "type": "watch_ack",
                    "ok": replyOk,
                    "command": command,
                    "session_id": sessionId ?? "",
                    "command_id": commandId ?? "",
                    "detail": replyOk ? "Watch acknowledged command" : "Watch rejected command",
                    "reply": reply
                ])
                self?.sendPhoneStatus()
                onReply?(reply)
            }
        }, errorHandler: { [weak self] error in
            DispatchQueue.main.async {
                // Why: only durable state may be re-sent through the queue. The
                // Watch discards context and user-info copies of a diagnostic,
                // so queueing one produced a delivery guaranteed to be ignored
                // while telling the caller it was on its way.
                if mayFallBackToUserInfo {
                    self?.transferUserInfoToWatch(payload, command: command)
                    onReply?([
                        WatchPayloadKey.ok: false,
                        WatchPayloadKey.command: command,
                        WatchPayloadKey.error:
                            "sendMessage failed (\(error.localizedDescription)); "
                            + "queued via transferUserInfo, no reply will follow"
                    ])
                    return
                }
                // Why: transferUserInfo has no reply channel back to the
                // iPhone, so a diagnostic caller (sensor probe / parity
                // check) would otherwise wait forever with no feedback at
                // all — exactly the "Watch unreachable" state the spike
                // protocol's app-kill step produces. Report the transport
                // failure as the terminal result it is.
                self?.lastWatchCommandStatus = "\(command): Watch unreachable"
                self?.sendPhoneStatus()
                onReply?([
                    WatchPayloadKey.ok: false,
                    WatchPayloadKey.command: command,
                    WatchPayloadKey.error:
                        "Watch unreachable (\(error.localizedDescription)); "
                        + "the query did not run"
                ])
            }
        })
    }

    private func transferUserInfoToWatch(_ payload: [String: Any],
                                         command: String) {
        WCSession.default.transferUserInfo(payload)
        lastWatchCommandStatus = "\(command): waiting for Watch poll"
        sendPhoneStatus()
    }

    private func sendServerEvent(_ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8)
        else { return }

        let (task, epoch) = socketSnapshot()
        guard let task else { return }
        task.send(.string(text)) { [weak self] error in
            guard let self, error != nil,
                  self.liveTask(forEpoch: epoch) != nil else { return }
            DispatchQueue.main.async { self.isConnected = false }
            self.scheduleReconnect()
        }
    }

    // Why: single builder for the phone_status payload — was duplicated between
    // the poll path and sendPhoneStatus with drift-prone field subsets.
    private func makePhoneStatus(watchInfo: [String: Any],
                                 reachable: Bool,
                                 polling: Bool,
                                 pollAgeMs: Int?,
                                 pollStatus: String) -> [String: Any] {
        let snap = sessionStateSnapshot()
        return [
            "type": "phone_status",
            "watch_reachable": reachable,
            "watch_polling": polling,
            "watch_poll_age_ms": pollAgeMs ?? -1,
            "watch_running": watchInfo["is_running"] as? Bool ?? false,
            "watch_session_id": watchInfo["session_id"] as? String ?? "",
            "watch_samples": watchInfo["sample_count"] as? Int ?? 0,
            "watch_queued_samples": watchInfo["queued_samples"] as? Int ?? 0,
            "watch_delivered_samples": watchInfo["delivered_samples"] as? Int ?? 0,
            "watch_failed_batches": watchInfo["failed_batches"] as? Int ?? 0,
            "watch_upload_mode": watchInfo["upload_mode"] as? String ?? "",
            "current_session_id": snap.sessionId ?? "",
            "current_command_id": snap.commandId ?? "",
            "watch_last_command_id": watchInfo["last_command_id"] as? String ?? "",
            "last_watch_command_status": lastCommandStatusSnapshot,
            "last_watch_poll_status": pollStatus,
        ]
    }

    func sendPhoneStatus() {
        let pollAgeMs = lastWatchPollAt.map { Int(Date().timeIntervalSince($0) * 1000) }
        let polling = pollAgeMs.map { $0 < Self.pollFreshMs } ?? false
        sendServerEvent(makePhoneStatus(watchInfo: lastWatchSnapshot,
                                        reachable: WCSession.default.isReachable || polling,
                                        polling: polling,
                                        pollAgeMs: pollAgeMs,
                                        pollStatus: lastWatchPollStatus))
    }

    private func scheduleReconnect() {
        // Why: the reconnect is debounced by 3 s, but failing WS sends recur at
        // the ~1 Hz watch-poll cadence (handleWatchCommandPoll → sendServerEvent).
        // Cancelling + rescheduling on every call tore the work item down ~1 s
        // after it was armed, so it never survived the 3 s to fire — the WS stayed
        // dead (isConnected=false / bridge offline) while HTTP /watch kept flowing.
        // Guarding on a pending item lets the already-armed reconnect run instead
        // of being perpetually deferred. Hop to main so reconnectWorkItem is only
        // ever touched there (connect() runs on main too).
        DispatchQueue.main.async { [weak self] in
            guard let self, self.reconnectWorkItem == nil else { return }
            let item = DispatchWorkItem { [weak self] in
                self?.reconnectWorkItem = nil
                self?.connect()
            }
            self.reconnectWorkItem = item
            DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: item)
        }
    }

    private func startPollAgeTimer() {
        pollAgeTimer?.invalidate()
        pollAgeTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            let age = self.lastWatchPollAt.map { Int(Date().timeIntervalSince($0) * 1000) }
            let isFresh = age.map { $0 < Self.pollFreshMs } ?? false
            DispatchQueue.main.async {
                self.watchPollAgeMs = age
                self.watchPolling = isFresh
            }
        }
    }
}
