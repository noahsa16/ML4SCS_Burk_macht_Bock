import Testing
import Foundation
@testable import WatchStreamer

// `WritingPageLayout` is the pure time -> position mapping `WritingPageView`
// draws from: gap compression above `FocusStrokes.restingGapMs`, the forced
// line break on a `.paragraph`, and wrapping a run across lines. None of it
// touches SwiftUI, so it is tested directly rather than through the Canvas
// that consumes it.
@Suite("Writing page layout")
struct WritingPageLayoutTests {

    // MARK: - drawnSeconds: gap compression above 15 s

    @Test("a lift's drawn width is linear up to the resting bound")
    func liftLinearUpToBound() {
        let lift = FocusSegment(kind: .lift, startMs: 0, endMs: 15_000)
        #expect(WritingPageLayout.drawnSeconds(lift) == 15.0)
    }

    @Test("past the resting bound a lift's drawn width compresses logarithmically")
    func liftCompressesLogarithmically() {
        let shortExcess = FocusSegment(kind: .lift, startMs: 0, endMs: 20_000)  // 5 s excess
        let longExcess = FocusSegment(kind: .lift, startMs: 0, endMs: 60_000)   // 45 s excess
        let a = WritingPageLayout.drawnSeconds(shortExcess)
        let b = WritingPageLayout.drawnSeconds(longExcess)
        #expect(abs(a - (15 + log(6))) < 0.0001)
        #expect(abs(b - (15 + log(46))) < 0.0001)
        // Nine times the excess (5 s -> 45 s) must not come close to nine
        // times the drawn width past the bound -- that is what "logarithmic"
        // has to mean here, not just "somewhat less than linear".
        let excessDrawnAtShort = a - 15
        let excessDrawnAtLong = b - 15
        #expect(excessDrawnAtLong < excessDrawnAtShort * 9)
        // And it must still stay well under the uncompressed 45 s.
        #expect(excessDrawnAtLong < 45 * 0.5)
    }

    @Test("ink and resting spans draw at wall-clock speed, uncompressed")
    func inkAndRestingAreLinear() {
        let ink = FocusSegment(kind: .ink, startMs: 0, endMs: 90_000)       // past 15 s too
        let resting = FocusSegment(kind: .resting, startMs: 0, endMs: 10_000)
        #expect(WritingPageLayout.drawnSeconds(ink) == 90.0)
        #expect(WritingPageLayout.drawnSeconds(resting) == 10.0)
    }

    // MARK: - layout: the paragraph line break above 60 s

    @Test("a paragraph forces a new line even with room left on the current one")
    func paragraphForcesLineBreak() {
        let segments = [
            FocusSegment(kind: .ink, startMs: 0, endMs: 10_000),          // 10 s of ink
            FocusSegment(kind: .paragraph, startMs: 10_000, endMs: 70_000), // 60 s gap
            FocusSegment(kind: .ink, startMs: 70_000, endMs: 80_000),
        ]
        // A 120 s line has 110 s of room left after 10 s of ink -- the
        // paragraph must break anyway; that is the whole point of the third
        // tier being a break rather than just a wider gap.
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        #expect(page.paragraphMarks == [.init(line: 1, durationMs: 60_000)])
        #expect(page.runs.count == 2)
        #expect(page.runs[0].line == 0)
        #expect(page.runs[1].line == 1)
        #expect(page.runs[1].startOffset == 0)
        #expect(page.lineCount == 2)
    }

    @Test("a paragraph exactly at a line boundary does not insert a blank line")
    func paragraphAtBoundaryDoesNotInsertBlankLine() {
        let segments = [
            FocusSegment(kind: .ink, startMs: 0, endMs: 120_000),        // fills line 0 exactly
            FocusSegment(kind: .paragraph, startMs: 120_000, endMs: 180_000),
            FocusSegment(kind: .ink, startMs: 180_000, endMs: 190_000),
        ]
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        #expect(page.paragraphMarks == [.init(line: 1, durationMs: 60_000)])
        #expect(page.runs.last?.line == 1)
    }

    // MARK: - layout: wrapping onto the next line

    @Test("a long ink run wraps onto as many lines as it needs")
    func longRunWrapsAcrossLines() {
        let segment = FocusSegment(kind: .ink, startMs: 0, endMs: 300_000) // 300 s
        let page = WritingPageLayout.layout([segment], secondsPerLine: 120)
        #expect(page.runs.count == 3)
        #expect(page.runs[0] == .init(kind: .ink, line: 0, startOffset: 0, endOffset: 120,
                                      isSegmentStart: true, isSegmentEnd: false,
                                      precedingKind: nil, followingKind: nil))
        #expect(page.runs[1] == .init(kind: .ink, line: 1, startOffset: 0, endOffset: 120,
                                      isSegmentStart: false, isSegmentEnd: false,
                                      precedingKind: nil, followingKind: nil))
        #expect(page.runs[2] == .init(kind: .ink, line: 2, startOffset: 0, endOffset: 60,
                                      isSegmentStart: false, isSegmentEnd: true,
                                      precedingKind: nil, followingKind: nil))
        #expect(page.lineCount == 3)
    }

    @Test("a run that starts mid-line wraps at exactly the remaining width")
    func midLineWrapUsesRemainingWidth() {
        let segments = [
            FocusSegment(kind: .ink, startMs: 0, endMs: 100_000),        // fills to 100 s
            FocusSegment(kind: .ink, startMs: 100_000, endMs: 250_000),  // +150 s -> wraps twice
        ]
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        #expect(page.runs.count == 4)
        #expect(page.runs[0].line == 0 && page.runs[0].startOffset == 0 && page.runs[0].endOffset == 100)
        #expect(page.runs[1].line == 0 && page.runs[1].startOffset == 100 && page.runs[1].endOffset == 120)
        #expect(page.runs[2].line == 1 && page.runs[2].startOffset == 0 && page.runs[2].endOffset == 120)
        #expect(page.runs[3].line == 2 && page.runs[3].startOffset == 0 && page.runs[3].endOffset == 10)
        #expect(page.lineCount == 3)
    }

    // MARK: - edges

    @Test("no segments produce an empty single-line page")
    func emptyIsSingleLinePage() {
        let page = WritingPageLayout.layout([], secondsPerLine: 120)
        #expect(page.runs.isEmpty)
        #expect(page.paragraphMarks.isEmpty)
        #expect(page.lineCount == 1)
        #expect(page.endCursor == 0)
    }

    @Test("endCursor tracks where the next segment would begin")
    func endCursorTracksCursor() {
        let segments = [FocusSegment(kind: .ink, startMs: 0, endMs: 45_000)]
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        #expect(page.endCursor == 45.0)
    }

    @Test("point(atDrawnSeconds:) wraps at exact multiples of the line length")
    func pointWrapsAtLineBoundary() {
        let onLine1Start = WritingPageLayout.point(atDrawnSeconds: 120, secondsPerLine: 120)
        #expect(onLine1Start.line == 1)
        #expect(onLine1Start.offset == 0)

        let midLine0 = WritingPageLayout.point(atDrawnSeconds: 45, secondsPerLine: 120)
        #expect(midLine0.line == 0)
        #expect(midLine0.offset == 45)
    }

    // MARK: - Run neighbours: what the taper needs to suppress itself

    // A resting gap must read as the stroke running through, never a break —
    // so the taper that fires at a genuine segment boundary has to know when
    // its neighbour is `.resting` and stay off. These tests guard the data
    // the drawing layer reads to make that call; the drawing itself is not
    // exercised here.
    @Test("a run's neighbours are recorded so the taper can suppress itself before a resting pause")
    func neighborKindsAreRecorded() {
        let segments = [
            FocusSegment(kind: .resting, startMs: 0, endMs: 5_000),
            FocusSegment(kind: .ink, startMs: 5_000, endMs: 15_000),
            FocusSegment(kind: .resting, startMs: 15_000, endMs: 20_000),
        ]
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        let ink = page.runs.first(where: { $0.kind == .ink })
        #expect(ink?.precedingKind == .resting)
        #expect(ink?.followingKind == .resting)
    }

    @Test("a genuine lift or paragraph neighbour is recorded distinctly from a resting one")
    func nonRestingNeighborsAreRecorded() {
        let segments = [
            FocusSegment(kind: .lift, startMs: 0, endMs: 20_000),
            FocusSegment(kind: .ink, startMs: 20_000, endMs: 30_000),
            FocusSegment(kind: .paragraph, startMs: 30_000, endMs: 95_000),
        ]
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        let ink = page.runs.first(where: { $0.kind == .ink })
        #expect(ink?.precedingKind == .lift)
        #expect(ink?.followingKind == .paragraph)
    }

    @Test("a run at the very start or end of the segment list has no neighbour on that side")
    func edgeRunsHaveNoOutsideNeighbor() {
        let segments = [
            FocusSegment(kind: .ink, startMs: 0, endMs: 10_000),
            FocusSegment(kind: .resting, startMs: 10_000, endMs: 15_000),
            FocusSegment(kind: .ink, startMs: 15_000, endMs: 25_000),
        ]
        let page = WritingPageLayout.layout(segments, secondsPerLine: 120)
        let inkRuns = page.runs.filter { $0.kind == .ink }
        #expect(inkRuns.first?.precedingKind == nil)   // nothing before the session started
        #expect(inkRuns.last?.followingKind == nil)    // nothing after the session ends yet
    }

    @Test("a wrapped mid-line piece carries no neighbour kind -- only the true start/end do")
    func midWrapRunsHaveNoNeighborKind() {
        let segment = FocusSegment(kind: .ink, startMs: 0, endMs: 300_000)
        let page = WritingPageLayout.layout([segment], secondsPerLine: 120)
        #expect(page.runs.count == 3)
        #expect(page.runs[1].precedingKind == nil)
        #expect(page.runs[1].followingKind == nil)
    }
}
