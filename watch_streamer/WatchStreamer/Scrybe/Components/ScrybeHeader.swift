import SwiftUI

/// Shared top header: centered serif brand, a hairline, the current page caption
/// in gold uppercase, and a Watch-connection indicator pinned top-right.
struct ScrybeHeader: View {
    let label: String
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(spacing: 4) {
            Text("Scrybe")
                .font(.system(.title, design: .serif).weight(.semibold))
                .foregroundStyle(theme.ink)
                .frame(maxWidth: .infinity)
                .overlay(alignment: .trailing) {
                    WatchStatusDot()
                }
            Rectangle().fill(theme.hairline).frame(width: 40, height: 1)
            Text(LocalizedStringKey(label))
                .textCase(.uppercase)
                .font(.caption.weight(.medium))
                .tracking(1.5)
                .foregroundStyle(theme.sepia)
        }
        .padding(.top, 8)
        .padding(.horizontal, 16)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

#Preview {
    ScrybeHeader(label: "Heute")
        .padding(.bottom, 40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
