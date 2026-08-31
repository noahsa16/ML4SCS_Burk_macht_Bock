/// When the page's line tears.
///
/// Only a `.lift` at the end of the page counts, and only with ink before it:
/// a `.resting` gap is the thinking pause the three-state line exists to draw
/// as continuous, and a session that opens with a pause tears nothing.
enum FocusPageTear {
    static func occurred(previousLastKind: FocusSegmentKind?,
                         segments: [FocusSegment]) -> Bool {
        guard previousLastKind != .lift,
              segments.count >= 2,
              segments.last?.kind == .lift else { return false }
        return segments[segments.count - 2].kind == .ink
    }
}
