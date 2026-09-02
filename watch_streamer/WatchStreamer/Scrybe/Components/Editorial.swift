import SwiftUI

// The page-not-card vocabulary the Trends, Fokus and Profil screens share:
// sections separated by a hairline rule, a tracked caption at the top of each,
// an italic serif note in the margin, and a serif figure large enough to be
// the section's headline. Defined once so the three screens read as one book.

/// A full-width hairline between two sections.
struct ScrybeRule: View {
    @Environment(\.scrybe) private var theme

    var body: some View {
        Rectangle()
            .fill(theme.hairline)
            .frame(height: 1)
            .frame(maxWidth: .infinity)
            .accessibilityHidden(true)
    }
}

/// A section's first line: the tracked caption on the left and, optionally,
/// an italic remark on the right.
struct ScrybeSectionHeader<Trailing: View>: View {
    let caption: LocalizedStringKey
    @ViewBuilder var trailing: Trailing

    init(_ caption: LocalizedStringKey, @ViewBuilder trailing: () -> Trailing) {
        self.caption = caption
        self.trailing = trailing()
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(caption).scrybeCaption()
            Spacer(minLength: 12)
            trailing
        }
    }
}

extension ScrybeSectionHeader where Trailing == EmptyView {
    init(_ caption: LocalizedStringKey) {
        self.init(caption, trailing: { EmptyView() })
    }
}

extension View {
    /// The italic serif aside — "+4 Min. vs. Vorwoche", "weiter so!". Serif
    /// and italic because it is commentary on the figures, not one of them.
    func scrybeMarginNote(_ style: Font.TextStyle = .subheadline) -> some View {
        modifier(ScrybeMarginNote(style: style))
    }

    /// The section's headline figure. Regular weight: the serif carries the
    /// hierarchy through size alone, as `InkRing` already argues.
    func scrybeDisplayFigure(size: CGFloat = 56) -> some View {
        modifier(ScrybeDisplayFigure(size: size))
    }
}

private struct ScrybeMarginNote: ViewModifier {
    let style: Font.TextStyle
    @Environment(\.scrybe) private var theme

    func body(content: Content) -> some View {
        content
            .font(.system(style, design: .serif))
            .italic()
            .foregroundStyle(theme.secondaryInk)
    }
}

private struct ScrybeDisplayFigure: ViewModifier {
    let size: CGFloat
    @Environment(\.scrybe) private var theme
    @ScaledMetric(relativeTo: .largeTitle) private var scale: CGFloat = 1

    func body(content: Content) -> some View {
        content
            .font(.system(size: size * scale, weight: .regular, design: .serif))
            .foregroundStyle(theme.ink)
            .monospacedDigit()
            .lineLimit(1)
            .minimumScaleFactor(0.6)
            .contentTransition(.numericText())
    }
}

/// "18" large with a small "m" hanging on its baseline — how the design
/// writes a duration as a figure rather than a clock.
struct DurationFigure: View {
    let seconds: Double
    var size: CGFloat = 56

    @Environment(\.scrybe) private var theme

    private var minutes: Int { Int(max(0, seconds)) / 60 }
    private var hours: Int { minutes / 60 }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 2) {
            if hours > 0 {
                Text("\(hours)").scrybeDisplayFigure(size: size)
                unit("h")
                Text(String(format: "%02d", minutes % 60)).scrybeDisplayFigure(size: size)
                unit("m")
            } else {
                Text("\(minutes)").scrybeDisplayFigure(size: size)
                unit("m")
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(TimeFormatting.abbreviated(seconds: seconds)))
    }

    private func unit(_ text: String) -> some View {
        Text(text)
            .font(.system(size: size * 0.5, weight: .regular, design: .serif))
            .foregroundStyle(theme.secondaryInk)
    }
}

#Preview {
    VStack(alignment: .leading, spacing: 24) {
        ScrybeSectionHeader("Diese Woche") {
            Text(verbatim: "+4 Min. vs. Vorwoche").scrybeMarginNote()
        }
        DurationFigure(seconds: 18 * 60)
        ScrybeRule()
        DurationFigure(seconds: 95 * 60, size: 40)
    }
    .padding(24)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
