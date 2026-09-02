import Foundation

/// Parses the operator-supplied server address once and derives every endpoint
/// from it.
///
/// HTTP upload and WebSocket control previously implemented their own trimming,
/// scheme and default-port logic, so an IPv6 literal, an explicit port or a TLS
/// address could be interpreted differently by the two paths.
public nonisolated enum ServerEndpoint {
    public struct Resolved: Equatable, Sendable {
        public let httpBase: URL
        public let watchUpload: URL
        public let webSocket: URL
        public let isSecure: Bool
    }

    public static let defaultPort = 8000

    /// Returns nil when `raw` cannot be read as a host — callers must surface
    /// that as a configuration error rather than falling back to a guess.
    public static func resolve(_ raw: String) -> Resolved? {
        let trimmed = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !trimmed.isEmpty else { return nil }

        let secure = trimmed.hasPrefix("https://")
        let withScheme: String
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            withScheme = trimmed
        } else {
            withScheme = "http://" + trimmed
        }

        guard var components = URLComponents(string: withScheme),
              let host = components.host, !host.isEmpty else { return nil }

        if components.port == nil { components.port = defaultPort }
        components.path = ""
        components.query = nil
        components.fragment = nil
        guard let base = components.url else { return nil }

        var socket = components
        socket.scheme = secure ? "wss" : "ws"
        socket.path = "/ws"
        guard let ws = socket.url else { return nil }

        return Resolved(httpBase: base,
                        watchUpload: base.appendingPathComponent("watch"),
                        webSocket: ws,
                        isSecure: secure)
    }
}
