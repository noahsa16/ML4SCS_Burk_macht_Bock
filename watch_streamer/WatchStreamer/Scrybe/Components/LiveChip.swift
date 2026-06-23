import SwiftUI

struct LiveChip: View {
    let isWriting: Bool

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    private var animatePulse: Bool { isWriting && !reduceMotion }
    private var dotColor: Color { isWriting ? theme.success : theme.ink.opacity(0.25) }
    private var textColor: Color { isWriting ? theme.ink : theme.sepia }
    private var statusText: String { isWriting ? "schreibt gerade" : "Pause" }
    private var a11yLabel: String { isWriting ? "schreibt gerade" : "keine Schreibaktivität" }

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(dotColor)
                .frame(width: 8, height: 8)
                .scaleEffect(pulse ? 1.4 : 1.0)
            Text(statusText)
                .font(.footnote.weight(.medium))
                .foregroundStyle(textColor)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Capsule().fill(theme.ink.opacity(0.05)))
        .onAppear { updatePulse() }
        .onChange(of: animatePulse) { _ in updatePulse() }
        .accessibilityLabel(a11yLabel)
    }

    private func updatePulse() {
        if animatePulse {
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                pulse = true
            }
        } else {
            withAnimation(.easeInOut(duration: 0.2)) {
                pulse = false
            }
        }
    }
}

#Preview {
    VStack(spacing: 16) {
        LiveChip(isWriting: true)
        LiveChip(isWriting: false)
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
