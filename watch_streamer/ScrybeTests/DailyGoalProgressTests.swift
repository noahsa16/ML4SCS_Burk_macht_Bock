import Testing
@testable import WatchStreamer

@Suite("DailyGoalProgress")
struct DailyGoalProgressTests {
    @Test("fraction clamps 0...1", arguments: [
        (3600.0, 7200.0, 0.5), (9000.0, 7200.0, 1.0), (0.0, 7200.0, 0.0),
    ])
    func fraction(writing: Double, goal: Double, expected: Double) {
        #expect(DailyGoalProgress(writingSeconds: writing, goalSeconds: goal).fraction == expected)
    }

    @Test("percent rounds, uncapped", arguments: [
        (5256.0, 7200.0, 73), (9000.0, 7200.0, 125),
    ])
    func percent(writing: Double, goal: Double, expected: Int) {
        #expect(DailyGoalProgress(writingSeconds: writing, goalSeconds: goal).percent == expected)
    }

    @Test("isMet at/above goal; zero goal never met")
    func met() {
        #expect(DailyGoalProgress(writingSeconds: 7200, goalSeconds: 7200).isMet)
        #expect(!DailyGoalProgress(writingSeconds: 7199, goalSeconds: 7200).isMet)
        let zero = DailyGoalProgress(writingSeconds: 100, goalSeconds: 0)
        #expect(!zero.isMet)
        #expect(zero.fraction == 0.0)
    }
}
