import Foundation

/// Wall-clock spans a focus session has already classified.
///
/// A focus session credits the day as its windows arrive (the phone runs the
/// model live), while the Watch's recorder classifies the same minutes again
/// a few minutes to hours later. The two paths never share a window
/// `startMs`, so the store's idempotency cannot catch the repeat — this
/// ledger does: a recorder window that falls inside a span the session
/// already judged is dropped, writing or not. The session's verdict stands for
/// its own minutes; the recorder's stands for the rest of the day.
///
/// Spans are extended window by window rather than opened at start and closed
/// at end, so a session the system kills mid-way leaves a ledger that covers
/// exactly the minutes it credited and nothing after.
nonisolated struct FocusSessionSpans: Codable, Equatable, Sendable {
    struct Span: Codable, Equatable, Sendable {
        var startMs: Int64
        var endMs: Int64
    }

    private(set) var spans: [Span] = []

    init() {}

    /// Adds `[startMs, endMs]`, merging it into any span it touches.
    mutating func extend(startMs: Int64, endMs: Int64) {
        guard endMs > startMs else { return }
        var merged = Span(startMs: startMs, endMs: endMs)
        var kept: [Span] = []
        for span in spans {
            if span.endMs < merged.startMs || span.startMs > merged.endMs {
                kept.append(span)
            } else {
                merged.startMs = min(merged.startMs, span.startMs)
                merged.endMs = max(merged.endMs, span.endMs)
            }
        }
        kept.append(merged)
        spans = kept.sorted { $0.startMs < $1.startMs }
    }

    /// Whether the window `[startMs, endMs]` lies inside a recorded span. A
    /// window that merely brushes a span's edge is not covered — the session
    /// did not judge those samples.
    func covers(startMs: Int64, endMs: Int64) -> Bool {
        spans.contains { startMs >= $0.startMs && endMs <= $0.endMs }
    }

    /// Drops spans that ended before `cutoffMs`. Recorder windows never
    /// arrive later than the raw retention the day store keeps, so a span
    /// older than that has nothing left to shield against.
    mutating func prune(before cutoffMs: Int64) {
        spans.removeAll { $0.endMs < cutoffMs }
    }
}
