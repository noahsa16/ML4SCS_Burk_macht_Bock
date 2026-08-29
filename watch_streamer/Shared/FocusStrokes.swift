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
    /// Up to this, the pen merely rests. Also the bound past which a gap's
    /// drawn width is compressed — one threshold, two effects.
    public static let restingGapMs: Int64 = 15_000
    /// Past this, the page starts a new line.
    public static let paragraphGapMs: Int64 = 60_000

    public static func segments(from decisions: [PassiveDecision]) -> [FocusSegment] {
        guard !decisions.isEmpty else { return [] }

        let sorted = decisions.sorted { $0.startMs < $1.startMs }

        // Extract ink (writing) segments by combining consecutive writing decisions
        var inkSegments: [FocusSegment] = []
        var currentInkStart: Int64? = nil
        var currentInkEnd: Int64? = nil

        for d in sorted {
            if d.writing {
                if currentInkStart == nil {
                    currentInkStart = d.startMs
                }
                currentInkEnd = d.endMs
            } else {
                if let start = currentInkStart, let end = currentInkEnd {
                    inkSegments.append(FocusSegment(kind: .ink, startMs: start, endMs: end))
                    currentInkStart = nil
                    currentInkEnd = nil
                }
            }
        }
        if let start = currentInkStart, let end = currentInkEnd {
            inkSegments.append(FocusSegment(kind: .ink, startMs: start, endMs: end))
        }

        // Fill in gaps between writing segments and classify them
        var result: [FocusSegment] = []
        for (i, ink) in inkSegments.enumerated() {
            result.append(ink)

            if i < inkSegments.count - 1 {
                let nextInk = inkSegments[i + 1]
                let gapStart = ink.endMs
                let gapEnd = nextInk.startMs
                let gapSpan = gapEnd - gapStart
                let gapKind: FocusSegmentKind =
                    gapSpan > paragraphGapMs ? .paragraph
                    : gapSpan > restingGapMs ? .lift
                    : .resting
                result.append(FocusSegment(kind: gapKind, startMs: gapStart, endMs: gapEnd))
            }
        }

        return result
    }
}
