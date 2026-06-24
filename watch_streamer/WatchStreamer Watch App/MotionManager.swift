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
        static let commandPollInterval = 1.0
        static let commandPollWatchdog = 3.0
        static let spillDrainInterval = 3.0
        // Hard cap so an indefinitely-disconnected watch can't fill the disk and
        // trip the OS. At ~150 B/sample this is roughly hours of 50 Hz capture.
        static let spillMaxBytes = 25 * 1024 * 1024
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
    // Wenn gesetzt, kettet der Drain-Erfolgs-Handler sofort den nächsten Drain
    // an, statt auf den 3-s-Timer zu warten (Burst-Send via drain_spill).
    private var forceDraining = false
    // Read cursor into the spill file. During a drain run lines are consumed by
    // advancing this offset (O(1), no file rewrite); the already-sent prefix is
    // reclaimed in a single rewrite at the end of the run (compactSpill). At rest
    // the cursor is 0, so "byte 0 = oldest live line" holds for the launch counter
    // and discardForeignSpill. Was a full-file rewrite per line (O(n²) on a burst).
    private var spillReadOffset: UInt64 = 0
    private var pendingSpillAdvance: UInt64 = 0
    private static let spillReadChunk = 256 * 1024
    private lazy var spillFileURL: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("watch_spill.jsonl")
    }()

    // H4 — Motion-Callbacks laufen auf einer Background-Queue statt auf Main.
    // Der Callback macht nur: Sample bauen + unter stagingLock anhängen +
    // (coalesced) einen Main-Drain anstoßen. Die bestehende Pipeline (buffer,
    // flushBuffer, sendViaBridge, alle @Published) bleibt unangetastet auf
    // Main. Einzige neue cross-thread Fläche: stagedSamples + stagingLock.
    private let motionOpQueue: OperationQueue = {
        let q = OperationQueue()
        q.maxConcurrentOperationCount = 1
        q.qualityOfService = .userInitiated
        q.name = "com.watchstreamer.motion.intake"
        return q
    }()
    private let stagingLock = NSLock()
    private var stagedSamples: [[String: Any]] = []
    private var drainScheduled = false

    // Backing counters — updated per sample on main; published to SwiftUI at batch rate only.
    private var rawSampleCount = 0
    private var rawLastAccMag = 0.0
    private var rawLastGyroMag = 0.0

    // Why: the per-sample capture clock is the ML ground-truth axis. We anchor the
    // monotonic sensor clock (motion.timestamp, boot-relative — the true sampling
    // instant) to wall-clock once per run and derive every ts from it. Date() in the
    // background callback is non-monotonic (an NTP step shifts all labels) and stamps
    // callback-execution time, not the sampling instant. Guarded by stagingLock (same
    // cross-thread surface as stagedSamples); sentinel < 0 means "not yet anchored".
    private var anchorUptime: TimeInterval = -1
    private var anchorWallMs: Int64 = 0

    @Published private(set) var sampleCount = 0
    @Published private(set) var deliveredSampleCount = 0
    @Published private(set) var backgroundQueuedSampleCount = 0
    @Published private(set) var failedBatchCount = 0
    @Published private(set) var spilledSampleCount = 0
    @Published private(set) var spillDroppedSampleCount = 0
    // Recent |acc| magnitudes (batch rate, capped) for the on-watch sparkline.
    @Published private(set) var accMagHistory: [Double] = []
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
        // Why: strukturfix gegen das „nächster-Morgen"-Problem (S044): liegt
        // beim Start noch Spill einer FREMDEN (alten) Session auf der Disk,
        // gehört er nicht in die neue Session — verwerfen, bevor wir aufnehmen.
        // Spill der GLEICHEN Session (legit Mid-Session-Stau) bleibt erhalten.
        discardForeignSpill(newSessionId: serverSessionId)
        resetRunCounters()
        startWorkoutSessionIfNeeded()
        isRunning = true
        runStartedAt = Date()
        status = "Recording"
        uploadMode = isReachable ? "Bridge" : "Bridge (polling)"
        cm.deviceMotionUpdateInterval = 1.0 / effectiveHz
        // H4: Callbacks auf motionOpQueue (Background). Der Callback baut nur
        // den Sample und staged ihn — die Verarbeitung passiert in
        // drainStaging() auf Main.
        cm.startDeviceMotionUpdates(to: motionOpQueue) { [weak self] motion, _ in
            guard let self, let motion else { return }
            self.stagingLock.lock()
            // Why: anchor the monotonic sensor clock to wall-clock on the first
            // sample of the run; every ts derives from it, so a mid-session NTP
            // step or callback jitter can no longer move labels.
            if self.anchorUptime < 0 {
                self.anchorUptime = motion.timestamp
                self.anchorWallMs = Self.currentTimestampMillis()
            }
            let ts = self.anchorWallMs
                + Int64((motion.timestamp - self.anchorUptime) * 1000)
            let sample: [String: Any] = [
                "ts": ts,
                "ax": motion.userAcceleration.x,
                "ay": motion.userAcceleration.y,
                "az": motion.userAcceleration.z,
                "rx": motion.rotationRate.x,
                "ry": motion.rotationRate.y,
                "rz": motion.rotationRate.z,
                // Modern-Pool (ab 2026-05-26): gravity vector separat. Damit
                // ist (ax+gx, ay+gy, az+gz) = total acceleration ableitbar,
                // ohne ax/ay/az-Semantik (user-acc ohne g) zu ändern.
                "gx": motion.gravity.x,
                "gy": motion.gravity.y,
                "gz": motion.gravity.z,
                // Attitude-Quaternion (forward-only): hardware-fusionierte
                // Handgelenk-Orientierung aus derselben Sensor-Fusion. Reine
                // Metadaten fürs spätere 3D-Replay — ax/ay/az-Semantik und das
                // ML/Feature-Set bleiben unberührt; reist passiv durch die
                // bestehende Staging-/Drain-/Spill-Pipeline.
                "qx": motion.attitude.quaternion.x,
                "qy": motion.attitude.quaternion.y,
                "qz": motion.attitude.quaternion.z,
                "qw": motion.attitude.quaternion.w
            ]
            self.stagedSamples.append(sample)
            let needDrain = !self.drainScheduled
            if needDrain { self.drainScheduled = true }
            self.stagingLock.unlock()
            // Coalesced: nur ein Main-Hop, bis drainStaging das Flag löscht.
            if needDrain {
                DispatchQueue.main.async { self.drainStaging() }
            }
        }
    }

    /// Holt die im Background-Callback gestageten Rohsamples und speist sie
    /// in die bestehende Main-Pipeline. Coalesced — ein Drain verarbeitet
    /// alles, was seit dem letzten aufgelaufen ist. Läuft auf Main.
    private func drainStaging() {
        stagingLock.lock()
        let batch = stagedSamples
        stagedSamples.removeAll(keepingCapacity: true)
        drainScheduled = false
        stagingLock.unlock()
        guard !batch.isEmpty else { return }

        buffer.append(contentsOf: batch)
        rawSampleCount += batch.count
        if let last = batch.last {
            rawLastAccMag = Self.magnitude(last["ax"], last["ay"], last["az"])
            rawLastGyroMag = Self.magnitude(last["rx"], last["ry"], last["rz"])
        }
        trimBufferIfNeeded()
        flushBuffer(force: false)
    }

    private static func magnitude(_ x: Any?, _ y: Any?, _ z: Any?) -> Double {
        let dx = x as? Double ?? 0
        let dy = y as? Double ?? 0
        let dz = z as? Double ?? 0
        return sqrt(dx * dx + dy * dy + dz * dz)
    }

    func stop() {
        guard isRunning || workoutSession != nil else { return }
        cm.stopDeviceMotionUpdates()
        isRunning = false
        runStartedAt = nil
        drainStaging()          // H4: noch gestagete Samples übernehmen
        flushBuffer(force: true)
        if buffer.isEmpty {
            status = "Stopped"
        }
        endWorkoutSessionIfNeeded()
    }

    private func resetRunCounters() {
        buffer.removeAll()
        stagingLock.lock()
        stagedSamples.removeAll()
        drainScheduled = false
        anchorUptime = -1   // re-anchor the capture clock on the next sample
        stagingLock.unlock()
        nextSequence = 0
        inFlightSequences.removeAll()
        rawSampleCount = 0
        rawLastAccMag = 0
        rawLastGyroMag = 0
        sampleCount = 0
        deliveredSampleCount = 0
        backgroundQueuedSampleCount = 0
        failedBatchCount = 0
        queuedSampleCount = 0
        actualSampleRateHz = 0
        lastAccelerationMagnitude = 0
        lastGyroscopeMagnitude = 0
        accMagHistory = []
        runStartedAt = nil
    }

    private func flushBuffer(force: Bool) {
        guard buffer.count >= effectiveBatchSize || (force && !buffer.isEmpty) else { return }

        // Publish UI counters at batch rate (~5 Hz) instead of per-sample.
        sampleCount = rawSampleCount
        lastAccelerationMagnitude = rawLastAccMag
        lastGyroscopeMagnitude = rawLastGyroMag
        // Real |acc| trail for the on-watch sparkline (published at batch rate).
        accMagHistory.append(rawLastAccMag)
        if accMagHistory.count > 40 { accMagHistory.removeFirst(accMagHistory.count - 40) }
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
        let timer = Timer(timeInterval: Config.commandPollInterval, repeats: true) { [weak self] _ in
            self?.pollPhoneForCommand()
        }
        commandPollTimer = timer
        RunLoop.main.add(timer, forMode: .common)
        pollPhoneForCommand()
    }

    private func pollPhoneForCommand() {
        // Watchdog: if a poll has been in-flight for >3 s without a reply, force-clear the flag.
        if commandPollInFlight, let sentAt = commandPollSentAt,
           Date().timeIntervalSince(sentAt) > Config.commandPollWatchdog {
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
        spillQueue.async { [weak self] in
            // Fix 4: hard size cap. Past it, drop the newest envelope to protect the
            // device disk (the existing backlog stays intact) and undo the optimistic
            // counter. When unreachable — the only time the cap bites — the read
            // cursor is 0, so file size ≈ live bytes and the cap is accurate.
            let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int) ?? 0
            if size >= Config.spillMaxBytes {
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.spilledSampleCount = max(0, self.spilledSampleCount - n)
                    self.spillDroppedSampleCount += n
                }
                return
            }
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
        let timer = Timer(timeInterval: Config.spillDrainInterval, repeats: true) { [weak self] _ in
            self?.autoDrainSpillIfBacklog()
        }
        spillTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    /// Why: one spilled line per 3 s tick cannot keep up with 50–100 Hz capture —
    /// after a stall the real tail samples would arrive minutes late, past the end
    /// of the session (→ server-side unsessioned quarantine). When the phone is
    /// reachable and a backlog exists, burst-drain it (sendSpilled's success handler
    /// chains the next line) so it converges within the session instead of trickling.
    private func autoDrainSpillIfBacklog() {
        guard spilledSampleCount > 0,
              WCSession.default.activationState == .activated,
              WCSession.default.isReachable else { return }
        forceDrainSpill()
    }

    /// Liest die älteste Spill-Zeile und schickt sie über den Live-Pfad neu.
    /// Seriell (`spillDrainInFlight`) — Spill passiert nur bei Stau, danach
    /// reicht eine Zeile pro 3-s-Tick.
    private func drainSpill() {
        guard !spillDrainInFlight else { return }
        guard WCSession.default.activationState == .activated,
              WCSession.default.isReachable else {
            // Can't drain now (unreachable). Clear the burst latch so the next
            // reachable tick re-arms it; the in-memory cursor resumes where it was.
            forceDraining = false
            return
        }
        spillDrainInFlight = true
        let url = spillFileURL
        let offset = spillReadOffset
        spillQueue.async { [weak self] in
            guard let self else { return }
            // Read just the next line at the cursor — one bounded chunk, not the
            // whole file. Appends only touch the file end, so the bytes at `offset`
            // are stable while we read them.
            let next: (env: [String: Any]?, advance: UInt64)? = {
                guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
                defer { try? handle.close() }
                try? handle.seek(toOffset: offset)
                guard let chunk = try? handle.read(upToCount: Self.spillReadChunk),
                      !chunk.isEmpty,
                      let nl = chunk.firstIndex(of: 0x0A) else { return nil }
                let lineLen = chunk.distance(from: chunk.startIndex, to: nl)
                let lineData = Data(chunk.prefix(lineLen))
                let env = (try? JSONSerialization.jsonObject(with: lineData)) as? [String: Any]
                return (env: env, advance: UInt64(lineLen) + 1)
            }()
            DispatchQueue.main.async {
                guard let next else {
                    // Cursor at/after EOF (or unreadable tail) → backlog drained.
                    self.compactSpill()
                    return
                }
                self.pendingSpillAdvance = next.advance
                if let env = next.env {
                    self.sendSpilled(env)
                } else {
                    // Corrupt line: skip it (advance the cursor) and continue.
                    self.spillReadOffset += next.advance
                    self.pendingSpillAdvance = 0
                    self.spillDrainInFlight = false
                    if self.forceDraining { self.drainSpill() }
                }
            }
        }
    }

    /// Sendet ein gespilltes Envelope via sendMessage. Erfolg → Cursor über die
    /// Zeile vorrücken (kein Rewrite). Fehler → Cursor bleibt, nächster Tick retryt.
    private func sendSpilled(_ envelope: [String: Any]) {
        guard WCSession.default.activationState == .activated,
              let payloadData = try? JSONSerialization.data(withJSONObject: envelope) else {
            pendingSpillAdvance = 0
            spillDrainInFlight = false
            return
        }
        let n = (envelope["samples"] as? [[String: Any]])?.count ?? 0
        WCSession.default.sendMessage(["payload": payloadData], replyHandler: { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.deliveredSampleCount += n
                self.spilledSampleCount = max(0, self.spilledSampleCount - n)
                // Consume the line by advancing the cursor — no file rewrite here.
                self.spillReadOffset += self.pendingSpillAdvance
                self.pendingSpillAdvance = 0
                if self.forceDraining {
                    // Burst: continue immediately from the new cursor, no rewrite.
                    self.spillDrainInFlight = false
                    self.drainSpill()
                } else {
                    // Single drain done → reclaim the consumed prefix in one rewrite.
                    self.compactSpill()
                }
            }
        }, errorHandler: { [weak self] _ in
            // Error → pause the burst and reclaim what was sent so far; the next
            // timer tick retries the remainder from a clean byte-0 cursor.
            DispatchQueue.main.async {
                guard let self else { return }
                self.pendingSpillAdvance = 0
                self.compactSpill()
            }
        })
    }

    /// Reclaims the already-sent prefix in a single rewrite (or deletes the file
    /// when fully drained) and resets the cursor. Called only at the END of a drain
    /// run — never per line — so a burst costs one rewrite instead of one per sample
    /// (the old per-line full rewrite was O(n²) on a large post-stall spill). Holds
    /// spillDrainInFlight across the rewrite so no drain reads a stale cursor; the
    /// "byte 0 = oldest live line" rest invariant is restored on completion.
    private func compactSpill() {
        let url = spillFileURL
        let consumed = spillReadOffset
        spillReadOffset = 0
        guard consumed > 0 else {
            forceDraining = false
            spillDrainInFlight = false
            return
        }
        spillQueue.async { [weak self] in
            var deletedEmpty = false
            if let data = try? Data(contentsOf: url), !data.isEmpty,
               consumed < UInt64(data.count) {
                let remainder = data.subdata(in: Int(consumed)..<data.count)
                try? remainder.write(to: url, options: [.atomic])
            } else {
                try? FileManager.default.removeItem(at: url)
                deletedEmpty = true
            }
            DispatchQueue.main.async {
                guard let self else { return }
                self.forceDraining = false
                self.spillDrainInFlight = false
                if deletedEmpty { self.spilledSampleCount = 0 }
            }
        }
    }

    // MARK: - Spill-Flush (manuell + auto)

    /// Rohes Löschen der Spill-Datei + Counter-Reset. Kein Guard — interner
    /// Baustein für clearSpill() (manuell, mit Guard) und discardForeignSpill()
    /// (Auto bei Session-Start).
    private func purgeSpillFile() {
        let url = spillFileURL
        spillQueue.async { try? FileManager.default.removeItem(at: url) }
        spilledSampleCount = 0
        spillReadOffset = 0
        forceDraining = false
    }

    /// Manueller „Spill verwerfen"-Befehl. Verweigert während einer laufenden
    /// Aufnahme — der Live-Stau ist echte Daten, die ein (evtl. stale
    /// zugestellter) Lösch-Befehl nie wegwerfen darf. Gibt zurück, ob gelöscht.
    @discardableResult
    func clearSpill() -> Bool {
        guard !isRunning else { return false }
        purgeSpillFile()
        return true
    }

    /// Manueller „Spill jetzt senden"-Befehl: Burst statt 1 Zeile/3 s. Setzt
    /// nur das Flag + kickt einen Drain an — der Erfolgs-Handler kettet den
    /// Rest, die Leer-Datei-Erkennung in drainSpill() beendet den Burst.
    func forceDrainSpill() {
        guard !forceDraining else { return }
        forceDraining = true
        drainSpill()
    }

    /// Auto-Discard bei Session-Start: liegt Spill einer FREMDEN Session auf
    /// der Disk, gehört er nicht in die neue Session → verwerfen. Vergleicht
    /// die `sessionId` der ältesten Spill-Zeile mit der neuen Session.
    private func discardForeignSpill(newSessionId: String?) {
        guard let newSessionId, !newSessionId.isEmpty else { return }
        let url = spillFileURL
        let firstSid: String? = spillQueue.sync {
            guard let data = try? Data(contentsOf: url), !data.isEmpty,
                  let first = data.split(separator: 0x0A,
                                         omittingEmptySubsequences: true).first,
                  let env = try? JSONSerialization.jsonObject(with: Data(first))
                            as? [String: Any]
            else { return nil }
            return env["sessionId"] as? String
        }
        if let firstSid, firstSid != newSessionId {
            purgeSpillFile()
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

        // Why: command_poll-Antworten tragen source == "iphone_command_poll".
        // Das iPhone baut sie off-main aus einem evtl. veralteten
        // currentSessionId — unter 100-Hz-Last weicht das sekundenlang von der
        // Realität ab. Eine laufende Aufnahme darf NIE auf eine Poll-Antwort
        // hin gestoppt + neugestartet werden (das war der „startet sich von
        // selbst neu"-Bug); nur ein expliziter Push (sendMessage /
        // applicationContext) darf die Session einer laufenden Aufnahme
        // wechseln. Ein Poll darf weiterhin eine *gestoppte* Watch starten
        // (Recovery, falls ein Push verloren ging) und jederzeit stoppen.
        let fromPoll = (message["source"] as? String) == "iphone_command_poll"

        switch command {
        case "start":
            if isRunning, let sid, !sid.isEmpty, sid != serverSessionId, !fromPoll {
                stop()
            }
            if !isRunning {
                start(sessionId: sid)
            } else if let sid, !sid.isEmpty, !fromPoll {
                serverSessionId = sid
            }
        case "stop":
            // Why: gepushte Commands können via transferUserInfo-Queue Minuten
            // alt sein (S044, 2026-06-12: stale stop+start → Workout-Restart →
            // WC-Jam → ~3 min Datenverlust). Ein Push-Stop darf eine laufende
            // Aufnahme nur beenden, wenn er deren session_id trägt. Der
            // Poll-Pfad (synchrone Reply, kann nicht stale sein) bleibt der
            // Recovery-Weg und darf weiterhin jederzeit stoppen.
            if isRunning, !fromPoll, sid != serverSessionId {
                return [
                    "ok": false,
                    "command": command,
                    "command_id": commandId ?? "",
                    "stale": true,
                    "isRunning": isRunning,
                    "session_id": serverSessionId ?? "",
                    "error": "stale stop ignored (session mismatch)"
                ]
            }
            stop()
            serverSessionId = nil
        case "drain_spill":
            // Nicht-destruktiv: gesamten Spill jetzt im Burst senden.
            forceDrainSpill()
            return [
                "ok": true,
                "command": command,
                "command_id": commandId ?? "",
                "isRunning": isRunning,
                "spilled_samples": spilledSampleCount,
            ]
        case "clear_spill":
            // Destruktiv: Spill verwerfen. clearSpill() weigert sich, wenn
            // gerade aufgenommen wird — schützt Live-Puffer gegen einen evtl.
            // stale (verspätet) zugestellten Lösch-Befehl.
            let cleared = clearSpill()
            return [
                "ok": cleared,
                "command": command,
                "command_id": commandId ?? "",
                "cleared": cleared,
                "isRunning": isRunning,
                "spilled_samples": spilledSampleCount,
                "error": cleared ? "" : "clear_spill ignored while recording",
            ]
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
