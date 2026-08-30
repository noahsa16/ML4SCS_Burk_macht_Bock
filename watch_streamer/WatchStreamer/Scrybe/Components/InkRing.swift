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
            VStack(spacing: 4) {
                if let centerText {
                    Text(centerText)
                        .font(.system(.largeTitle, design: .serif).weight(.semibold))
                        .foregroundStyle(theme.ink)
                        .monospacedDigit()
                        .contentTransition(.numericText())
                        .animation(reduceMotion ? nil : .easeOut(duration: 0.4), value: centerText)
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
    InkRing(fraction: 0.73, centerText: "1:47", subtitle: "73 % · Ziel 2 h")
        .frame(width: 240, height: 240)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
