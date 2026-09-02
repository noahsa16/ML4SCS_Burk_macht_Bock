import Foundation

/// One finished day, kept after its raw windows are gone.
///
/// Deliberately the *computed* day rather than a bare total: Verlauf lists a
/// day's writing stretches and Trends charts its time of day, so a total alone
/// would empty both screens for everything older than the raw retention.
struct FocusDaySummary: Codable, Sendable {
    let date: String
    let writingSeconds: Double
    let stretches: [FocusStretchDTO]
    /// Writing seconds per local hour, 24 entries.
    let hourlySeconds: [Double]
    /// Raw windows this day was built from, for diagnostics.
    let windowCount: Int

    var hourly: [Double] {
        hourlySeconds.count == 24 ? hourlySeconds : [Double](repeating: 0, count: 24)
    }
}

/// Per-day summaries on the phone, so raw passive windows can be discarded.
///
/// Why this exists: the tracker records every window, writing or not — 34,560
/// a day at a 2.5 s stride. Kept for the 90-day retention that would be roughly
/// 310 MB on the device. A summary is a few KB, and it is all any screen reads
/// once the day is over.
nonisolated final class FocusArchive: @unchecked Sendable {
    /// Days whose raw windows are kept so late deliveries still land.
    ///
    /// The watch fetches up to 12 h of recorder history per cycle and delivers
    /// over `transferUserInfo`, which is durable but unhurried. Three days is
    /// more than double the backlog the watch can even build, so a day is only
    /// sealed once nothing more can arrive for it.
    static let rawRetentionDays = 3

    private let fileURL: URL
    private let queue = DispatchQueue(label: "com.watchstreamer.focus.archive")
    private var days: [String: FocusDaySummary] = [:]

    init(fileURL: URL = FocusArchive.defaultFileURL()) {
        self.fileURL = fileURL
        days = Self.load(from: fileURL)
    }

    static func defaultFileURL() -> URL {
        AppSupportURL.file(named: "focus_archive.json")
    }

    // MARK: - Reading

    func summary(for date: String) -> FocusDaySummary? {
        queue.sync { days[date] }
    }

    func all() -> [FocusDaySummary] {
        queue.sync { days.values.sorted { $0.date < $1.date } }
    }

    // MARK: - Rolling up

    /// Seals every day that is older than the raw retention and still has
    /// windows, and reports which dates were sealed so the caller can prune
    /// exactly those.
    ///
    /// Archived days are immutable. The retention horizon is longer than the
    /// Watch recorder's delivery horizon, so a later fragment is necessarily
    /// a durable transport re-delivery. Replacing a complete archived day with
    /// that fragment would lose history; adding it would double-count it.
    @discardableResult
    func rollUp(_ decisions: [PassiveDecision],
                calendar: Calendar = .current, now: Date = Date()) -> [String] {
        guard let cutoff = calendar.date(byAdding: .day, value: -Self.rawRetentionDays,
                                         to: calendar.startOfDay(for: now))
        else { return [] }
        let cutoffMs = Int64(cutoff.timeIntervalSince1970 * 1000)

        var byDay: [String: [PassiveDecision]] = [:]
        for d in decisions where d.startMs < cutoffMs {
            let at = Date(timeIntervalSince1970: Double(d.startMs) / 1000)
            byDay[PassiveFocusAggregator.isoDate(at, calendar: calendar), default: []].append(d)
        }
        guard !byDay.isEmpty else { return [] }

        var sealed: [String] = []
        for (date, dayDecisions) in byDay {
            guard let first = dayDecisions.first else { continue }
            let at = Date(timeIntervalSince1970: Double(first.startMs) / 1000)
            let payload = PassiveFocusAggregator.day(at, from: dayDecisions,
                                                     calendar: calendar, now: now)
            let summary = FocusDaySummary(
                date: date,
                writingSeconds: payload.totalWritingSeconds,
                stretches: payload.stretches,
                hourlySeconds: PassiveFocusAggregator.hourlySeconds(
                    from: dayDecisions, on: at, calendar: calendar),
                windowCount: dayDecisions.count)
            queue.sync {
                guard days[date] == nil else { return }
                days[date] = summary
            }
            sealed.append(date)
        }
        persist()
        return sealed.sorted()
    }

    /// Drops summaries older than `days` days, matching the raw store's own
    /// retention so the two cannot drift apart.
    func prune(olderThan retentionDays: Int, calendar: Calendar = .current,
               now: Date = Date()) {
        guard let cutoff = calendar.date(byAdding: .day, value: -retentionDays,
                                         to: calendar.startOfDay(for: now))
        else { return }
        let cutoffISO = PassiveFocusAggregator.isoDate(cutoff, calendar: calendar)
        let removed: Bool = queue.sync {
            let before = days.count
            days = days.filter { $0.key >= cutoffISO }
            return days.count != before
        }
        if removed { persist() }
    }

    func removeAll() {
        queue.sync { days = [:] }
        try? FileManager.default.removeItem(at: fileURL)
    }

    // MARK: - Persistence

    private static func load(from url: URL) -> [String: FocusDaySummary] {
        guard let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode([String: FocusDaySummary].self,
                                                      from: data) else { return [:] }
        return decoded
    }

    private func persist() {
        let snapshot = queue.sync { days }
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        // Why atomic: a torn archive would silently lose months of history,
        // and unlike the raw windows there is nothing left to rebuild it from.
        try? data.write(to: fileURL, options: .atomic)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var url = fileURL
        try? url.setResourceValues(values)
    }
}
