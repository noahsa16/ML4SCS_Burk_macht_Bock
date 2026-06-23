import SwiftUI

/// Small Watch-connection indicator for the header: filled accent-green while the
/// watch is actively streaming, muted when no recent samples have arrived.
struct WatchStatusDot: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @Environment(\.scrybe) private var theme

    private var connected: Bool { server.watchPolling }
    private var color: Color { connected ? theme.success : theme.mutedInk }
    private var a11y: String { connected ? "Watch verbunden" : "Watch getrennt" }

    var body: some View {
        Image(systemName: "applewatch")
            .font(.system(size: 15, weight: .medium))
            .foregroundStyle(color)
            .accessibilityLabel(a11y)
    }
}

#Preview {
    WatchStatusDot()
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
