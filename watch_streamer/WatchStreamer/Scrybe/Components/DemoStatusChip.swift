import SwiftUI

struct DemoStatusChip: View {
    let isWriting: Bool
    @Environment(\.scrybe) private var theme

    var body: some View {
        HStack(spacing: 8) {
            Text("DEMO")
                .font(.caption2.weight(.bold))
                .tracking(1)
            Circle()
                .fill(isWriting ? theme.success : theme.warning)
                .frame(width: 8, height: 8)
                .accessibilityHidden(true)
            Text(isWriting ? "Schreiben erkannt" : "Kurze Pause")
                .font(.footnote.weight(.medium))
        }
        .foregroundStyle(theme.ink)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .scrybeCapsuleSurface(
            tint: theme.wash(isWriting ? theme.success : theme.warning)
        )
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    VStack(spacing: 16) {
        DemoStatusChip(isWriting: true)
        DemoStatusChip(isWriting: false)
    }
    .padding(40)
    .scrybeTheme()
}
