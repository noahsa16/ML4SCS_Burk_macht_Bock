import Testing
@testable import WatchStreamer

@Suite("Focus progress preview")
struct FocusProgressTests {

    @Test func remainingCountsDownFromThirtyMinutes() {
        #expect(FocusProgress.remainingSeconds(writingSeconds: 0) == 30 * 60)
        #expect(FocusProgress.remainingSeconds(writingSeconds: 600) == 20 * 60)
    }

    /// Why the clamp: past the creature's thirty minutes the subtraction goes
    /// negative and the sentence would promise a remaining time below zero.
    @Test func remainingNeverGoesNegative() {
        #expect(FocusProgress.remainingSeconds(writingSeconds: 31 * 60) == 0)
        #expect(FocusProgress.remainingSeconds(writingSeconds: 10_000) == 0)
    }

    @Test func aLongerSessionSaysItStartsANewOne() {
        #expect(FocusProgress.exceedsCreature(remainingSeconds: 12 * 60,
                                              sessionSeconds: 25 * 60))
        #expect(!FocusProgress.exceedsCreature(remainingSeconds: 30 * 60,
                                               sessionSeconds: 15 * 60))
    }

    /// A goalless session makes no claim about finishing anything.
    @Test func noGoalMakesNoClaim() {
        #expect(!FocusProgress.exceedsCreature(remainingSeconds: 60,
                                               sessionSeconds: nil))
    }
}
