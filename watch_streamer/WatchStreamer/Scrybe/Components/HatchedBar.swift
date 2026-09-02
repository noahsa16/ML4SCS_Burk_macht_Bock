import SwiftUI

/// Diagonal pen hatching, the way a manuscript shades an area: parallel
/// strokes at 45°, clipped by whoever uses it. One drawing so every bar,
/// meter and swatch in the app is hatched at the same angle and density.
struct HatchPattern: View {
    var color: Color
    var spacing: CGFloat = 5
    var lineWidth: CGFloat = 1

    var body: some View {
        Canvas { context, size in
            var path = Path()
            // Run the strokes from beyond the left edge to beyond the right,
            // so a clip of any aspect ratio is covered corner to corner.
            let span = size.width + size.height
            var x = -size.height
            while x < span {
                path.move(to: CGPoint(x: x, y: size.height))
                path.addLine(to: CGPoint(x: x + size.height, y: 0))
                x += spacing
            }
            context.stroke(path, with: .color(color), lineWidth: lineWidth)
        }
        .accessibilityHidden(true)
    }
}

/// A rectangle rounded only at the top: the profile of a bar that stands on
/// a baseline. `UnevenRoundedRectangle` would do the same from iOS 16.4, and
/// the app deploys to 16.0.
struct TopRoundedRectangle: Shape {
    var radius: CGFloat

    func path(in rect: CGRect) -> Path {
        let r = min(radius, rect.width / 2, rect.height)
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + r))
        path.addQuadCurve(to: CGPoint(x: rect.minX + r, y: rect.minY),
                          control: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - r, y: rect.minY))
        path.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.minY + r),
                          control: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

/// One hatched bar on a baseline. The bar's height is the caller's; this
/// only decides how it is drawn: hatched in the muted tone, hatched and
/// outlined in the accent when highlighted, a flat stub when empty.
struct HatchedBar: View {
    var height: CGFloat
    var highlighted = false
    /// Whether the bar carries any value. An empty day still draws a stub so
    /// the baseline reads as continuous, but a stub is not hatched.
    var isEmpty = false
    var cornerRadius: CGFloat = 6

    @Environment(\.scrybe) private var theme

    private var tone: Color { highlighted ? theme.accent : theme.secondaryInk }

    var body: some View {
        let shape = TopRoundedRectangle(radius: cornerRadius)
        ZStack {
            if isEmpty {
                shape.fill(theme.track)
            } else {
                HatchPattern(color: tone.opacity(highlighted ? 0.9 : 0.55))
                    .clipShape(shape)
                shape.stroke(tone.opacity(highlighted ? 1 : 0.7), lineWidth: 1)
            }
        }
        .frame(height: height)
    }
}

/// A horizontal hatched meter: the filled part hatched in the accent, the
/// remainder a hairline track. Used where the reference design shows how far
/// a creature is drawn.
struct HatchedMeter: View {
    var fraction: Double
    var height: CGFloat = 8

    @Environment(\.scrybe) private var theme

    private var clamped: Double { max(0, min(1, fraction)) }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(theme.track)
                HatchPattern(color: theme.accent, spacing: 4, lineWidth: 1.2)
                    .frame(width: max(0, geo.size.width * clamped))
                    .clipShape(Capsule())
            }
        }
        .frame(height: height)
        .accessibilityHidden(true)
    }
}

#Preview {
    VStack(spacing: 32) {
        HStack(alignment: .bottom, spacing: 12) {
            HatchedBar(height: 20)
            HatchedBar(height: 60)
            HatchedBar(height: 4, isEmpty: true)
            HatchedBar(height: 90, highlighted: true)
        }
        .frame(width: 200)
        HatchedMeter(fraction: 0.45).frame(width: 240)
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
