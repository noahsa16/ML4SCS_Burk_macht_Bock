import SwiftUI
import Combine

struct SessionCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @Environment(\.scrybe) private var theme
    @State private var elapsed = 0
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var hasSession: Bool { server.currentSessionId != nil }

    var body: some View {
        AdminCard(title: "Session") {
            if hasSession, let sid = server.currentSessionId {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(sid).font(.headline).foregroundStyle(theme.ink)
                        Text(server.currentPersonId ?? "Anonymous")
                            .font(.caption).foregroundStyle(theme.sepia)
                    }
                    Spacer()
                    Text(String(format: "%02d:%02d", elapsed / 60, elapsed % 60))
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                        .foregroundStyle(theme.ink)
                        .accessibilityLabel("Laufzeit \(elapsed / 60) Minuten \(elapsed % 60) Sekunden")
                }
                Button(role: .destructive, action: stopSession) {
                    Text("STOP")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(.white)
                        .scrybeSurface(cornerRadius: 12, tint: theme.danger, interactive: true)
                }
            } else {
                Text("Keine aktive Session")
                    .font(.subheadline).foregroundStyle(theme.ink)
                Text("Session im Dashboard starten.")
                    .font(.caption).foregroundStyle(theme.sepia)
            }
        }
        .onReceive(timer) { _ in if hasSession { elapsed += 1 } }
        .onChange(of: server.currentSessionId) { sid in if sid == nil { elapsed = 0 } }
    }

    private func stopSession() {
        guard let url = URL(string: PhoneBridge.serverBaseURL + "/session/stop") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 6
        // Why: the server broadcasts {type:"stop"} over WS → ServerCommandListener
        // clears currentSessionId, so the card updates reactively.
        Task { _ = try? await URLSession.shared.data(for: req) }
    }
}
