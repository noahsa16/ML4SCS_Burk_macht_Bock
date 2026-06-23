import Foundation

struct DayWriting: Sendable {
    let date: String          // "YYYY-MM-DD"
    let writingSeconds: Double
}

enum StreakCalculator {
    static func currentStreak(days: [DayWriting], goalSeconds: Double, todayISO: String) -> Int {
        guard goalSeconds > 0, !days.isEmpty else { return 0 }
        let met = Dictionary(uniqueKeysWithValues: days.map {
            ($0.date, DailyGoalProgress(writingSeconds: $0.writingSeconds, goalSeconds: goalSeconds).isMet)
        })

        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = .current
        guard let today = fmt.date(from: todayISO) else { return 0 }

        var streak = 0
        var cursor = today
        var isFirst = true
        while true {
            let iso = fmt.string(from: cursor)
            let dayMet = met[iso] ?? false
            if dayMet {
                streak += 1
            } else if isFirst {
                // Today pending: skip without breaking, then require met days.
            } else {
                break
            }
            isFirst = false
            guard let prev = Calendar.current.date(byAdding: .day, value: -1, to: cursor) else { break }
            cursor = prev
            // Stop once we run past the available data window.
            if met[fmt.string(from: cursor)] == nil && fmt.string(from: cursor) < (days.first?.date ?? iso) {
                break
            }
        }
        return streak
    }

    /// Longest run of consecutive goal-met days in the (chronologically ordered,
    /// gap-free) history. The server backfills missing days with 0, so array
    /// adjacency equals calendar adjacency.
    static func longestStreak(days: [DayWriting], goalSeconds: Double) -> Int {
        guard goalSeconds > 0 else { return 0 }
        var longest = 0, run = 0
        for d in days {
            let met = DailyGoalProgress(writingSeconds: d.writingSeconds, goalSeconds: goalSeconds).isMet
            run = met ? run + 1 : 0
            longest = max(longest, run)
        }
        return longest
    }
}
