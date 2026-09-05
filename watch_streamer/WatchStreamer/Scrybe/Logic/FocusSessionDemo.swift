import Foundation

/// The writing a demo session pretends to observe, in session seconds.
///
/// Pure so the pattern can be asserted without a clock: a store advances a
/// virtual session clock and asks for the windows that fall into the span it
/// just crossed. The pauses are chosen to hit every tier the page draws — a
/// resting hairline under 15 s, a lifted pen between 15 and 60 s, and a
/// paragraph break past a minute — so a video shows the whole vocabulary of
/// the page inside a couple of minutes.
enum FocusSessionDemo {
    struct Beat: Equatable {
        let writing: Bool
        let seconds: Double
    }

    static let script: [Beat] = [
        Beat(writing: true, seconds: 58), Beat(writing: false, seconds: 9),
        Beat(writing: true, seconds: 74), Beat(writing: false, seconds: 28),
        Beat(writing: true, seconds: 96), Beat(writing: false, seconds: 75),
        Beat(writing: true, seconds: 42), Beat(writing: false, seconds: 6),
        Beat(writing: true, seconds: 130), Beat(writing: false, seconds: 22),
    ]

    static let cycleSeconds: Double = script.reduce(0) { $0 + $1.seconds }

    /// Matches the live session's builder: five-second windows every 2.5 s.
    static let strideSeconds: Double = 2.5
    static let windowSeconds: Double = 5

    static func isWriting(atSessionSeconds t: Double) -> Bool {
        var offset = t.truncatingRemainder(dividingBy: cycleSeconds)
        if offset < 0 { offset += cycleSeconds }
        for beat in script {
            if offset < beat.seconds { return beat.writing }
            offset -= beat.seconds
        }
        return false
    }

    /// The windows whose start falls in `[from, to)` session seconds, stamped
    /// onto the wall clock from `sessionStart`. Consecutive calls with
    /// touching spans never repeat or skip a window, whatever the tick size.
    static func decisions(from: Double, to: Double, sessionStart: Date) -> [PassiveDecision] {
        guard to > from else { return [] }
        let first = Int((max(0, from) / strideSeconds).rounded(.up))
        let last = Int((to / strideSeconds).rounded(.up))
        let origin = sessionStart.timeIntervalSince1970
        return (first..<last).map { index in
            let start = Double(index) * strideSeconds
            let writing = isWriting(atSessionSeconds: start)
            let startMs = Int64((origin + start) * 1000)
            return PassiveDecision(
                startMs: startMs,
                endMs: startMs + Int64(windowSeconds * 1000),
                logit: writing ? Float(1.4 + 0.7 * sin(Double(index) * 0.6)) : -1.3,
                writing: writing,
                creditSeconds: strideSeconds)
        }
    }
}
