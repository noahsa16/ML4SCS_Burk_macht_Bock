import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus strokes")
struct FocusStrokesTests {

    /// The shape a session really produces: 5 s windows on a 2.5 s stride,
    /// each crediting the stride. Non-overlapping fixtures would certify a
    /// mapping the app never asks for — and would hide that a pause is as
    /// long as the idle credited across it, not as long as the wall-clock
    /// hole between the ink either side of it.
    private func decisions(_ pattern: [Bool]) -> [PassiveDecision] {
        pattern.enumerated().map { index, writing in
            let start = Int64(index) * 2_500
            return PassiveDecision(startMs: start, endMs: start + 5_000,
                                   logit: writing ? 2 : -2, writing: writing,
                                   creditSeconds: 2.5)
        }
    }

    /// `count` idle windows — `count * 2.5 s` of credited pause.
    private func idle(_ count: Int) -> [Bool] {
        Array(repeating: false, count: count)
    }

    // A ten-second look at the page is not an interruption; the stroke has to
    // survive it, or the page claims something the writer did not do.
    @Test("a short pause rests the pen instead of lifting it")
    func shortPauseRests() {
        let d = decisions([true] + idle(4) + [true])          // 10 s
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .resting, .ink])
    }

    @Test("a longer gap lifts the pen")
    func mediumGapLifts() {
        let d = decisions([true] + idle(8) + [true])          // 20 s
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .lift, .ink])
    }

    @Test("a gap past a minute starts a new paragraph")
    func longGapBreaksParagraph() {
        let d = decisions([true] + idle(25) + [true])         // 62.5 s
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .paragraph, .ink])
    }

    // The boundary has to fire where it says it does. Measured against the
    // wall-clock hole instead, six idle windows read as 12.5 s and the pen
    // kept resting until 17.5 s of real pause.
    @Test("the resting boundary is fifteen credited seconds, not seventeen and a half")
    func restingBoundaryIsCreditedTime() {
        let atBound = decisions([true] + idle(6) + [true])    // exactly 15 s
        #expect(FocusStrokes.segments(from: atBound).map(\.kind) == [.ink, .resting, .ink])

        let pastBound = decisions([true] + idle(7) + [true])  // 17.5 s
        #expect(FocusStrokes.segments(from: pastBound).map(\.kind) == [.ink, .lift, .ink])
    }

    @Test("the paragraph boundary is sixty credited seconds")
    func paragraphBoundaryIsCreditedTime() {
        let atBound = decisions([true] + idle(24) + [true])   // exactly 60 s
        #expect(FocusStrokes.segments(from: atBound).map(\.kind) == [.ink, .lift, .ink])

        let pastBound = decisions([true] + idle(25) + [true]) // 62.5 s
        #expect(FocusStrokes.segments(from: pastBound).map(\.kind) == [.ink, .paragraph, .ink])
    }

    // A gap is classified by credited idle, but it is still *drawn* across the
    // wall-clock hole — the page's geometry must not move with the fix.
    @Test("a gap spans the wall clock between the ink either side of it")
    func gapKeepsItsWallClockBounds() {
        let segments = FocusStrokes.segments(from: decisions([true] + idle(4) + [true]))
        #expect(segments.count == 3)
        #expect(segments[0] == FocusSegment(kind: .ink, startMs: 0, endMs: 5_000))
        #expect(segments[1] == FocusSegment(kind: .resting, startMs: 5_000, endMs: 12_500))
        #expect(segments[2] == FocusSegment(kind: .ink, startMs: 12_500, endMs: 17_500))
    }

    @Test("consecutive writing windows form one ink segment")
    func consecutiveWritingMerges() {
        let segments = FocusStrokes.segments(from: decisions([true, true, true]))
        #expect(segments == [FocusSegment(kind: .ink, startMs: 0, endMs: 10_000)])
    }

    @Test("all-idle list emits a single idle segment")
    func allIdleEmitsSegment() {
        let segments = FocusStrokes.segments(from: decisions(idle(2)))
        #expect(segments == [FocusSegment(kind: .resting, startMs: 0, endMs: 7_500)])
    }

    @Test("leading idle before first ink is classified")
    func leadingIdleClassified() {
        let short = decisions(idle(2) + [true])               // 5 s
        #expect(FocusStrokes.segments(from: short).map(\.kind) == [.resting, .ink])

        let long = decisions(idle(8) + [true])                // 20 s
        #expect(FocusStrokes.segments(from: long).map(\.kind) == [.lift, .ink])
    }

    @Test("trailing idle after last ink is classified")
    func trailingIdleClassified() {
        let short = decisions([true] + idle(2))               // 5 s
        #expect(FocusStrokes.segments(from: short).map(\.kind) == [.ink, .resting])

        let long = decisions([true] + idle(8))                // 20 s
        #expect(FocusStrokes.segments(from: long).map(\.kind) == [.ink, .lift])
    }

    @Test("an empty list draws nothing")
    func emptyIsEmpty() {
        #expect(FocusStrokes.segments(from: []).isEmpty)
    }
}
