import SwiftUI
import Combine

/// The phone's own record of writing time.
///
/// Reads passive decisions the watch delivered and the sealed day summaries
/// derived from them — no server. Recent days are computed from raw windows;
/// older ones come from `FocusArchive`, which is why the raw windows can be
/// thrown away (see `FocusArchive` for the volume this avoids).
@MainActor
final class FocusStore: ObservableObject {
    static let shared = FocusStore()

    @Published private(set) var today: FocusTodayDTO?
    @Published private(set) var week: FocusRangeDTO?
    @Published private(set) var history: FocusRangeDTO? {
        didSet { recomputeDerived() }
    }
    @Published private(set) var timeOfDay: FocusTimeOfDayDTO?
    /// The last pull did not reach the watch. Cached days stay on screen.
    @Published private(set) var watchUnreachable = false
    @Published private(set) var lastUpdated: Date?
    /// End of the most recent writing window on record, for the Heute status
    /// line. Passive decisions lag the recorder by minutes, so this is the
    /// honest replacement for a live "writing now" claim.
    @Published private(set) var lastWritingAt: Date?

    /// Per-day payloads for the Verlauf detail.
    @Published private(set) var dayCache: [String: FocusTodayDTO] = [:]

    private let decisions: PassiveDecisionStore
    private let archive: FocusArchive
    private let historyDays = 90
    private let calendar = Calendar.current

    init(decisions: PassiveDecisionStore = PassiveDecisionStore(
            fileURL: PassiveDecisionStore.defaultFileURL()),
         archive: FocusArchive = FocusArchive()) {
        self.decisions = decisions
        self.archive = archive
    }

    /// Loads what is already on disk. There is nothing to poll — data arrives
    /// when the watch hands it over, and `ingest` refreshes then.
    func start() {
        Task { await refresh() }
    }

    func stop() {}

    // MARK: - Reading

    /// Re-derives every screen from local data.
    /// - Returns: always true; a local read cannot be offline. Kept for the
    ///   call sites that report an outcome.
    @discardableResult
    func refresh() async -> Bool {
        let now = Date()
        var raw = decisions.allDecisions()

        // Seal days that can no longer receive late deliveries, then drop the
        // windows behind them. This is what keeps the store bounded.
        let sealed = archive.rollUp(raw, calendar: calendar, now: now)
        if !sealed.isEmpty {
            decisions.pruneOlderThan(days: FocusArchive.rawRetentionDays, now: now)
            raw = decisions.allDecisions()
        }
        archive.prune(olderThan: historyDays, calendar: calendar, now: now)

        apply(raw: raw, now: now)
        lastUpdated = now
        return true
    }

    /// Asks the watch to hand over what it has, then re-derives.
    func refreshForPull() async -> InkRefreshOutcome {
        let reached = await WatchDecisionSync.shared.requestSync()
        await refresh()
        watchUnreachable = !reached
        return reached ? .updated(at: lastUpdated ?? Date()) : .offline
    }

    /// Stores a batch handed over by the watch and refreshes.
    ///
    /// Idle windows are dropped on arrival: no screen reads them — a gap
    /// between writing windows already ends a stretch — and keeping them costs
    /// roughly twenty times the storage.
    func ingest(_ batch: [PassiveDecision]) async {
        let writing = batch.filter(\.writing)
        guard !writing.isEmpty else { return }
        decisions.record(writing)
        await refresh()
    }

    private func apply(raw: [PassiveDecision], now: Date) {
        var liveByDay: [String: [PassiveDecision]] = [:]
        for d in raw {
            let at = Date(timeIntervalSince1970: Double(d.startMs) / 1000)
            liveByDay[PassiveFocusAggregator.isoDate(at, calendar: calendar), default: []]
                .append(d)
        }

        let todayStart = calendar.startOfDay(for: now)
        today = payload(for: todayStart, liveByDay: liveByDay, now: now)
        history = range(days: historyDays, liveByDay: liveByDay, now: now)
        week = range(days: 7, liveByDay: liveByDay, now: now)
        timeOfDay = hourly(days: 7, liveByDay: liveByDay, now: now)
        lastWritingAt = mostRecentWriting(raw: raw)
        dayCache = [:]
    }

    /// The archive owns sealed days; raw windows own the rest. `rollUp` and the
    /// prune that follows it keep the two disjoint, so archive-first is exact.
    private func payload(for dayStart: Date, liveByDay: [String: [PassiveDecision]],
                         now: Date) -> FocusTodayDTO {
        let iso = PassiveFocusAggregator.isoDate(dayStart, calendar: calendar)
        let start = Int(dayStart.timeIntervalSince1970 * 1000)
        let end = Int((calendar.date(byAdding: .day, value: 1, to: dayStart) ?? dayStart)
            .timeIntervalSince1970 * 1000)
        if let s = archive.summary(for: iso) {
            return FocusTodayDTO(date: iso, totalWritingSeconds: s.writingSeconds,
                                 stretches: s.stretches, tickCount: s.windowCount,
                                 dayStartMs: start, dayEndMs: end,
                                 nowMs: Int(now.timeIntervalSince1970 * 1000))
        }
        return PassiveFocusAggregator.day(dayStart, from: liveByDay[iso] ?? [],
                                          calendar: calendar, now: now)
    }

    private func range(days: Int, liveByDay: [String: [PassiveDecision]],
                       now: Date) -> FocusRangeDTO {
        let todayStart = calendar.startOfDay(for: now)
        var out: [FocusDayDTO] = []
        var maxSeconds: Double = 0
        for offset in stride(from: days - 1, through: 0, by: -1) {
            guard let dayStart = calendar.date(byAdding: .day, value: -offset, to: todayStart)
            else { continue }
            let p = payload(for: dayStart, liveByDay: liveByDay, now: now)
            maxSeconds = max(maxSeconds, p.totalWritingSeconds)
            out.append(FocusDayDTO(date: p.date,
                                   weekday: Self.weekday(dayStart, calendar: calendar),
                                   writingSeconds: p.totalWritingSeconds,
                                   isToday: dayStart == todayStart))
        }
        return FocusRangeDTO(days: out,
                             today: PassiveFocusAggregator.isoDate(todayStart,
                                                                   calendar: calendar),
                             maxSeconds: maxSeconds)
    }

    private func hourly(days: Int, liveByDay: [String: [PassiveDecision]],
                        now: Date) -> FocusTimeOfDayDTO {
        let todayStart = calendar.startOfDay(for: now)
        var seconds = [Double](repeating: 0, count: 24)
        for offset in 0..<days {
            guard let dayStart = calendar.date(byAdding: .day, value: -offset, to: todayStart)
            else { continue }
            let iso = PassiveFocusAggregator.isoDate(dayStart, calendar: calendar)
            let dayHours = archive.summary(for: iso)?.hourly
                ?? PassiveFocusAggregator.hourlySeconds(from: liveByDay[iso] ?? [],
                                                        on: dayStart, calendar: calendar)
            for h in 0..<24 { seconds[h] += dayHours[h] }
        }
        return PassiveFocusAggregator.timeOfDay(seconds: seconds, days: days)
    }

    private func mostRecentWriting(raw: [PassiveDecision]) -> Date? {
        if let ms = raw.filter(\.writing).map(\.endMs).max() {
            return Date(timeIntervalSince1970: Double(ms) / 1000)
        }
        guard let ms = archive.all().reversed()
            .compactMap({ $0.stretches.last?.endMs }).first else { return nil }
        return Date(timeIntervalSince1970: Double(ms) / 1000)
    }

    private static func weekday(_ date: Date, calendar: Calendar) -> String {
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = Locale.current
        f.setLocalizedDateFormatFromTemplate("EEE")
        return f.string(from: date)
    }

    // MARK: - Verlauf detail

    /// Kept for the Verlauf detail's call sites. Local reads cannot fail, so a
    /// day is either present or genuinely empty.
    enum DayLoadState: Equatable {
        case loading
        case loaded
        case failed(String)
    }

    @Published private(set) var dayState: [String: DayLoadState] = [:]

    func loadDay(_ date: String, force: Bool = false) async {
        if !force, dayCache[date] != nil { return }
        guard let dayStart = Self.date(fromISO: date, calendar: calendar) else {
            dayState[date] = .failed("Ungültiges Datum")
            return
        }
        let raw = decisions.allDecisions()
        var liveByDay: [String: [PassiveDecision]] = [:]
        for d in raw {
            let at = Date(timeIntervalSince1970: Double(d.startMs) / 1000)
            liveByDay[PassiveFocusAggregator.isoDate(at, calendar: calendar), default: []]
                .append(d)
        }
        dayCache[date] = payload(for: dayStart, liveByDay: liveByDay, now: Date())
        dayState[date] = .loaded
    }

    private static func date(fromISO iso: String, calendar: Calendar) -> Date? {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var c = DateComponents()
        c.year = parts[0]; c.month = parts[1]; c.day = parts[2]
        return calendar.date(from: c)
    }

    /// Erases every writing record on this phone.
    func deleteAllLocalData() {
        decisions.removeAll()
        archive.removeAll()
        today = nil; week = nil; history = nil; timeOfDay = nil
        dayCache = [:]; dayState = [:]
        lastWritingAt = nil; lastUpdated = nil
    }

    // MARK: - Derived

    var todayWritingSeconds: Double { today?.totalWritingSeconds ?? 0 }

    var goalProgress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: todayWritingSeconds,
                          goalSeconds: ScrybeSettings.goalSeconds)
    }

    var streak: Int {
        let days = (history?.days ?? []).map {
            DayWriting(date: $0.date, writingSeconds: $0.writingSeconds)
        }
        let todayISO = history?.today ?? today?.date ?? ""
        return StreakCalculator.currentStreak(
            days: days, goalSeconds: ScrybeSettings.goalSeconds, todayISO: todayISO)
    }

    var longestStreak: Int {
        let days = (history?.days ?? []).map {
            DayWriting(date: $0.date, writingSeconds: $0.writingSeconds)
        }
        return StreakCalculator.longestStreak(days: days, goalSeconds: ScrybeSettings.goalSeconds)
    }

    var hasData: Bool { today != nil || history != nil }

    // Derived once per data change rather than on every body pass — Trends and
    // Verlauf otherwise re-filtered a 90-day array on each render.
    private(set) var activeDays: [FocusDayDTO] = []
    private(set) var monthDays: [FocusDayDTO] = []
    private(set) var monthMax: Double = 0
    private(set) var monthSum: Double = 0
    private(set) var previousMonthSum: Double?
    private(set) var previousWeekSum: Double?
    private(set) var lastSevenDays: [FocusDayDTO] = []

    private func recomputeDerived() {
        let days = history?.days ?? []
        activeDays = days.filter { $0.writingSeconds > 0 }.reversed()
        monthDays = Array(days.suffix(30))
        monthMax = monthDays.map(\.writingSeconds).max() ?? 0
        monthSum = monthDays.reduce(0) { $0 + $1.writingSeconds }
        previousWeekSum = days.count >= 14
            ? days.suffix(14).prefix(7).reduce(0) { $0 + $1.writingSeconds } : nil
        previousMonthSum = days.count >= 60
            ? days.suffix(60).prefix(30).reduce(0) { $0 + $1.writingSeconds } : nil
        lastSevenDays = Array(days.suffix(7))
    }

    var thisWeekSum: Double {
        (week?.days ?? []).reduce(0) { $0 + $1.writingSeconds }
    }

    var hasAnyHistory: Bool { !activeDays.isEmpty }
}
