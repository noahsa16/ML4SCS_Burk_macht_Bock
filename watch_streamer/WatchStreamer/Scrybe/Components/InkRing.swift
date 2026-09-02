import SwiftUI

struct InkRing: View {
    let fraction: Double
    var lineWidth: CGFloat = 16
    var centerText: String? = nil
    var subtitle: String? = nil
    /// Ring fill colour; defaults to the theme accent. Pass the goal-reached tone
    /// at the goal-met moment.
    var tint: Color? = nil
    /// Curve for the fill sweep when `fraction` changes. `nil` keeps the
    /// component's own gentle default (and Reduce Motion's plain snap) — a
    /// caller marking one specific update as an event (e.g. minutes a pull
    /// just harvested) passes its own curve, already resolved for Reduce
    /// Motion, so it applies only to that update rather than every change.
    var sweepAnimation: Animation? = nil

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Larger than `.largeTitle`: the figure is the page's one headline and
    /// the ring gives it room. Scaled so Dynamic Type still moves it.
    @ScaledMetric(relativeTo: .largeTitle) private var centerSize: CGFloat = 52

    private var clamped: Double { max(0, min(1, fraction)) }

    var body: some View {
        ZStack {
            Circle().stroke(theme.track, lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: clamped)
                .stroke(tint ?? theme.accent,
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(sweepAnimation ?? (reduceMotion ? nil : .easeOut(duration: 0.6)),
                          value: fraction)
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.4), value: tint)
            VStack(spacing: 8) {
                if let centerText {
                    Text(centerText)
                        // Why `.regular` and not a heavier weight: a serif
                        // carries hierarchy through size, and this figure is
                        // already the largest thing on the screen. Bold, round
                        // and centred is the fitness-app reflex this design is
                        // avoiding.
                        .font(.system(size: centerSize, weight: .regular, design: .serif))
                        .foregroundStyle(theme.ink)
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                        .contentTransition(.numericText())
                        .animation(reduceMotion ? nil : .easeOut(duration: 0.4), value: centerText)
                }
                if centerText != nil, subtitle != nil {
                    // The same short rule the header draws under the brand,
                    // so the ring's centre reads as a small title block.
                    Rectangle().fill(theme.hairline).frame(width: 40, height: 1)
                }
                if let subtitle {
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(theme.secondaryInk)
                        .multilineTextAlignment(.center)
                }
            }
            .padding(lineWidth * 2)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Schreibzeit heute")
        .accessibilityValue([centerText, subtitle].compactMap { $0 }.joined(separator: ", "))
    }
}

#Preview {
    InkRing(fraction: 0.73, centerText: "1:47", subtitle: "73 % von 2 Std.")
        .frame(width: 240, height: 240)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
