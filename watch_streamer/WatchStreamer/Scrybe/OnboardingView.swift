import SwiftUI

struct OnboardingView: View {
    @Environment(\.scrybe) private var theme
    @ScaledMetric(relativeTo: .largeTitle) private var iconSize: CGFloat = 44

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "applewatch")
                .font(.system(size: iconSize))
                .foregroundStyle(theme.accent)
                .accessibilityHidden(true)
            Text("Trag die Watch und fang an zu schreiben")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
            Text("Deine Schreibzeit erscheint hier, sobald die erste Aufnahme läuft.")
                .font(.subheadline)
                .foregroundStyle(theme.sepia)
                .multilineTextAlignment(.center)
        }
        .padding(32)
        .scrybeSurface(cornerRadius: 20)
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    OnboardingView()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
