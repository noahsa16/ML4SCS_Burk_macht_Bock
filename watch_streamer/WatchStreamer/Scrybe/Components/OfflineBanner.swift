import SwiftUI

struct OfflineBanner: View {
    let lastUpdated: Date?

    @Environment(\.scrybe) private var theme

    private var message: String {
        guard let lastUpdated else { return "Uhr nicht erreichbar" }
        let time = lastUpdated.formatted(date: .omitted, time: .shortened)
        return "Uhr nicht erreichbar · Stand \(time)"
    }

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "applewatch.slash")
                .accessibilityHidden(true)
            Text(message)
        }
        .font(.caption)
        .foregroundStyle(theme.warning)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .scrybeCapsuleSurface(tint: theme.wash(theme.warning))
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    VStack(spacing: 16) {
        OfflineBanner(lastUpdated: Date())
        OfflineBanner(lastUpdated: nil)
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
