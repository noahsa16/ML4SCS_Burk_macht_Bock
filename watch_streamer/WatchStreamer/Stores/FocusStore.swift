import SwiftUI
import Combine

@MainActor
final class FocusStore: ObservableObject {
    static let shared = FocusStore()

    @Published private(set) var today: FocusTodayDTO?
    @Published private(set) var week: FocusRangeDTO?
    @Published private(set) var history: FocusRangeDTO? {
        didSet { recomputeDerived() }
    }
    @Published private(set) var timeOfDay: FocusTimeOfDayDTO?
    @Published private(set) var isOffline = false
    @Published private(set) var lastUpdated: Date?

    // Per-day stretch payloads for the Verlauf detail (past days are immutable,
    // so a session-lifetime cache is safe; today is read live from `today`).
    @Published private(set) var dayCache: [String: FocusTodayDTO] = [:]

    private let api = FocusAPI()
    private var pollTask: Task<Void, Never>?
    private let historyDays = 90

    private init() {}

    func start() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refresh()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    /// Refreshes every section, committing each one independently.
    ///
    /// Why not one `try await (t, w, h, tod)` tuple: a single throw discarded
    /// three successful responses along with the failed one, so a hiccup on the
    /// time-of-day endpoint could make Heute, Trends and Verlauf all read as
    /// stale at once. `isOffline` now means *nothing* came back, which is what
    /// the offline banner claims.
    /// - Returns: whether this refresh reached the server at all. The pull-to-
    ///   refresh control needs the result of *its own* pull; `isOffline` is the
    ///   standing state and stays false while cached data is still on screen.
    @discardableResult
    func refresh() async -> Bool {
        async let t = api.today()
        async let w = api.week()
        async let h = api.history(days: historyDays)
        async let tod = api.timeOfDay(days: 7)

        var succeeded = 0
        var cancelled = false

        do { today = try await t; succeeded += 1 }
        catch is CancellationError { cancelled = true } catch {}
        do { week = try await w; succeeded += 1 }
        catch is CancellationError { cancelled = true } catch {}
        do { history = try await h; succeeded += 1 }
        catch is CancellationError { cancelled = true } catch {}
        do { timeOfDay = try await tod; succeeded += 1 }
        catch is CancellationError { cancelled = true } catch {}

        guard !cancelled else { return !isOffline }   // poll cancelled — keep state
        if succeeded > 0 {
            isOffline = false
            lastUpdated = Date()
        } else {
            isOffline = true   // keep last good values
        }
        return succeeded > 0
    }

    /// Refresh phrased as a pull outcome, so every screen's ink control shares
    /// one mapping from "did it reach the server" to what the ring reports.
    func refreshForPull() async -> InkRefreshOutcome {
        await refresh() ? .updated(at: lastUpdated ?? Date()) : .offline
    }

    /// Load state for a single past day, so the UI can show a failure and a
    /// retry instead of an indefinite "Laden …".
    enum DayLoadState: Equatable {
        case loading
        case loaded
        case failed(String)
    }

    @Published private(set) var dayState: [String: DayLoadState] = [:]

    /// Fetch + cache a past day's stretch payload for the Verlauf detail. Today
    /// is served live from `today`, so callers should prefer that for today.
    func loadDay(_ date: String, force: Bool = false) async {
        if !force, dayCache[date] != nil { return }
        if !force, dayState[date] == .loading { return }
        dayState[date] = .loading
        do {
            dayCache[date] = try await api.day(date)
            dayState[date] = .loaded
        } catch is CancellationError {
            dayState[date] = nil
        } catch {
            // Why surfaced rather than swallowed: the row otherwise sat at
            // "Laden …" forever with no failure and no way to retry.
            dayState[date] = .failed(error.localizedDescription)
        }
    }

    // Polled-only today seconds (does not include the live WS counter).
    var todayWritingSecondsPolled: Double { today?.totalWritingSeconds ?? 0 }

    var goalProgress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: todayWritingSecondsPolled,
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

    // MARK: – Derived screen snapshots
    //
    // Why here and not in the views: History filtered and reversed the 90-day
    // array, and Trends took three suffixes and four reductions, on every body
    // pass of a view observing a store that publishes on a 5-second poll and on
    // every WebSocket tick. Deriving once per data change keeps that work off
    // the render path as the history grows.

    /// Days with any writing, newest first.
    private(set) var activeDays: [FocusDayDTO] = []
    /// The last 30 days, for the Trends month chart.
    private(set) var monthDays: [FocusDayDTO] = []
    private(set) var monthMax: Double = 0
    private(set) var monthSum: Double = 0
    /// The 30 days before those, or nil when the history is too short.
    private(set) var previousMonthSum: Double?
    /// The 7 days before this week, or nil when the history is too short.
    private(set) var previousWeekSum: Double?
    /// The last 7 days, for the streak calendar.
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
