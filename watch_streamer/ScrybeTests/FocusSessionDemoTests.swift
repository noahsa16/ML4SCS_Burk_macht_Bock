import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus session demo script")
struct FocusSessionDemoTests {

    @Test("the script opens writing, pauses, and wraps around")
    func pattern() {
        #expect(FocusSessionDemo.isWriting(atSessionSeconds: 0))
        #expect(FocusSessionDemo.isWriting(atSessionSeconds: 57.9))
        #expect(!FocusSessionDemo.isWriting(atSessionSeconds: 60))
        #expect(FocusSessionDemo.isWriting(atSessionSeconds: 70))
        let cycle = FocusSessionDemo.cycleSeconds
        #expect(FocusSessionDemo.isWriting(atSessionSeconds: cycle + 1))
        #expect(!FocusSessionDemo.isWriting(atSessionSeconds: cycle - 1))
    }

    // Every tier the page draws has to appear, or the video never shows it.
    @Test("the pauses cover the resting, lift and paragraph tiers")
    func pauseTiers() {
        let pauses = FocusSessionDemo.script.filter { !$0.writing }.map(\.seconds)
        let resting = Double(FocusStrokes.restingGapMs) / 1000
        let paragraph = Double(FocusStrokes.paragraphGapMs) / 1000
        // Computed outside the macro: a closure reads as throwing inside
        // #expect's expansion.
        let hasResting = pauses.contains { $0 < resting }
        let hasLift = pauses.contains { $0 >= resting && $0 < paragraph }
        let hasParagraph = pauses.contains { $0 >= paragraph }
        #expect(hasResting)
        #expect(hasLift)
        #expect(hasParagraph)
    }

    @Test("windows fall on the stride and are stamped from the session start")
    func windows() {
        let start = Date(timeIntervalSince1970: 1_700_000_000)
        let first = FocusSessionDemo.decisions(from: 0, to: 10, sessionStart: start)
        #expect(first.map(\.startMs) == [0, 2_500, 5_000, 7_500].map { 1_700_000_000_000 + $0 })
        let spans = Set(first.map { $0.endMs - $0.startMs })
        let credits = Set(first.map(\.creditSeconds))
        let verdicts = Set(first.map(\.writing))
        #expect(spans == [5_000])
        #expect(credits == [2.5])
        #expect(verdicts == [true])
    }

    // A tick of any length continues exactly where the last one stopped.
    @Test("touching spans neither repeat nor skip a window")
    func contiguity() {
        let start = Date(timeIntervalSince1970: 1_700_000_000)
        let whole = FocusSessionDemo.decisions(from: 0, to: 200, sessionStart: start)
        let pieces = FocusSessionDemo.decisions(from: 0, to: 7, sessionStart: start)
            + FocusSessionDemo.decisions(from: 7, to: 61.3, sessionStart: start)
            + FocusSessionDemo.decisions(from: 61.3, to: 200, sessionStart: start)
        #expect(whole == pieces)
        #expect(whole.count == 80)
    }
}
