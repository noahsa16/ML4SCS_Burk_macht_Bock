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
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            action()
        } label: {
            Text(title)
                .textCase(.uppercase)
                .font(.subheadline.weight(.semibold))
                .tracking(2.5)
                .frame(maxWidth: .infinity)
                .padding(.vertical, verticalPadding)
                .foregroundStyle(theme.paperTop)
                .background(theme.accent, in: Capsule())
        }
        .buttonStyle(ScrybePressStyle())
        .frame(minHeight: 44)
    }
}

/// Dims and shrinks the label while the finger is down. `.plain` shows no
/// pressed state at all, so a tap on "Beenden" looked ignored until the
/// next screen arrived.
struct ScrybePressStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.72 : 1)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.975 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

#Preview {
    ScrybePrimaryButton("Sitzung starten") {}
        .padding(24)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
