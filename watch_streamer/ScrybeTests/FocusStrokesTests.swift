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
}
