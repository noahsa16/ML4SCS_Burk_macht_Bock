import SwiftUI

struct ConnectionsCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @Environment(\.scrybe) private var theme

    var body: some View {
        AdminCard(title: "Verbindungen") {
            row("Server", server.isConnected, server.isConnected ? "verbunden" : "getrennt")
            row("iPhone-Bridge", bridge.isConnected, bridge.isConnected ? "aktiv" : "inaktiv")
            row("Watch", server.watchRunning, server.watchRunning ? "läuft" : "bereit")

            Button { server.reconnectAndRefresh() } label: {
                Label("Server neu verbinden", systemImage: "arrow.clockwise")
                    .font(.subheadline.weight(.medium))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .foregroundStyle(theme.accent)
                    .scrybeSurface(cornerRadius: 12, tint: theme.accent.opacity(0.10), interactive: true)
            }
            .padding(.top, 4)
        }
    }

    @ViewBuilder private func row(_ name: String, _ ok: Bool, _ detail: String) -> some View {
        HStack(spacing: 8) {
            Circle().fill(ok ? theme.success : theme.mutedInk).frame(width: 10, height: 10)
            Text(name).foregroundStyle(theme.ink)
            Spacer()
            Text(detail).font(.caption).foregroundStyle(theme.sepia)
        }
        .accessibilityElement(children: .combine)
    }
}
