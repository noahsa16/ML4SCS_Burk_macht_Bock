import SwiftUI

/// A few ruled lines on nothing: the same motif the focus tab shows at full
/// size, here small and without a creature. An empty state should look like
/// the page before anyone wrote on it, not like a missing list.
struct EmptyPageVignette: View {
    var side: CGFloat = 64

    @Environment(\.scrybe) private var theme

    var body: some View {
        Canvas { context, size in
            let rows = 4
            let gap = size.height / CGFloat(rows + 1)
            for row in 1...rows {
                var line = Path()
                let y = gap * CGFloat(row)
                line.move(to: CGPoint(x: size.width * 0.12, y: y))
                line.addLine(to: CGPoint(x: size.width * 0.88, y: y))
                context.stroke(line, with: .color(theme.track), lineWidth: 1)
            }
        }
        .frame(width: side, height: side)
        // Decorative: the sentence below already says what is empty, and a
        // mark that announces itself only adds noise.
        .accessibilityHidden(true)
    }
}
