import Testing
import Foundation
@testable import WatchStreamer

/// The haptic on the focus page fires on exactly one event: the line tearing.
///
/// The trailing gap grows through `.resting` before it becomes a `.lift`, so a
/// rule phrased as "the previous kind was `.ink`" would never fire at all —
/// these cases pin the transition that actually happens.
@Suite("Focus page tear")
struct FocusPageTearTests {

    private func segment(_ kind: FocusSegmentKind, _ start: Int64, _ end: Int64) -> FocusSegment {
        FocusSegment(kind: kind, startMs: start, endMs: end)
    }

    @Test("a resting gap growing into a lift tears the line")
    func restingBecomingLiftTears() {
        let segments = [segment(.ink, 0, 40_000), segment(.lift, 40_000, 56_000)]
        #expect(FocusPageTear.occurred(previousLastKind: .resting, segments: segments))
    }

    // The pause the three-state line exists to draw as continuous. A haptic
    // here would buzz at every reading pause.
    @Test("a resting gap alone does not tear")
    func restingDoesNotTear() {
        let segments = [segment(.ink, 0, 40_000), segment(.resting, 40_000, 48_000)]
        #expect(!FocusPageTear.occurred(previousLastKind: .ink, segments: segments))
    }

    // Growing lifts must not re-fire: the gap keeps extending for as long as
    // the pen is off the page, and only its first moment is the tear.
    @Test("a lift that keeps growing tears only once")
    func liftFiresOnlyOnce() {
        let segments = [segment(.ink, 0, 40_000), segment(.lift, 40_000, 90_000)]
        #expect(!FocusPageTear.occurred(previousLastKind: .lift, segments: segments))
    }

    // A session that opens with a pause has no line yet, so nothing tears.
    @Test("a leading lift with no ink before it does not tear")
    func leadingLiftDoesNotTear() {
        let segments = [segment(.lift, 0, 30_000)]
        #expect(!FocusPageTear.occurred(previousLastKind: nil, segments: segments))
    }

    @Test("an empty page does not tear")
    func emptyPageDoesNotTear() {
        #expect(!FocusPageTear.occurred(previousLastKind: nil, segments: []))
    }
}
