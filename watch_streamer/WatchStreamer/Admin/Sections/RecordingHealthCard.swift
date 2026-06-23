import SwiftUI

struct RecordingHealthCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var health = RecordingHealthStore.shared
    @Environment(\.scrybe) private var theme

    private var hasSession: Bool { server.currentSessionId != nil }
    private var pollFresh: Bool { server.watchPolling }
    private var dataFlowing: Bool { health.dataFlowing }
    private var wsUp: Bool { server.isConnected }

    private enum Verdict { case idle, healthy, warning, error }
    private var verdict: Verdict {
        guard hasSession else { return .idle }
        if dataFlowing && pollFresh { return .healthy }   // Why: green = data over HTTP + fresh watch poll; WS is command-only
        if !dataFlowing && !pollFresh && !wsUp { return .error }
        return .warning
    }

    var body: some View {
        AdminCard(title: "Recording-Health") {
            HStack(spacing: 8) {
                Circle().fill(color).frame(width: 12, height: 12)
                Text(label).font(.headline).foregroundStyle(theme.ink)
            }
            .accessibilityElement(children: .combine)
            HStack(spacing: 8) {
                flag("WS", "WebSocket", wsUp)
                flag("DATA", "Datenfluss", dataFlowing)
                flag("WATCH", "Watch-Poll", pollFresh)
            }
        }
    }

    private var label: String {
        switch verdict {
        case .idle: return "Keine Aufnahme"
        case .healthy: return "Gesund"
        case .warning: return "Upload staut sich"
        case .error: return "Fehler"
        }
    }
    private var color: Color {
        switch verdict {
        case .idle: return theme.mutedInk
        case .healthy: return theme.success
        case .warning: return theme.warning
        case .error: return theme.danger
        }
    }
    @ViewBuilder private func flag(_ name: String, _ a11yName: String, _ on: Bool) -> some View {
        Text(name)
            .font(.caption2.weight(.bold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill((on ? theme.success : theme.ink).opacity(0.12)))
            .foregroundStyle(on ? theme.success : theme.sepia)
            .accessibilityLabel(a11yName)
            .accessibilityValue(on ? "aktiv" : "inaktiv")
    }
}
