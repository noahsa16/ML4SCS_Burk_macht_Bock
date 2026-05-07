import Combine
import Foundation
import WatchConnectivity
#if canImport(UIKit)
import UIKit
#endif

class PhoneBridge: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = PhoneBridge()

    // MARK: – Tuning constants

    /// Hard limit für die Upload-Queue. Bei 50 Hz und Batches à 5 Samples
    /// = 200 batches × 5 = 1000 samples = ~20 s Backlog. Reicht für kurze
    /// Server-Ausfälle, kappt RAM-Wachstum bei längeren.
    private static let maxQueueSize = 200

    /// Disk-Persistierung — überlebt App-Crash / Force-Quit. Datei landet in
    /// Documents/, weil das in iCloud-Backups inkludiert ist UND nach App-
    /// Updates erhalten bleibt (im Gegensatz zu Caches/).
    private static let queueFileName = "upload_queue.json"

    /// Coalesce-Delay für Disk-Writes. 500 ms Debounce → wir schreiben nicht
    /// nach jedem einzelnen Batch (50 Hz wäre Overkill), aber bei Crash gehen
    /// max ~25 Samples verloren.
    private static let persistDebounce: TimeInterval = 0.5

    // MARK: – Server URL helpers

    static var serverBaseURL: String {
        let raw = UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147"
        let trimmed = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return trimmed
        }
        return trimmed.contains(":") ? "http://\(trimmed)" : "http://\(trimmed):8000"
    }

    static var serverAddress: String {
        "\(serverBaseURL)/watch"
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

    private lazy var queueFileURL: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory,
                                            in:  .userDomainMask)[0]
        return docs.appendingPathComponent(Self.queueFileName)
    }()

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
            self.syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
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
        let accepted = receivePayload(message, source: "message")
        replyHandler(["ok": accepted])
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        if userInfo["type"] as? String == "command_poll" {
            _ = ServerCommandListener.shared.handleWatchCommandPoll(userInfo)
            return
        }
        receivePayload(userInfo, source: "background")
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async {
            self.applyReachability(session)
            self.syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
            ServerCommandListener.shared.sendPhoneStatus()
        }
    }

    func syncServerIP(_ ip: String) {
        let trimmed = ip.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        UserDefaults.standard.set(trimmed, forKey: "serverIP")
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
        syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
        ServerCommandListener.shared.sendPhoneStatus()
    }

    func resyncWatchContext() {
        syncServerIP(UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147")
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
    }

    // MARK: – Receive (off-main heavy work)

    @discardableResult
    private func receivePayload(_ payload: [String: Any], source: String) -> Bool {
        // Heavy parsing + magnitude calc auf workQueue. Kommt zurück mit
        // (normalized, accValues, gyroValues) und wird auf main verarbeitet.
        workQueue.async { [weak self] in
            guard let self else { return }

            guard let normalized = self.normalizePayload(payload, source: source),
                  let samples = normalized["samples"] as? [[String: Any]] else {
                DispatchQueue.main.async {
                    self.lastError = "Invalid watch payload"
                }
                return
            }

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

                self.schedulePersist()
                self.uploadNextIfNeeded()
            }
        }
        return true
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
        guard let url = URL(string: Self.serverAddress) else {
            lastError = "Invalid server URL"
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
        req.httpBody = body

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
                self.schedulePersist()
                self.uploadNextIfNeeded()
            }
        }.resume()
    }

    private func scheduleRetry() {
        queuedBatchCount = uploadQueue.count
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            self.uploadNextIfNeeded()
        }
    }

    private static func currentTimestampMillis() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }

    // MARK: – Disk persistence (debounced)

    /// Auf main thread aufrufen — pausiert vorhandenen pending write und
    /// schedult einen neuen mit `persistDebounce` Verzögerung. Mehrere Aufrufe
    /// in kurzer Folge → nur ein Write am Ende.
    private func schedulePersist() {
        persistTask?.cancel()
        let snapshot = uploadQueue
        let work = DispatchWorkItem { [weak self] in
            self?.writeQueueToDisk(snapshot)
        }
        persistTask = work
        persistQueue.asyncAfter(deadline: .now() + Self.persistDebounce, execute: work)
    }

    /// Sofort persistieren — bei Backgrounding / Termination, kein Debounce.
    @objc private func persistImmediately() {
        persistTask?.cancel()
        let snapshot = uploadQueue
        persistQueue.async { [weak self] in
            self?.writeQueueToDisk(snapshot)
        }
    }

    /// Schreibt die Queue als JSON-Array. Atomic write → entweder vollständig
    /// alt oder vollständig neu, nie korrupt.
    private func writeQueueToDisk(_ snapshot: [[String: Any]]) {
        let url = queueFileURL
        do {
            if snapshot.isEmpty {
                // Datei löschen statt leeres Array schreiben — spart Cycles
                // beim nächsten Launch (kein Decode).
                try? FileManager.default.removeItem(at: url)
                return
            }
            let data = try JSONSerialization.data(withJSONObject: snapshot,
                                                  options: [.fragmentsAllowed])
            try data.write(to: url, options: [.atomic])
        } catch {
            // Persistenz-Fehler sollen den Datenfluss nicht stören. Wir loggen
            // sie nur, blockieren aber nicht den Upload.
            DispatchQueue.main.async {
                self.lastError = "Persist failed: \(error.localizedDescription)"
            }
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
