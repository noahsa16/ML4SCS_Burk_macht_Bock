import Combine
import Foundation
import WatchConnectivity

/// Maintains a WebSocket connection to the FastAPI server.
/// Forwards "start" / "stop" commands to the Watch via WatchConnectivity.
class ServerCommandListener: NSObject, ObservableObject {
    static let shared = ServerCommandListener()

    @Published var isConnected = false
    @Published var currentSessionId: String?
    @Published var currentPersonId: String?
    @Published var currentCommandId: String?
    @Published var lastWatchCommandStatus = "No command sent"
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

    private var task: URLSessionWebSocketTask?
    private var reconnectWorkItem: DispatchWorkItem?
    private var pollAgeTimer: Timer?
    private var sentHello = false
    /// Identifies the current WebSocket "generation". Each connect() bumps this.
    /// Stale receive/send callbacks check their captured epoch and bail out if
    /// the current epoch has moved on — so a cancelled task's failure handler
    /// can never schedule a reconnect against the live connection.
    private var connectionEpoch: Int = 0
    private var lastPollAckKey: String?
    // Protected by pollStateLock — written from WCSession bg thread, read from main-thread timer.
    private let pollStateLock = NSLock()
    private var _lastWatchPollAt: Date?
    private var _lastWatchSnapshot: [String: Any] = [:]
    private var lastWatchPollAt: Date? {
        get { pollStateLock.withLock { _lastWatchPollAt } }
        set { pollStateLock.withLock { _lastWatchPollAt = newValue } }
    }
    private var lastWatchSnapshot: [String: Any] {
        get { pollStateLock.withLock { _lastWatchSnapshot } }
        set { pollStateLock.withLock { _lastWatchSnapshot = newValue } }
    }
    private var serverIP: String { UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147" }
    private var serverWebSocketURL: URL? {
        let trimmed = serverIP
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if trimmed.hasPrefix("http://") {
            return URL(string: "ws://" + String(trimmed.dropFirst("http://".count)) + "/ws")
        }
        if trimmed.hasPrefix("https://") {
            return URL(string: "wss://" + String(trimmed.dropFirst("https://".count)) + "/ws")
        }
        let host = trimmed.contains(":") ? trimmed : "\(trimmed):8000"
        return URL(string: "ws://\(host)/ws")
    }

    private override init() {
        super.init()
        connect()
        startPollAgeTimer()
    }

    func connect() {
        reconnectWorkItem?.cancel()
        reconnectWorkItem = nil
        connectionEpoch &+= 1
        task?.cancel(with: .goingAway, reason: nil)

        guard let url = serverWebSocketURL else { return }
        let epoch = connectionEpoch
        task = URLSession.shared.webSocketTask(with: url)
        task?.resume()
        isConnected = false
        sentHello = false
        listenLoop(epoch: epoch)
    }

    private func listenLoop(epoch: Int) {
        task?.receive { [weak self] result in
            guard let self, epoch == self.connectionEpoch else { return }
            switch result {
            case .failure:
                DispatchQueue.main.async { self.isConnected = false }
                self.scheduleReconnect()
            case .success(let msg):
                DispatchQueue.main.async { self.isConnected = true }
                if !self.sentHello {
                    self.sentHello = true
                    self.sendServerEvent(["type": "hello", "client": "iphone"])
                    self.sendPhoneStatus()
                }
                self.handle(msg)
                self.listenLoop(epoch: epoch)
            }
        }
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
                AirPodsMotionManager.shared.start()
            } else if type == "stop" {
                let commandId = self.extractCommandId(from: json)
                self.currentCommandId = commandId
                self.forwardToWatch(self.watchPayload(command: "stop",
                                                      sessionId: json["session_id"] as? String,
                                                      personId: nil,
                                                      commandId: commandId))
                self.currentSessionId = nil
                self.currentPersonId  = nil
                AirPodsMotionManager.shared.stop()
            } else if type == "airpods_start" {
                AirPodsMotionManager.shared.start()
            } else if type == "airpods_stop" {
                AirPodsMotionManager.shared.stop()
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
        var payload: [String: Any] = ["command": command, "server_ip": serverIP]
        if let sessionId, !sessionId.isEmpty { payload["session_id"] = sessionId }
        if let personId, !personId.isEmpty { payload["person_id"] = personId }
        if let commandId, !commandId.isEmpty { payload["command_id"] = commandId }
        // H3: Motion-Config aus den Phone-App-Settings mitgeben. Die Watch
        // liest sie in handleCommand() — auch via 1-s-Poll-Reply, also ohne
        // dass ein expliziter Push nötig wäre.
        let hz = UserDefaults.standard.double(forKey: "requestedHz")
        if hz >= 10 { payload["requested_hz"] = hz }
        let batch = UserDefaults.standard.integer(forKey: "batchSize")
        if batch >= 1 { payload["batch_size"] = batch }
        return payload
    }

    func currentWatchCommandPayload() -> [String: Any] {
        if let currentSessionId {
            return watchPayload(command: "start",
                                sessionId: currentSessionId,
                                personId: currentPersonId,
                                commandId: currentCommandId)
        }
        return watchPayload(command: "stop",
                            sessionId: nil,
                            personId: nil,
                            commandId: currentCommandId)
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
        sendServerEvent([
            "type": "phone_status",
            "watch_reachable": true,
            "watch_polling": true,
            "watch_running": watchRunning,
            "watch_session_id": watchSessionId,
            "watch_samples": message["sample_count"] as? Int ?? 0,
            "watch_queued_samples": message["queued_samples"] as? Int ?? 0,
            "watch_delivered_samples": message["delivered_samples"] as? Int ?? 0,
            "watch_failed_batches": message["failed_batches"] as? Int ?? 0,
            "watch_upload_mode": message["upload_mode"] as? String ?? "",
            "current_session_id": currentSessionId ?? "",
            "current_command_id": currentCommandId ?? "",
            "watch_last_command_id": watchLastCommandId,
            "last_watch_command_status": lastWatchCommandStatus,
            "last_watch_poll_status": pollStatus
        ])
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
        forwardToWatch(["command": "drain_spill", "server_ip": serverIP])
    }

    /// „Spill verwerfen": die Watch löscht ihren persistenten Buffer. Die Watch
    /// verweigert das während einer laufenden Aufnahme (Schutz des Live-Staus).
    func clearWatchSpill() {
        forwardToWatch(["command": "clear_spill", "server_ip": serverIP])
    }

    private func updatePublishedWatchStatus(from message: [String: Any], pollAgeMs: Int?) {
        DispatchQueue.main.async {
            self.watchPolling = (pollAgeMs ?? 0) < 3000
            self.watchPollAgeMs = pollAgeMs
            self.watchRunning = message["is_running"] as? Bool ?? false
            self.watchSessionId = message["session_id"] as? String ?? ""
            self.watchSampleCount = message["sample_count"] as? Int ?? 0
            self.watchQueuedSamples = message["queued_samples"] as? Int ?? 0
            self.watchDeliveredSamples = message["delivered_samples"] as? Int ?? 0
            self.watchFailedBatches = message["failed_batches"] as? Int ?? 0
            self.watchLastCommandId = message["last_command_id"] as? String ?? ""
            self.watchUploadMode = message["upload_mode"] as? String ?? "Offline"
        }
    }

    private func confirmCommandFromWatchPoll(command: String,
                                             watchRunning: Bool,
                                             watchSessionId: String,
                                             watchLastCommandId: String) {
        let expectedSessionId = currentSessionId ?? ""
        let expectedCommandId = currentCommandId ?? ""
        let commandIdMatches = expectedCommandId.isEmpty || watchLastCommandId == expectedCommandId
        let commandApplied = commandIdMatches && (
            (command == "start" && watchRunning && watchSessionId == expectedSessionId) ||
            (command == "stop" && !watchRunning)
        )
        guard commandApplied else { return }

        let ackKey = "\(command)|\(expectedSessionId)|\(watchRunning)|\(expectedCommandId)"
        guard ackKey != lastPollAckKey else { return }
        lastPollAckKey = ackKey
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

    func forwardToWatch(_ payload: [String: Any]) {
        let command = payload["command"] as? String ?? "unknown"
        let sessionId = payload["session_id"] as? String
        let commandId = payload["command_id"] as? String

        // Why: ein neuer Befehl macht alle gequeueten älteren obsolet. Ohne
        // Cancel stellt die transferUserInfo-FIFO Minuten-alte stop/start-
        // Paare mitten in eine laufende Session zu (S044, 2026-06-12).
        // Spiegelbild von cancelStaleUserInfoTransfers() auf der Watch-Seite;
        // phone-seitig laufen über transferUserInfo ausschließlich Commands.
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
            }
        }, errorHandler: { [weak self] error in
            DispatchQueue.main.async {
                self?.transferUserInfoToWatch(payload,
                                              command: command)
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

        let epoch = connectionEpoch
        task?.send(.string(text)) { [weak self] error in
            guard let self, error != nil, epoch == self.connectionEpoch else { return }
            DispatchQueue.main.async { self.isConnected = false }
            self.scheduleReconnect()
        }
    }

    func sendPhoneStatus() {
        let pollAgeMs = lastWatchPollAt.map { Int(Date().timeIntervalSince($0) * 1000) }
        let watchPolling = pollAgeMs.map { $0 < 3000 } ?? false
        let airpods = AirPodsMotionManager.shared
        sendServerEvent([
            "type": "phone_status",
            "watch_reachable": WCSession.default.isReachable || watchPolling,
            "watch_polling": watchPolling,
            "watch_poll_age_ms": pollAgeMs ?? -1,
            "watch_running": lastWatchSnapshot["is_running"] as? Bool ?? false,
            "watch_session_id": lastWatchSnapshot["session_id"] as? String ?? "",
            "watch_samples": lastWatchSnapshot["sample_count"] as? Int ?? 0,
            "watch_queued_samples": lastWatchSnapshot["queued_samples"] as? Int ?? 0,
            "watch_delivered_samples": lastWatchSnapshot["delivered_samples"] as? Int ?? 0,
            "watch_failed_batches": lastWatchSnapshot["failed_batches"] as? Int ?? 0,
            "watch_upload_mode": lastWatchSnapshot["upload_mode"] as? String ?? "",
            "current_session_id": currentSessionId ?? "",
            "current_command_id": currentCommandId ?? "",
            "watch_last_command_id": lastWatchSnapshot["last_command_id"] as? String ?? "",
            "last_watch_command_status": lastWatchCommandStatus,
            "last_watch_poll_status": lastWatchPollStatus,
            "airpods_available": airpods.isAvailable,
            "airpods_paired": airpods.isHeadphonesConnected,
            "airpods_streaming": airpods.isStreaming,
            "airpods_samples": airpods.sampleCount,
            "airpods_uploaded": airpods.uploadedCount,
            "airpods_queued": airpods.queuedBatchCount,
            "airpods_failed_batches": airpods.failedUploadCount,
            "airpods_dropped_batches": airpods.droppedBatchCount,
            "airpods_last_error": airpods.lastError,
        ])
    }

    private func scheduleReconnect() {
        reconnectWorkItem?.cancel()
        let item = DispatchWorkItem { [weak self] in self?.connect() }
        reconnectWorkItem = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: item)
    }

    private func startPollAgeTimer() {
        pollAgeTimer?.invalidate()
        pollAgeTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            let age = self.lastWatchPollAt.map { Int(Date().timeIntervalSince($0) * 1000) }
            let isFresh = age.map { $0 < 3000 } ?? false
            DispatchQueue.main.async {
                self.watchPollAgeMs = age
                self.watchPolling = isFresh
            }
        }
    }
}
