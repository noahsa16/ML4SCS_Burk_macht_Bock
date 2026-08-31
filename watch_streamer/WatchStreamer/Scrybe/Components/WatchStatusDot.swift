import SwiftUI

/// The one persistent Watch status in the app. The Watch glyph communicates
/// connection; a tiny ink dot appears while the Watch's sensors are running.
struct WatchStatusDot: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @ObservedObject private var focus = FocusStore.shared
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    private var connected: Bool { server.watchPolling || bridge.isConnected }
    // Why not `server.liveInference`: that rides the server's 1 Hz broadcast,
    // which Scrybe no longer runs, and it deliberately holds its last value —
    // so it stays dark without a server and can stay lit after one goes away.
    // Why measuring and not recency: the dot sits beside a live connection
    // glyph, so it reads as a statement about now. Recency answers a different
    // question — one the daily ring asks, and keeps asking, in TodayView.
    private var measuring: Bool { focus.isMeasuringNow }
    private var color: Color { connected ? theme.success : theme.mutedInk }
    private var a11y: String {
        if measuring { return String(localized: "Watch verbunden, Messung läuft") }
        return connected
            ? String(localized: "Watch verbunden, keine Messung")
            : String(localized: "Watch getrennt")
    }

    var body: some View {
        Image(systemName: "applewatch")
            .font(.system(size: 15, weight: .medium))
            .foregroundStyle(color)
            .overlay(alignment: .bottomTrailing) {
                if measuring {
                    Circle()
                        .fill(theme.accent)
                        .frame(width: 7, height: 7)
                        .overlay(Circle().stroke(theme.paper, lineWidth: 1.5))
                        .scaleEffect(pulse ? 1.18 : 1)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            .accessibilityLabel(a11y)
            .onChange(of: measuring) { _ in updatePulse() }
            .onAppear { updatePulse() }
    }

    private func updatePulse() {
        guard measuring, !reduceMotion else {
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
