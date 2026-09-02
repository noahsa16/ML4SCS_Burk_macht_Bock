import Foundation

/// What one span of a session's page shows.
public nonisolated enum FocusSegmentKind: Equatable {
    /// Writing was detected: full ink.
    case ink
    /// A pause short enough that the pen is still on the page.
    case resting
    /// The pen came off the page.
    case lift
    /// Long enough that the page starts a new line.
    case paragraph
}

public nonisolated struct FocusSegment: Equatable {
    public let kind: FocusSegmentKind
    public let startMs: Int64
    public let endMs: Int64
}

/// Turns the session's decisions into what the page draws.
///
/// Why three kinds and not two: writing consists of writing *and* thinking. A
/// two-state line tore on every ten-second look at the page and claimed an
/// interruption the writer had not made.
public nonisolated enum FocusStrokes {
    /// Up to this much idle, the pen merely rests. Also the bound past which a
    /// gap's drawn width is compressed — one threshold, two effects.
    public static let restingGapMs: Int64 = 15_000
    /// Past this, the page starts a new line.
    public static let paragraphGapMs: Int64 = 60_000

    /// Which kind of pause `idleMs` of credited idle time is.
    ///
    /// Extracted because the same three-way split classifies four different
    /// gaps below, and thresholds that must never drift apart may not be
    /// written out four times.
    private static func classify(idleMs: Int64) -> FocusSegmentKind {
        if idleMs > paragraphGapMs { return .paragraph }
        if idleMs > restingGapMs { return .lift }
        return .resting
    }

    /// A decision's own contribution to the pause, in milliseconds.
    ///
    /// Why `creditSeconds` and not `endMs - startMs`: windows overlap — five
    /// seconds of signal every 2.5 s — so their spans sum to twice the wall
    /// time they cover. The wall-clock hole between two ink runs is one
    /// stride shorter than the idle actually credited across it, which put
    /// the 15 s boundary at roughly 17.5 s of real pause.
    private static func creditedMs(_ decision: PassiveDecision) -> Int64 {
        Int64((decision.creditSeconds * 1000).rounded())
    }

    public static func segments(from decisions: [PassiveDecision]) -> [FocusSegment] {
        guard !decisions.isEmpty else { return [] }

        let sorted = decisions.sorted { $0.startMs < $1.startMs }

        // Ink runs, plus the idle credited immediately before each of them.
        // Whatever idle is still pending when the list ends is the trailing
        // pause — and, if no ink was found at all, the whole session's.
        var inkSegments: [FocusSegment] = []
        var idleBeforeInk: [Int64] = []
        var pendingIdleMs: Int64 = 0
        var currentInkStart: Int64?
        var currentInkEnd: Int64?

        for d in sorted {
            guard d.writing else {
                if let start = currentInkStart, let end = currentInkEnd {
                    inkSegments.append(FocusSegment(kind: .ink, startMs: start, endMs: end))
                    currentInkStart = nil
                    currentInkEnd = nil
                }
                pendingIdleMs += creditedMs(d)
                continue
            }
            if currentInkStart == nil {
                currentInkStart = d.startMs
                idleBeforeInk.append(pendingIdleMs)
                pendingIdleMs = 0
            }
            currentInkEnd = d.endMs
        }
        if let start = currentInkStart, let end = currentInkEnd {
            inkSegments.append(FocusSegment(kind: .ink, startMs: start, endMs: end))
        }

        let firstStart = sorted[0].startMs
        let lastEnd = sorted[sorted.count - 1].endMs

        guard let firstInk = inkSegments.first, let lastInk = inkSegments.last else {
            return [FocusSegment(kind: classify(idleMs: pendingIdleMs),
                                 startMs: firstStart, endMs: lastEnd)]
        }

        var result: [FocusSegment] = []

        if firstStart < firstInk.startMs {
            result.append(FocusSegment(kind: classify(idleMs: idleBeforeInk[0]),
                                       startMs: firstStart, endMs: firstInk.startMs))
        }

        for (i, ink) in inkSegments.enumerated() {
            result.append(ink)
            guard i < inkSegments.count - 1 else { continue }
            result.append(FocusSegment(kind: classify(idleMs: idleBeforeInk[i + 1]),
                                       startMs: ink.endMs,
                                       endMs: inkSegments[i + 1].startMs))
        }

        if lastInk.endMs < lastEnd {
            result.append(FocusSegment(kind: classify(idleMs: pendingIdleMs),
                                       startMs: lastInk.endMs, endMs: lastEnd))
        }

        return result
    }
}
