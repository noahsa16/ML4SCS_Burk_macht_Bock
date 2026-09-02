import SwiftUI

/// Shared top header: centered serif brand, a hairline, the current page caption
/// in gold uppercase, and — pinned top-right — the profile circle that opens
/// the profile sheet.
///
/// It is content, not chrome: every page places it at the top of its own
/// scroll view so it moves with the page instead of standing over it.
struct ScrybeHeader: View {
    let label: String
    /// Paging controls beside the caption. Either one being present shows a
    /// subtle chevron on its side; `nil` hides that side. Heute passes both
    /// so a reader can step through days without discovering the swipe.
    var onPrevious: (() -> Void)? = nil
    var onNext: (() -> Void)? = nil
    /// What the chevrons step through, for VoiceOver. Heute steps days,
    /// Trends steps weeks or months.
    var previousLabel: LocalizedStringKey = "Vorheriger Tag"
    var nextLabel: LocalizedStringKey = "Nächster Tag"
    /// The profile page shows this header too, and must not offer a way into
    /// itself; it passes `false` and draws its own close control.
    var showsProfileEntry = true
    /// Set by a page shown as a sheet: replaces the profile circle with a
    /// close control in the same slot.
    var onClose: (() -> Void)? = nil

    @Environment(\.scrybe) private var theme
    @State private var profilePresented = false

    var body: some View {
        VStack(spacing: 4) {
            Text("Scrybe")
                .font(.system(.title3, design: .serif).weight(.semibold))
                .foregroundStyle(theme.ink)
                .frame(maxWidth: .infinity)
                .overlay(alignment: .trailing) {
                    Group {
                        if let onClose {
                            Button(action: onClose) {
                                Image(systemName: "xmark")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(theme.secondaryInk)
                                    .frame(width: 28, height: 28)
                                    .background(Circle().fill(theme.wash(theme.sepia)))
                                    .overlay(Circle().stroke(theme.sepia.opacity(0.6), lineWidth: 1))
                                    .contentShape(Circle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Schließen")
                        } else if showsProfileEntry {
                            Button { profilePresented = true } label: {
                                ProfileAvatar()
                                    .contentShape(Circle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Profil")
                            .accessibilityHint(Text("Öffnet Profil und Einstellungen."))
                        }
                    }
                }
            Rectangle().fill(theme.hairline).frame(width: 40, height: 1)
            HStack(spacing: 12) {
                chevron("chevron.left", label: previousLabel, action: onPrevious)
                Text(LocalizedStringKey(label))
                    .scrybeCaption(.caption)
                    .contentTransition(.opacity)
                chevron("chevron.right", label: nextLabel, action: onNext)
            }
            .animation(.easeOut(duration: 0.2), value: label)
        }
        .padding(.top, 8)
        .padding(.horizontal, 16)
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isHeader)
        .sheet(isPresented: $profilePresented) {
            ScrybeThemeProvider {
                ProfileView(onClose: { profilePresented = false })
            }
        }
    }

    /// Muted, tiny, and keeping its slot when absent so the caption never
    /// jumps sideways as the last available day hides one side.
    private func chevron(_ symbol: String, label: LocalizedStringKey,
                         action: (() -> Void)?) -> some View {
        Button { action?() } label: {
            Image(systemName: symbol)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(theme.mutedInk)
                .frame(width: 24, height: 24)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .opacity(action == nil ? 0 : 1)
        .disabled(action == nil)
        .accessibilityLabel(label)
        .accessibilityHidden(action == nil)
    }
}

extension View {
    /// The gold, tracked, uppercase caption the header, stat labels and card
    /// titles share. One definition so the tracking cannot drift per site.
    func scrybeCaption(_ style: Font.TextStyle = .caption2) -> some View {
        modifier(ScrybeCaption(style: style))
    }
}

private struct ScrybeCaption: ViewModifier {
    let style: Font.TextStyle
    @Environment(\.scrybe) private var theme

    func body(content: Content) -> some View {
        content
            .textCase(.uppercase)
            .font(.system(style).weight(.medium))
            .tracking(2)
            .foregroundStyle(theme.secondaryInk)
    }
}

#Preview {
    VStack(spacing: 40) {
        ScrybeHeader(label: "Heute", onPrevious: {})
        ScrybeHeader(label: "Gestern", onPrevious: {}, onNext: {})
        ScrybeHeader(label: "Trends")
    }
    .padding(.bottom, 40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
