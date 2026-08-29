import Combine
import Foundation
import WatchConnectivity
#if canImport(UIKit)
import UIKit
#endif

/// Single source of truth for the default server address. The address is
/// user-overridable via UserDefaults("serverIP"); this is the fallback when none
/// is set. Was duplicated as a bare "192.168.178.147" literal across PhoneBridge
/// and ServerCommandListener.
enum ServerConfig {
    /// Why: a release build must not silently target the development LAN. Debug
    /// keeps the convenience default; release starts unconfigured so the UI can
    /// say "no server configured" instead of probing a developer machine.
    #if DEBUG
    static let defaultIP = "192.168.178.147"
    #else
    static let defaultIP = ""
    #endif

    /// The address as configured, or the build's default when unset.
    static var configuredIP: String {
        UserDefaults.standard.string(forKey: CaptureSettings.serverIPKey) ?? defaultIP
    }

    /// Every endpoint derived from one parse. Nil when no usable address is set.
    static var endpoint: ServerEndpoint.Resolved? {
        ServerEndpoint.resolve(configuredIP)
    }

    /// Shared secret attached to server requests when the operator has set one.
    static var token: String? {
        let t = UserDefaults.standard.string(forKey: CaptureSettings.serverTokenKey) ?? ""
        return t.isEmpty ? nil : t
    }
}

class PhoneBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneBridge()

    // MARK: – Tuning constants

    /// Hard limit für die Upload-Queue (drop-oldest). Bei 50 Hz / Batch 10
    /// = 5000 batches × 10 = 50 000 samples ≈ 16 min Backlog. Die Watch puffert
    /// einen Ausfall stundenlang auf Disk; das iPhone hat reichlich RAM, daher
    /// ein großzügiges Limit, damit ein mehrminütiger Server-Ausfall keine Daten
    /// verwirft. Die Queue wird debounced als Snapshot persistiert — ein höheres
    /// Limit verteuert nur diesen (Hintergrund-)Write, kein Live-Pfad-Kosten.
    private static let maxQueueSize = 5000

    /// Disk-Persistierung — überlebt App-Crash / Force-Quit.
    ///
    /// Why Application Support and not Documents: the queue holds raw wrist
    /// motion for an identified person. In Documents it was backup-eligible,
    /// so a phone backup carried the proband's motion data off the device.
    /// Application Support survives app updates the same way, is excluded from
    /// backup here, and is file-protected until first unlock.
    private static let queueFileName = "upload_queue.json"

    /// Coalesce-Delay für Disk-Writes. 500 ms Debounce → wir schreiben nicht
    /// nach jedem einzelnen Batch (50 Hz wäre Overkill), aber bei Crash gehen
    /// max ~25 Samples verloren.
    private static let persistDebounce: TimeInterval = 0.5

    // MARK: – Server URL helpers

    static var serverBaseURL: String {
        ServerConfig.endpoint?.httpBase.absoluteString ?? ""
    }

    static var serverAddress: String {
        ServerConfig.endpoint?.watchUpload.absoluteString ?? ""
    }

    // MARK: – Published state

    @Published var isConnected = false
    @Published var isBridgeCapable = false
    @Published var receivedSampleCount = 0
    @Published var uploadedSampleCount = 0
    @Published var queuedBatchCount = 0
    @Published var failedUploadCount = 0
    /// Anzahl Batches, die wegen Queue-Cap gedroppt wurden. Bei >0 fehlen
    /// uns Daten — wichtig für die Quality-Beurteilung serverseitig.
    @Published var droppedBatchCount = 0
    @Published var lastError = ""

    // MARK: – Private state

    private var uploadQueue: [[String: Any]] = []
    private var isUploading = false
    private var disconnectDebounce: DispatchWorkItem?

    // Why: capped exponential backoff for upload retries — a fixed 2 s cadence
    // hammers the radio during a longer server outage. Reset to base on the
    // next successful upload (see dispatchUpload).
    private static let uploadRetryBaseDelay: TimeInterval = 2.0
    private static let uploadRetryMaxDelay: TimeInterval = 30.0
    private var uploadRetryDelay: TimeInterval = 2.0

    // Why: WatchConnectivity liefert denselben Batch manchmal zweimal aus
    // (replyHandler-Timeout → Watch queued fallback via transferUserInfo,
    // obwohl iPhone die Live-Message schon hatte). Dedup-Key = sessionId+seq.
    // Bounded LRU verhindert unbegrenztes Wachstum bei langen Sessions.
    private var seenBatchKeys: Set<String> = []
    private var seenBatchOrder: [String] = []
    // Why: a stuck transferUserInfo queue can deliver minutes-old batches; the
    // dedup memory must outlast that delay. 10 000 keys ≈ 16 min @ 50 Hz/Batch 10
    // (short strings, negligible RAM) so a very late re-delivery is still caught.
    private static let seenBatchCapacity = 10000

    /// Background queue für JSON-Encoding und Magnituden-Berechnung. UserInitiated
    /// QoS, weil's am Live-Datenpfad hängt — aber wir wollen den Main-Thread
    /// für UI freihalten.
    private let workQueue = DispatchQueue(label: "com.watchstreamer.bridge.work",
                                          qos: .userInitiated)

    /// Serial queue für Disk-IO. Verhindert, dass mehrere Schreibvorgänge
    /// gleichzeitig die Datei zerschießen.
    private let persistQueue = DispatchQueue(label: "com.watchstreamer.bridge.persist",
                                             qos: .utility)

    /// Debounce-Token für Queue-Persistierung. Wird vor dem nächsten Schreiben
    /// gecancelt → coalescing.
    private var persistTask: DispatchWorkItem?

    /// Watch acknowledgements waiting for the write that makes their batch
    /// durable. Main-thread only.
    private var pendingDurabilityAcks: [(Bool) -> Void] = []

    private lazy var queueFileURL: URL = {
        let fm = FileManager.default
        let support = (try? fm.url(for: .applicationSupportDirectory,
                                   in: .userDomainMask,
                                   appropriateFor: nil, create: true))
            ?? fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? fm.createDirectory(at: support, withIntermediateDirectories: true)
        let url = support.appendingPathComponent(Self.queueFileName)
        Self.migrateLegacyQueue(to: url)
        Self.protect(url)
        return url
    }()

    /// Moves a queue left in Documents by an older build, then removes the
    /// original — otherwise the backup-eligible copy would linger untouched.
    private static func migrateLegacyQueue(to destination: URL) {
        let fm = FileManager.default
        let legacy = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(queueFileName)
        guard fm.fileExists(atPath: legacy.path) else { return }
        if !fm.fileExists(atPath: destination.path) {
            try? fm.moveItem(at: legacy, to: destination)
        } else {
            try? fm.removeItem(at: legacy)
        }
    }

    /// Excludes the queue from backups and requires a first unlock to read it.
    private static func protect(_ url: URL) {
        var target = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? target.setResourceValues(values)
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path)
    }

    /// Removes every piece of locally held recording data.
    ///
    /// Distinct from resetting preferences: this is what "delete my data"
    /// has to mean if the Profile screen offers it. Server-side data is
    /// untouched and the UI says so.
    func deleteAllLocalData() {
        persistTask?.cancel()
        uploadQueue.removeAll()
        queuedBatchCount = 0
        receivedSampleCount = 0
        uploadedSampleCount = 0
        failedUploadCount = 0
        droppedBatchCount = 0
        seenBatchKeys.removeAll()
        seenBatchOrder.removeAll()
        lastError = ""
        let url = queueFileURL
        persistQueue.async { try? FileManager.default.removeItem(at: url) }
    }

    // MARK: – Lifecycle

    private override init() {
        super.init()
        WCSession.default.delegate = self
        WCSession.default.activate()

        // Persistierte Queue von Disk laden (z.B. nach App-Crash).
        loadPersistedQueue()

        // App-Backgrounding → sofort persistieren, damit nichts verloren geht
        // wenn iOS uns suspended.
        #if canImport(UIKit)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(persistImmediately),
            name: UIApplication.didEnterBackgroundNotification,
            object: nil)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(persistImmediately),
            name: UIApplication.willTerminateNotification,
            object: nil)
        #endif
    }

    // MARK: – Connectivity helpers (must be called on main thread)

    private func applyReachability(_ session: WCSession) {
        isBridgeCapable = session.activationState == .activated
            && session.isPaired
            && session.isWatchAppInstalled

        if session.isReachable {
            disconnectDebounce?.cancel()
            disconnectDebounce = nil
            isConnected = true
        } else {
            guard isConnected, disconnectDebounce == nil else { return }
            let item = DispatchWorkItem { [weak self] in
                self?.isConnected = false
                self?.disconnectDebounce = nil
            }
            disconnectDebounce = item
            DispatchQueue.main.asyncAfter(deadline: .now() + 4.0, execute: item)
        }
    }

    private func forceDisconnect() {
        disconnectDebounce?.cancel()
        disconnectDebounce = nil
        isConnected = false
        isBridgeCapable = false
    }

    func session(_ session: WCSession,
                 activationDidCompleteWith state: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async {
            self.applyReachability(session)
            if let error {
                self.lastError = error.localizedDescription
            }
            self.syncServerIP(ServerConfig.configuredIP)
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }
    func sessionDidBecomeInactive(_ session: WCSession) {
        DispatchQueue.main.async { self.forceDisconnect() }
    }
    func sessionDidDeactivate(_ session: WCSession) {
        DispatchQueue.main.async { self.forceDisconnect() }
        session.activate()
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard message["type"] as? String != "command_poll" else { return }
        receivePayload(message, source: "message")
    }

    func session(_ session: WCSession,
                 didReceiveMessage message: [String: Any],
                 replyHandler: @escaping ([String: Any]) -> Void) {
        if message["type"] as? String == "command_poll" {
            let reply = ServerCommandListener.shared.handleWatchCommandPoll(message)
            replyHandler(reply)
            return
        }
        // Why: the reply is the Watch's permission to release its copy of this
        // batch, so it must not be sent until the batch is durable here. A
        // malformed payload still answers immediately with ok=false via the
        // same callback.
        var replied = false
        receivePayload(message, source: "message") { durable in
            guard !replied else { return }
            replied = true
            replyHandler([WatchPayloadKey.ok: durable])
        }
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        if userInfo[WatchPayloadKey.type] as? String == "command_poll" {
            _ = ServerCommandListener.shared.handleWatchCommandPoll(userInfo)
            return
        }
        if userInfo[WatchPayloadKey.type] as? String == WatchPayloadKey.passiveDecisionsType {
            receivePassiveDecisions(userInfo)
            return
        }
        receivePayload(userInfo, source: "background")
    }

    /// Forwards a batch of passive writing decisions to the server.
    ///
    /// Idempotent by construction: each decision carries its own `startMs`, so
    /// a re-delivered batch is recognised server-side rather than counted
    /// twice. Kept off the raw-IMU upload queue — these are small, derived and
    /// independently retryable, and mixing them into the sample backlog would
    /// let an IMU stall block them.
    private func receivePassiveDecisions(_ userInfo: [String: Any]) {
        guard let data = userInfo[WatchPayloadKey.decisions] as? Data,
              let decisions = try? JSONDecoder().decode([PassiveDecision].self, from: data),
              !decisions.isEmpty else {
            DispatchQueue.main.async { self.lastError = "Invalid passive decisions payload" }
            return
        }
        guard let url = ServerConfig.endpoint?.httpBase
            .appendingPathComponent("passive/decisions") else { return }

        var body: [String: Any] = ["decisions": decisions.map {
            ["start_ms": $0.startMs, "end_ms": $0.endMs,
             "logit": $0.logit, "writing": $0.writing,
             "credit_seconds": $0.creditSeconds]
        }]
        body["source"] = "watch_passive"
        guard let payload = try? JSONSerialization.data(withJSONObject: body) else { return }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = ServerConfig.token {
            req.setValue(token, forHTTPHeaderField: "X-Scrybe-Token")
        }
        req.httpBody = payload
        req.timeoutInterval = 12
        URLSession.shared.dataTask(with: req) { [weak self] _, response, error in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard error != nil || !(200..<300).contains(code) else { return }
            DispatchQueue.main.async {
                self?.lastError = "Passive sync failed: "
                    + (error?.localizedDescription ?? "HTTP \(code)")
            }
        }.resume()
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            self.applyReachability(session)
            self.syncServerIP(ServerConfig.configuredIP)
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }

    func syncServerIP(_ ip: String) {
        let trimmed = ip.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        UserDefaults.standard.set(trimmed, forKey: CaptureSettings.serverIPKey)
        guard WCSession.default.activationState == .activated else { return }
        do {
            var context = ServerCommandListener.shared.currentWatchCommandPayload()
            context["server_ip"] = trimmed
            try WCSession.default.updateApplicationContext(context)
        } catch {
            lastError = "Could not sync server IP: \(error.localizedDescription)"
        }
    }

    func reactivateSession() {
        WCSession.default.delegate = self
        WCSession.default.activate()
        applyReachability(WCSession.default)
        syncServerIP(ServerConfig.configuredIP)
        ServerCommandListener.shared.sendPhoneStatus()
    }

    func resyncWatchContext() {
        syncServerIP(ServerConfig.configuredIP)
        ServerCommandListener.shared.refreshWatchContext()
    }

    func retryUploadQueue() {
        guard !uploadQueue.isEmpty else {
            lastError = ""
            queuedBatchCount = 0
            return
        }
        lastError = ""
        uploadNextIfNeeded()
    }

    func clearDiagnostics() {
        lastError = ""
        failedUploadCount = 0
        droppedBatchCount = 0
        seenBatchKeys.removeAll(keepingCapacity: true)
        seenBatchOrder.removeAll(keepingCapacity: true)
    }

    // MARK: – Receive (off-main heavy work)

    /// Ingests one batch. `onDurable`, when given, fires exactly once with
    /// whether the batch is safely owned by the persisted upload queue.
    ///
    /// Why the callback: the Watch treats a successful reply as permission to
    /// release its own copy of the batch. Replying at validation time — before
    /// the batch reached the queue, let alone disk — meant a suspension or
    /// crash in that window lost data the Watch had already let go.
    @discardableResult
    private func receivePayload(_ payload: [String: Any],
                                source: String,
                                onDurable: ((Bool) -> Void)? = nil) -> Bool {
        // Why: validate synchronously so the WatchConnectivity replyHandler can
        // honestly report whether the batch was accepted — a malformed payload
        // must not be acked as ok=true. normalizePayload is pure (no shared
        // state), so running it on the delegate thread is safe; the heavy
        // magnitude precompute + enqueue still hop off-main below.
        guard let normalized = normalizePayload(payload, source: source),
              let samples = normalized["samples"] as? [[String: Any]] else {
            DispatchQueue.main.async { self.lastError = "Invalid watch payload" }
            onDurable?(false)
            return false
        }

        workQueue.async { [weak self] in
            guard let self else { onDurable?(false); return }

            // Magnituden für Live-Chart vorberechnen — vermeidet O(N) Arbeit
            // auf dem Main-Thread bei jedem Batch.
            let accValues  = samples.map { s -> Double in
                let ax = s["ax"] as? Double ?? 0
                let ay = s["ay"] as? Double ?? 0
                let az = s["az"] as? Double ?? 0
                return (ax*ax + ay*ay + az*az).squareRoot()
            }
            let gyroValues = samples.map { s -> Double in
                let rx = s["rx"] as? Double ?? 0
                let ry = s["ry"] as? Double ?? 0
                let rz = s["rz"] as? Double ?? 0
                return (rx*rx + ry*ry + rz*rz).squareRoot()
            }

            DispatchQueue.main.async {
                // Dedup: WatchConnectivity kann denselben Batch via Live+Fallback
                // doppelt liefern. Wir gaten alles (receivedSampleCount, Queue,
                // Chart) hinter dem (sessionId, Capture-ts)-Check.
                if self.isDuplicateBatch(normalized) {
                    // Why: a duplicate is already durable from the delivery
                    // that won, so acking true is truthful and lets the Watch
                    // release its copy rather than retrying forever.
                    onDurable?(true)
                    return
                }

                self.receivedSampleCount += samples.count

                // Queue-Cap mit drop-oldest.
                if self.uploadQueue.count >= Self.maxQueueSize {
                    let dropCount = self.uploadQueue.count - Self.maxQueueSize + 1
                    self.uploadQueue.removeFirst(dropCount)
                    self.droppedBatchCount += dropCount
                }
                self.uploadQueue.append(normalized)
                self.queuedBatchCount = self.uploadQueue.count
                self.lastError = ""

                IMUDataStore.shared.pushBatch(accValues: accValues, gyroValues: gyroValues)

                // Why: the ack rides on the next successful snapshot write, so
                // it reports durability rather than intent. Batches arriving
                // inside one debounce window share that write, so the disk cost
                // is unchanged from before.
                self.schedulePersist(ack: onDurable)
                self.uploadNextIfNeeded()
            }
        }
        return true
    }

    /// Returns true if this batch has already been processed.
    ///
    /// Keyed on (sessionId, first-sample capture ts) rather than
    /// (sessionId, sequence). The watch-side sequence counter is run-scoped and
    /// resets to 0 on every start(); a single server session can span multiple
    /// runs (reconnect or app relaunch), so sequence numbers get reused within
    /// the same session. A sequence-based key would collide on that reuse and
    /// drop legitimate post-reset batches. The first sample's capture ts is
    /// monotonic across resets and identical on a genuine re-delivery, so it
    /// deduplicates true duplicates without colliding on reused numbers.
    /// Idempotent in the false branch — only inserts when unseen.
    /// Must be called on main.
    private func isDuplicateBatch(_ normalized: [String: Any]) -> Bool {
        let sessionId = (normalized["sessionId"] as? String) ?? "_"

        let identity: String
        if let samples = normalized["samples"] as? [[String: Any]],
           let firstTs = WatchPayloadValue.int64(samples.first?["ts"]) {
            identity = "ts\(firstTs)"
        } else if let seq = WatchPayloadValue.int64(normalized["sequence"]) {
            // Fallback auf die Sequenznummer, falls ein Batch keine Capture-Zeit
            // trägt. Ohne beides ist kein Dedup möglich → durchlassen (lieber
            // über- als unter-zählen).
            identity = "seq\(seq)"
        } else {
            return false
        }

        let key = "\(sessionId)#\(identity)"
        if seenBatchKeys.contains(key) {
            return true
        }
        seenBatchKeys.insert(key)
        seenBatchOrder.append(key)
        if seenBatchOrder.count > Self.seenBatchCapacity {
            let drop = seenBatchOrder.removeFirst()
            seenBatchKeys.remove(drop)
        }
        return false
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
        normalized["source"] = decodedPayload["source"] as? String ?? source
        normalized["transport"] = decodedPayload["transport"] as? String ?? "watchconnectivity"
        normalized["phoneReceivedAt"] = Self.currentTimestampMillis()
        normalized["samples"] = samples
        return normalized
    }

    // MARK: – Upload (off-main JSON encoding)

    private func uploadNextIfNeeded() {
        guard !isUploading, let payload = uploadQueue.first else { return }
        guard let url = ServerConfig.endpoint?.watchUpload else {
            lastError = ServerConfig.configuredIP.isEmpty
                ? "No server configured"
                : "Invalid server address"
            return
        }

        isUploading = true

        // JSON-Encoding off-main — bei großen Backlogs sonst spürbarer Hitch.
        workQueue.async { [weak self] in
            guard let self else { return }

            let bodyResult: Result<Data, Error>
            do {
                let body = try JSONSerialization.data(withJSONObject: payload)
                bodyResult = .success(body)
            } catch {
                bodyResult = .failure(error)
            }

            DispatchQueue.main.async {
                switch bodyResult {
                case .failure(let error):
                    self.failedUploadCount += 1
                    self.lastError = "Encode failed: \(error.localizedDescription)"
                    if !self.uploadQueue.isEmpty { self.uploadQueue.removeFirst() }
                    self.queuedBatchCount = self.uploadQueue.count
                    self.isUploading = false
                    self.schedulePersist()
                    self.uploadNextIfNeeded()

                case .success(let body):
                    self.dispatchUpload(url: url, body: body, payload: payload)
                }
            }
        }
    }

    /// Muss auf main aufgerufen werden. Setzt URLSessionDataTask ab und
    /// verarbeitet das Ergebnis auf main.
    private func dispatchUpload(url: URL, body: Data, payload: [String: Any]) {
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Why: the research server does not yet require the token, so an absent
        // one must not block a recording. It is attached whenever configured so
        // the server can start enforcing it without a client change.
        if let token = ServerConfig.token {
            req.setValue(token, forHTTPHeaderField: "X-Scrybe-Token")
        }
        req.httpBody = body
        // Why: cap the per-request wait so a hung POST on flaky WLAN can't pin
        // isUploading (and stall the whole queue) for the 60 s URLSession default.
        req.timeoutInterval = 12

        URLSession.shared.dataTask(with: req) { [weak self] _, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
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
                if !self.uploadQueue.isEmpty { self.uploadQueue.removeFirst() }
                self.queuedBatchCount = self.uploadQueue.count
                self.lastError = ""
                self.uploadRetryDelay = Self.uploadRetryBaseDelay
                self.schedulePersist()
                self.uploadNextIfNeeded()
            }
        }.resume()
    }

    private func scheduleRetry() {
        queuedBatchCount = uploadQueue.count
        let delay = uploadRetryDelay
        uploadRetryDelay = min(uploadRetryDelay * 2, Self.uploadRetryMaxDelay)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.uploadNextIfNeeded()
        }
    }

    private static func currentTimestampMillis() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }

    // MARK: – Disk persistence (debounced)

    /// Auf main thread aufrufen — pausiert vorhandenen pending write und
    /// schedult einen neuen mit `persistDebounce` Verzögerung. Mehrere Aufrufe
    /// in kurzer Folge → nur ein Write am Ende.
    private func schedulePersist(ack: ((Bool) -> Void)? = nil) {
        // Why: an ack waits for the write that includes its batch. Cancelling
        // the previous work item never strands one — the queue only grows, so
        // the next write covers every batch the cancelled one would have.
        if let ack { pendingDurabilityAcks.append(ack) }
        persistTask?.cancel()
        let snapshot = uploadQueue
        let work = DispatchWorkItem { [weak self] in
            let ok = self?.writeQueueToDisk(snapshot) ?? false
            DispatchQueue.main.async { self?.flushDurabilityAcks(ok) }
        }
        persistTask = work
        persistQueue.asyncAfter(deadline: .now() + Self.persistDebounce, execute: work)
    }

    /// Sofort persistieren — bei Backgrounding / Termination, kein Debounce.
    @objc private func persistImmediately() {
        persistTask?.cancel()
        let snapshot = uploadQueue
        persistQueue.async { [weak self] in
            let ok = self?.writeQueueToDisk(snapshot) ?? false
            DispatchQueue.main.async { self?.flushDurabilityAcks(ok) }
        }
    }

    /// Main-thread only. Fires and clears every ack waiting on a write.
    private func flushDurabilityAcks(_ ok: Bool) {
        guard !pendingDurabilityAcks.isEmpty else { return }
        let acks = pendingDurabilityAcks
        pendingDurabilityAcks.removeAll(keepingCapacity: true)
        for ack in acks { ack(ok) }
    }

    /// Schreibt die Queue als JSON-Array. Atomic write → entweder vollständig
    /// alt oder vollständig neu, nie korrupt. Returns whether the snapshot is
    /// now durable, which is what the Watch's acknowledgement rides on.
    @discardableResult
    private func writeQueueToDisk(_ snapshot: [[String: Any]]) -> Bool {
        let url = queueFileURL
        do {
            if snapshot.isEmpty {
                // Datei löschen statt leeres Array schreiben — spart Cycles
                // beim nächsten Launch (kein Decode).
                try? FileManager.default.removeItem(at: url)
                return true
            }
            let data = try JSONSerialization.data(withJSONObject: snapshot,
                                                  options: [.fragmentsAllowed])
            try data.write(to: url, options: [.atomic])
            // Why: an atomic write replaces the file, so the backup-exclusion
            // and protection attributes have to be re-applied to the new inode.
            Self.protect(url)
            return true
        } catch {
            // Persistenz-Fehler sollen den Datenfluss nicht stören. Wir loggen
            // sie nur, blockieren aber nicht den Upload.
            DispatchQueue.main.async {
                self.lastError = "Persist failed: \(error.localizedDescription)"
            }
            return false
        }
    }

    /// Im init() aufgerufen. Synchron — Datei ist klein (max ~50 KB) und wir
    /// brauchen die Queue, bevor irgendwer pushBatch() aufrufen kann.
    private func loadPersistedQueue() {
        let url = queueFileURL
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        do {
            let data = try Data(contentsOf: url)
            guard let array = try JSONSerialization.jsonObject(with: data,
                                                               options: [.fragmentsAllowed]) as? [[String: Any]]
            else { return }
            uploadQueue = array
            queuedBatchCount = array.count
            // Upload sofort triggern, sobald die App initialisiert ist.
            DispatchQueue.main.async { [weak self] in
                self?.uploadNextIfNeeded()
            }
        } catch {
            // Korruption → Datei wegwerfen, nicht crashen.
            try? FileManager.default.removeItem(at: url)
        }
    }
}
