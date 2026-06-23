import SwiftUI

struct InkRing: View {
    let fraction: Double
    var lineWidth: CGFloat = 16
    var centerText: String? = nil
    var subtitle: String? = nil

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Circle().stroke(theme.track, lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: max(0.001, min(1, fraction)))
                .stroke(theme.accent,
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.6), value: fraction)
            VStack(spacing: 4) {
                if let centerText {
                    Text(centerText)
                        .font(.system(.largeTitle, design: .serif).weight(.semibold))
                        .foregroundStyle(theme.ink)
                        .monospacedDigit()
                        .contentTransition(.numericText())
                        .animation(reduceMotion ? nil : .easeInOut(duration: 0.4), value: centerText)
                }
                if let subtitle {
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(theme.sepia)
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
