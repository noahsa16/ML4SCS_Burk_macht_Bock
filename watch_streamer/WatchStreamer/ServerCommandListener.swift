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
    @Published var lastWatchCommandStatus = "No command sent"

    private var task: URLSessionWebSocketTask?
    private var reconnectWorkItem: DispatchWorkItem?
    private var sentHello = false
    private var serverIP: String { UserDefaults.standard.string(forKey: "serverIP") ?? "192.168.178.147" }

    private override init() {
        super.init()
        connect()
    }

    func connect() {
        reconnectWorkItem?.cancel()
        task?.cancel(with: .goingAway, reason: nil)

        guard let url = URL(string: "ws://\(serverIP):8000/ws") else { return }
        task = URLSession.shared.webSocketTask(with: url)
        task?.resume()
        isConnected = false
        sentHello = false
        listenLoop()
    }

    private func listenLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
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
                self.listenLoop()
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
                self.currentSessionId = sid
                self.currentPersonId  = pid
                self.forwardToWatch(self.watchPayload(command: "start", sessionId: sid, personId: pid))
            } else if type == "stop" {
                self.forwardToWatch(["command": "stop"])
                self.currentSessionId = nil
                self.currentPersonId  = nil
            } else if type == "status" {
                let active = json["session_active"] as? Bool ?? false
                if active, let sid = json["session_id"] as? String {
                    let pid = json["person_id"] as? String
                    if self.currentSessionId != sid {
                        self.forwardToWatch(self.watchPayload(command: "start", sessionId: sid, personId: pid))
                    }
                    self.currentSessionId = sid
                    self.currentPersonId = pid
                } else if self.currentSessionId != nil {
                    self.forwardToWatch(["command": "stop"])
                    self.currentSessionId = nil
                    self.currentPersonId = nil
                }
                self.sendPhoneStatus()
            }
        }
    }

    private func watchPayload(command: String, sessionId: String?, personId: String?) -> [String: Any] {
        var payload: [String: Any] = ["command": command]
        if let sessionId, !sessionId.isEmpty { payload["session_id"] = sessionId }
        if let personId, !personId.isEmpty { payload["person_id"] = personId }
        return payload
    }

    private func forwardToWatch(_ payload: [String: Any]) {
        let command = payload["command"] as? String ?? "unknown"
        let sessionId = payload["session_id"] as? String

        guard WCSession.default.isReachable else {
            let detail = "Watch not reachable"
            lastWatchCommandStatus = "\(command): \(detail)"
            sendServerEvent([
                "type": "watch_ack",
                "ok": false,
                "command": command,
                "session_id": sessionId ?? "",
                "detail": detail
            ])
            return
        }

        WCSession.default.sendMessage(payload, replyHandler: { [weak self] reply in
            DispatchQueue.main.async {
                self?.lastWatchCommandStatus = "\(command): acknowledged"
                self?.sendServerEvent([
                    "type": "watch_ack",
                    "ok": true,
                    "command": command,
                    "session_id": sessionId ?? "",
                    "detail": "Watch acknowledged command",
                    "reply": reply
                ])
            }
        }, errorHandler: { [weak self] error in
            DispatchQueue.main.async {
                self?.lastWatchCommandStatus = "\(command): \(error.localizedDescription)"
                self?.sendServerEvent([
                    "type": "watch_ack",
                    "ok": false,
                    "command": command,
                    "session_id": sessionId ?? "",
                    "detail": error.localizedDescription
                ])
            }
        })
    }

    private func sendServerEvent(_ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8)
        else { return }

        task?.send(.string(text)) { [weak self] error in
            if error != nil {
                DispatchQueue.main.async { self?.isConnected = false }
                self?.scheduleReconnect()
            }
        }
    }

    private func sendPhoneStatus() {
        sendServerEvent([
            "type": "phone_status",
            "watch_reachable": WCSession.default.isReachable,
            "current_session_id": currentSessionId ?? "",
            "last_watch_command_status": lastWatchCommandStatus
        ])
    }

    private func scheduleReconnect() {
        let item = DispatchWorkItem { [weak self] in self?.connect() }
        reconnectWorkItem = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: item)
    }
}
