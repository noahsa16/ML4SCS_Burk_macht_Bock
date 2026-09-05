import CoreGraphics

/// How thick a creature's stroke is drawn, shared by `CreatureCanvas` and
/// `tools/render_marginalia.swift` so the picture that gets approved on the
/// Mac is the one the app draws.
enum CreaturePen {
    /// Thinnest line worth drawing, in points on screen. Below this a
    /// hairline of hatching disappears into the paper, so it is widened
    /// rather than lost — the small cells of the gallery are where this
    /// bites, not the medallion of a running session.
    static let minimumPoints: CGFloat = 0.55

    /// Line width in the creature's 100-unit box for a stroke of measured
    /// `width` when the box is drawn `side` points wide.
    static func lineWidth(_ width: CGFloat, side: CGFloat) -> CGFloat {
        guard side > 0 else { return width }
        return max(width, minimumPoints * 100 / side)
    }

    /// Ink tone for a stroke: a hairline is drawn a shade lighter than a
    /// contour, the way a pen under less pressure leaves less ink.
    static func opacity(_ width: CGFloat, reference: CGFloat) -> Double {
        guard reference > 0 else { return 1 }
        return Double(min(1, 0.62 + 0.38 * min(1, width / reference)))
    }
}
