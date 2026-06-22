import Testing
@testable import WatchStreamer

@Suite("StreakCalculator")
struct StreakCalculatorTests {
    // Helper: build N consecutive ISO dates ending at `today`, oldest first.
    private func days(_ secs: [Double], endingAt today: String) -> [DayWriting] {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = .current
        let end = fmt.date(from: today)!
        return secs.enumerated().map { i, s in
            let d = Calendar.current.date(byAdding: .day,
                        value: -(secs.count - 1 - i), to: end)!
            return DayWriting(date: fmt.string(from: d), writingSeconds: s)
        }
    }

    @Test("counts consecutive goal-met days including today")
    func includesToday() {
        let d = days([8000, 8000, 8000], endingAt: "2026-06-22")
        #expect(StreakCalculator.currentStreak(days: d, goalSeconds: 7200, todayISO: "2026-06-22") == 3)
    }

    @Test("today pending does not break a streak through yesterday")
    func todayPending() {
        let d = days([8000, 8000, 100], endingAt: "2026-06-22")  // today under goal
        #expect(StreakCalculator.currentStreak(days: d, goalSeconds: 7200, todayISO: "2026-06-22") == 2)
    }

    @Test("a missed prior day breaks the streak")
    func brokenByMiss() {
        let d = days([8000, 100, 8000], endingAt: "2026-06-22")  // yesterday missed
        #expect(StreakCalculator.currentStreak(days: d, goalSeconds: 7200, todayISO: "2026-06-22") == 1)
    }

    @Test("no data is zero")
    func empty() {
        #expect(StreakCalculator.currentStreak(days: [], goalSeconds: 7200, todayISO: "2026-06-22") == 0)
    }
}
