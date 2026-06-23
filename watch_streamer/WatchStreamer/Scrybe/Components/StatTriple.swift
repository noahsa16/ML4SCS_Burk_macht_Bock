import SwiftUI

/// Three equal-weight day stats under the Heute ring: sessions, longest stretch,
/// current streak. All values derive client-side from today's stretches + streak.
struct StatTriple: View {
    let sessions: Int
    let longestSeconds: Double
    let streak: Int
    @Environment(\.scrybe) private var theme

    private var longestText: String {
        longestSeconds > 0 ? TimeFormatting.human(seconds: longestSeconds) : "—"
    }

    var body: some View {
        HStack(spacing: 0) {
            stat(value: "\(sessions)", label: "Sessions", a11y: "\(sessions) Sessions heute")
            divider
            stat(value: longestText, label: "Längste", a11y: "Längste Session \(longestText)")
            divider
            stat(value: "\(streak)", label: "Streak", a11y: "Streak \(streak) Tage")
        }
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity)
        .scrybeSurface(cornerRadius: 16)
    }

    private func stat(value: String, label: String, a11y: String) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .contentTransition(.numericText())
            Text(LocalizedStringKey(label))
                .textCase(.uppercase)
                .font(.caption2.weight(.medium))
                .tracking(1)
                .foregroundStyle(theme.sepia)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(a11y)
    }

    private var divider: some View {
        Rectangle().fill(theme.hairline).frame(width: 1, height: 28)
    }
}

#Preview {
    StatTriple(sessions: 3, longestSeconds: 1500, streak: 5)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
