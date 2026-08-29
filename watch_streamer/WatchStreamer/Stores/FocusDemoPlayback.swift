import Foundation

/// Ephemeral decisions used only to stage the product UI in the admin demo.
/// Nothing here is written to `PassiveDecisionStore` or uploaded.
struct FocusDemoPlayback {
    private(set) var decisions: [PassiveDecision]
    private(set) var isWriting = true
    private(set) var tickIndex = 0
    let secondsPerTick: Double

    init(startingSeconds: Double, secondsPerTick: Double, now: Date = Date()) {
        self.secondsPerTick = max(1, secondsPerTick)
        decisions = Self.seed(seconds: max(0, startingSeconds), endingAt: now)
    }

    /// Eight seconds of visible writing followed by a four-second pause makes
    /// both the active treatment and new-session behavior legible on video.
    mutating func advance(at now: Date = Date()) {
        isWriting = tickIndex % 12 < 8
        tickIndex += 1
        guard isWriting else { return }

        let startMs = Int64(now.timeIntervalSince1970 * 1_000)
        let pulse = Float(1.8 + 0.7 * sin(Double(tickIndex) * 0.8))
        decisions.append(PassiveDecision(
            startMs: startMs,
            endMs: startMs + 1_000,
            logit: pulse,
            writing: true,
            creditSeconds: secondsPerTick
        ))
    }

    private static func seed(seconds: Double, endingAt now: Date) -> [PassiveDecision] {
        guard seconds > 0 else { return [] }
        let stride = 2.5
        // Twenty-four points fill the existing sparkline without allocating
        // thousands of fake model windows for a multi-hour starting value.
        let count = 24
        let credit = seconds / Double(count)
        let lastStart = now.addingTimeInterval(-5).timeIntervalSince1970
        let firstStart = lastStart - Double(count - 1) * stride

        return (0..<count).map { index in
            let start = firstStart + Double(index) * stride
            let startMs = Int64(start * 1_000)
            let logit = Float(1.6 + 0.8 * sin(Double(index) * 0.45))
            return PassiveDecision(
                startMs: startMs,
                endMs: startMs + 5_000,
                logit: logit,
                writing: true,
                creditSeconds: credit
            )
        }
    }
}
