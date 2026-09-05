import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus session spans")
struct FocusSessionSpansTests {

    @Test("touching spans merge into one")
    func touchingSpansMerge() {
        var spans = FocusSessionSpans()
        spans.extend(startMs: 0, endMs: 5_000)
        spans.extend(startMs: 2_500, endMs: 7_500)
        spans.extend(startMs: 7_500, endMs: 12_500)
        #expect(spans.spans == [.init(startMs: 0, endMs: 12_500)])
    }

    @Test("separate sessions stay separate and sorted")
    func separateSpansStay() {
        var spans = FocusSessionSpans()
        spans.extend(startMs: 60_000, endMs: 65_000)
        spans.extend(startMs: 0, endMs: 5_000)
        #expect(spans.spans.map(\.startMs) == [0, 60_000])
    }

    @Test("only a window wholly inside a span is covered")
    func coverageIsWhole() {
        var spans = FocusSessionSpans()
        spans.extend(startMs: 10_000, endMs: 20_000)
        #expect(spans.covers(startMs: 12_000, endMs: 17_000))
        #expect(spans.covers(startMs: 10_000, endMs: 20_000))
        #expect(!spans.covers(startMs: 8_000, endMs: 13_000))
        #expect(!spans.covers(startMs: 17_000, endMs: 22_000))
    }

    @Test("pruning drops spans that ended before the cutoff")
    func pruneDropsOldSpans() {
        var spans = FocusSessionSpans()
        spans.extend(startMs: 0, endMs: 5_000)
        spans.extend(startMs: 100_000, endMs: 105_000)
        spans.prune(before: 50_000)
        #expect(spans.spans == [.init(startMs: 100_000, endMs: 105_000)])
    }

    @Test("an empty or inverted window is ignored")
    func degenerateWindowIgnored() {
        var spans = FocusSessionSpans()
        spans.extend(startMs: 5_000, endMs: 5_000)
        spans.extend(startMs: 9_000, endMs: 4_000)
        #expect(spans.spans.isEmpty)
    }
}
