import SwiftUI

/// The one persistent Watch status in the app. The Watch glyph communicates
/// connection; a tiny ink dot appears while writing was detected recently
/// enough to still read as in progress.
struct WatchStatusDot: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false
    /// Re-read on appear so a stale "recent" cannot outlive a backgrounded app.
    @State private var at = Date()

    private var connected: Bool { server.watchPolling || bridge.isConnected }
    // Why not `server.liveInference`: that rides the server's 1 Hz broadcast,
    // which Scrybe no longer runs, and it deliberately holds its last value —
    // so it stays dark without a server and can stay lit after one goes away.
    private var writing: Bool { focus.isRecentlyWriting(now: at) }
    private var color: Color { connected ? theme.success : theme.mutedInk }
    private var a11y: String {
        if writing { return "Watch verbunden, kürzlich Schreiben erkannt" }
        return connected ? "Watch verbunden, kein Schreiben erkannt" : "Watch getrennt"
    }

    var body: some View {
        Image(systemName: "applewatch")
            .font(.system(size: 15, weight: .medium))
            .foregroundStyle(color)
            .overlay(alignment: .bottomTrailing) {
                if writing {
                    Circle()
                        .fill(theme.accent)
                        .frame(width: 7, height: 7)
                        .overlay(Circle().stroke(theme.paper, lineWidth: 1.5))
                        .scaleEffect(pulse ? 1.18 : 1)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            .accessibilityLabel(a11y)
            .onChange(of: writing) { _ in updatePulse() }
            .onChange(of: scenePhase) { _ in at = Date() }
            .onAppear { at = Date(); updatePulse() }
    }

    private func updatePulse() {
        guard writing, !reduceMotion else {
            pulse = false
            return
        }
        withAnimation(.easeInOut(duration: 0.85).repeatForever(autoreverses: true)) {
            pulse = true
        }
    }
}

#Preview {
    WatchStatusDot()
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
