import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus strokes")
struct FocusStrokesTests {

    private func decision(_ offset: Int64, writing: Bool) -> PassiveDecision {
        PassiveDecision(startMs: offset, endMs: offset + 5_000,
                        logit: writing ? 2 : -2, writing: writing,
                        creditSeconds: 2.5)
    }

    // A ten-second look at the page is not an interruption; the stroke has to
    // survive it, or the page claims something the writer did not do.
    @Test("a short pause rests the pen instead of lifting it")
    func shortPauseRests() {
        let d = [decision(0, writing: true),
                 decision(10_000, writing: false),
                 decision(20_000, writing: true)]
        let kinds = FocusStrokes.segments(from: d).map(\.kind)
        #expect(kinds == [.ink, .resting, .ink])
    }

    @Test("a longer gap lifts the pen")
    func mediumGapLifts() {
        let d = [decision(0, writing: true),
                 decision(30_000, writing: false),
                 decision(40_000, writing: true)]
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .lift, .ink])
    }

    @Test("a gap past a minute starts a new paragraph")
    func longGapBreaksParagraph() {
        let d = [decision(0, writing: true),
                 decision(90_000, writing: false),
                 decision(100_000, writing: true)]
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .paragraph, .ink])
    }

    @Test("all-idle list emits a single idle segment")
    func allIdleEmitsSegment() {
        let d = [decision(0, writing: false),
                 decision(5_000, writing: false)]
        let segments = FocusStrokes.segments(from: d)
        #expect(segments.count == 1)
        #expect(segments[0].kind == .resting)
        #expect(segments[0].startMs == 0)
        #expect(segments[0].endMs == 10_000)
    }

    @Test("leading idle before first ink is classified")
    func leadingIdleClassified() {
        let d = [decision(0, writing: false),
                 decision(10_000, writing: true)]
        let kinds = FocusStrokes.segments(from: d).map(\.kind)
        #expect(kinds == [.resting, .ink])
    }

    @Test("trailing idle after last ink is classified")
    func trailingIdleClassified() {
        let d = [decision(0, writing: true),
                 decision(10_000, writing: false)]
        let kinds = FocusStrokes.segments(from: d).map(\.kind)
        #expect(kinds == [.ink, .resting])
    }

    @Test("gap of exactly 60 seconds is lift, not paragraph")
    func exactParagraphBoundary() {
        let d = [decision(0, writing: true),
                 decision(10_000, writing: false),
                 decision(65_000, writing: true)]
        let kinds = FocusStrokes.segments(from: d).map(\.kind)
        // Gap from 5000 to 65000 is 60000, which is not > 60000, so lift
        #expect(kinds == [.ink, .lift, .ink])

        let d2 = [decision(0, writing: true),
                  decision(10_000, writing: false),
                  decision(70_000, writing: true)]
        let kinds2 = FocusStrokes.segments(from: d2).map(\.kind)
        // Gap from 5000 to 70000 is 65000, which is > 60000, so paragraph
        #expect(kinds2 == [.ink, .paragraph, .ink])
    }
}
