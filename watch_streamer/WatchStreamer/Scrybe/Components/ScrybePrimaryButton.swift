import SwiftUI

/// Full-width accent pill shared by Scrybe's focus and onboarding flows. The
/// label is set in the same tracked capitals as the section captions, so the
/// one filled shape on a page still speaks the page's typography.
struct ScrybePrimaryButton: View {
    let title: LocalizedStringKey
    var verticalPadding: CGFloat = 16
    let action: () -> Void

    @Environment(\.scrybe) private var theme

    init(_ title: LocalizedStringKey, verticalPadding: CGFloat = 16,
         action: @escaping () -> Void) {
        self.title = title
        self.verticalPadding = verticalPadding
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Text(title)
                .textCase(.uppercase)
                .font(.subheadline.weight(.semibold))
                .tracking(2.5)
                .frame(maxWidth: .infinity)
                .padding(.vertical, verticalPadding)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.paperTop)
        .background(theme.accent, in: Capsule())
        .frame(minHeight: 44)
    }
}

#Preview {
    ScrybePrimaryButton("Sitzung starten") {}
        .padding(24)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
