import Foundation

/// One sentence the Trends page can say about a window of days. The view
/// turns each case into copy; keeping the facts and the wording apart is what
/// makes the facts testable.
nonisolated enum TrendInsight: Equatable {
    /// Days with any writing, out of the days the window holds.
    case activeDays(active: Int, of: Int)
    /// Days on which the daily goal was met. Omitted when none.
    case goalDays(met: Int)
    /// The window's strongest day.
    case bestDay(iso: String, seconds: Double)
    /// Mean writing time over the window's active days.
    case averagePerActiveDay(seconds: Double)
    /// Across the whole history, the weekday most is written on.
    /// `weekday` follows `Calendar.component(.weekday)`: 1 is Sunday.
    case weekdayHabit(weekday: Int)
}

nonisolated enum TrendInsights {

    /// Insights in display order. An empty window yields none: there is
    /// nothing honest to say about a week with no writing in it.
    static func insights(window: [FocusDayDTO],
                         allDays: [FocusDayDTO],
                         goalSeconds: Double,
                         calendar: Calendar = .current) -> [TrendInsight] {
        let active = window.filter { $0.writingSeconds > 0 }
        guard !active.isEmpty else { return [] }

        var out: [TrendInsight] = [.activeDays(active: active.count, of: window.count)]

        if goalSeconds > 0 {
            let met = window.filter {
                DailyGoalProgress(writingSeconds: $0.writingSeconds, goalSeconds: goalSeconds).isMet
            }.count
            if met > 0 { out.append(.goalDays(met: met)) }
        }

        if let best = window.max(by: { $0.writingSeconds < $1.writingSeconds }),
           best.writingSeconds > 0 {
            out.append(.bestDay(iso: best.date, seconds: best.writingSeconds))
        }

        // Why only from two active days: a single day's "average" is the
        // day itself, already stated as the best day.
        if active.count >= 2 {
            let total = active.reduce(0) { $0 + $1.writingSeconds }
            out.append(.averagePerActiveDay(seconds: total / Double(active.count)))
        }

        if let habit = weekdayHabit(allDays: allDays, calendar: calendar) {
            out.append(.weekdayHabit(weekday: habit))
        }
        return out
    }

    /// The weekday with the most writing across the history, once there is
    /// enough of it to mean anything: at least three active days spread over
    /// at least two different weekdays, and the leading weekday ahead of the
    /// runner-up rather than tied with it.
    static func weekdayHabit(allDays: [FocusDayDTO], calendar: Calendar = .current) -> Int? {
        let active = allDays.filter { $0.writingSeconds > 0 }
        guard active.count >= 3 else { return nil }
        var totals: [Int: Double] = [:]
        for day in active {
            guard let weekday = weekday(iso: day.date, calendar: calendar) else { continue }
            totals[weekday, default: 0] += day.writingSeconds
        }
        guard totals.count >= 2 else { return nil }
        let ranked = totals.sorted { $0.value > $1.value }
        guard ranked[0].value > ranked[1].value else { return nil }
        return ranked[0].key
    }

    /// The clock hour with the most writing, or `nil` when the buckets are
    /// empty or all zero.
    static func peakHour(buckets: [FocusHourBucketDTO]) -> Int? {
        guard let top = buckets.max(by: { $0.seconds < $1.seconds }), top.seconds > 0 else {
            return nil
        }
        return top.hour
    }

    /// Writing time by daypart, in the order the chart draws them.
    enum DayPart: String, CaseIterable, Equatable {
        case morning, noon, evening, night

        var hours: Set<Int> {
            switch self {
            case .morning: return Set(5..<11)
            case .noon: return Set(11..<17)
            case .evening: return Set(17..<23)
            case .night: return [23, 0, 1, 2, 3, 4]
            }
        }
    }

    static func seconds(for part: DayPart, buckets: [FocusHourBucketDTO]) -> Double {
        buckets.filter { part.hours.contains($0.hour) }.reduce(0) { $0 + $1.seconds }
    }

    /// `Calendar.component(.weekday)` for an ISO day, 1 = Sunday.
    static func weekday(iso: String, calendar: Calendar) -> Int? {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var c = DateComponents()
        c.year = parts[0]; c.month = parts[1]; c.day = parts[2]
        guard let date = calendar.date(from: c) else { return nil }
        return calendar.component(.weekday, from: date)
    }
}
