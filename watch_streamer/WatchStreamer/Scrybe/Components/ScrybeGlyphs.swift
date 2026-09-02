import SwiftUI
import UIKit

/// The app's own tab and marker symbols.
///
/// Why not SF Symbols: the rest of Scrybe is ink on paper, and the tab bar was
/// the one surface where that stopped. Why not the bestiary creatures: a
/// creature is the reward of a finished session, and a navigation icon is not
/// a reward.
enum ScrybeGlyph: CaseIterable {
    /// A filled day: one closed stroke.
    case today
    /// A rising line of three marks.
    case trends
    /// A quill nib.
    case focus
    /// A profile in one stroke.
    case profile
    /// The streak marker that replaces `flame.fill`.
    case streak
}

/// Draws a glyph into whatever box it is given, normalised so the same path
/// works at tab size and inline in a sentence.
struct ScrybeGlyphShape: Shape {
    let glyph: ScrybeGlyph

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let x = rect.minX + (rect.width - s) / 2
        let y = rect.minY + (rect.height - s) / 2
        func p(_ fx: CGFloat, _ fy: CGFloat) -> CGPoint {
            CGPoint(x: x + fx * s, y: y + fy * s)
        }

        var path = Path()
        switch glyph {
        case .today:
            path.addEllipse(in: CGRect(x: x + 0.12 * s, y: y + 0.12 * s,
                                       width: 0.76 * s, height: 0.76 * s))
        case .trends:
            path.move(to: p(0.12, 0.78))
            path.addLine(to: p(0.38, 0.52))
            path.addLine(to: p(0.60, 0.66))
            path.addLine(to: p(0.88, 0.24))
        case .focus:
            path.move(to: p(0.30, 0.16))
            path.addLine(to: p(0.62, 0.16))
            path.addLine(to: p(0.52, 0.74))
            path.addLine(to: p(0.46, 0.88))
            path.addLine(to: p(0.40, 0.74))
            path.closeSubpath()
        case .profile:
            path.addEllipse(in: CGRect(x: x + 0.32 * s, y: y + 0.14 * s,
                                       width: 0.36 * s, height: 0.36 * s))
            path.move(to: p(0.16, 0.88))
            path.addQuadCurve(to: p(0.84, 0.88), control: p(0.50, 0.50))
        case .streak:
            path.move(to: p(0.50, 0.10))
            path.addQuadCurve(to: p(0.74, 0.62), control: p(0.78, 0.30))
            path.addQuadCurve(to: p(0.26, 0.62), control: p(0.50, 0.92))
            path.addQuadCurve(to: p(0.50, 0.10), control: p(0.22, 0.30))
        }
        return path
    }
}

extension ScrybeGlyph {
    /// A `Label`-compatible icon at tab-bar weight.
    ///
    /// Why rasterised and not the `Shape` itself: `tabItem` renders only `Text`
    /// and `Image` and silently drops any other view, which leaves the bar with
    /// labels and no icons at all. `.template` keeps the bar's own tint.
    @MainActor
    var image: Image {
        let renderer = ImageRenderer(content:
            ScrybeGlyphShape(glyph: self)
                .stroke(style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                .frame(width: 24, height: 24))
        renderer.scale = UIScreen.main.scale
        guard let rendered = renderer.uiImage else { return Image(systemName: "circle") }
        return Image(uiImage: rendered.withRenderingMode(.alwaysTemplate))
    }

    /// The same drawing as pixels, so a test can prove it is not blank.
    @MainActor
    static func renderedPixels(_ glyph: ScrybeGlyph, side: CGFloat = 24) -> UIImage? {
        let renderer = ImageRenderer(content:
            ScrybeGlyphShape(glyph: glyph)
                .stroke(style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                .foregroundStyle(.black)
                .frame(width: side, height: side))
        renderer.scale = 1
        return renderer.uiImage
    }
}
