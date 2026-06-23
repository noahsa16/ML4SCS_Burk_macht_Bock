import SwiftUI
import Combine

@MainActor
final class FocusStore: ObservableObject {
    static let shared = FocusStore()

    @Published private(set) var today: FocusTodayDTO?
    @Published private(set) var week: FocusRangeDTO?
    @Published private(set) var history: FocusRangeDTO?
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

    func refresh() async {
        do {
            async let t = api.today()
            async let w = api.week()
            async let h = api.history(days: historyDays)
            async let tod = api.timeOfDay(days: 7)
            let (td, wk, hi, to) = try await (t, w, h, tod)
            today = td
            week = wk
            history = hi
            timeOfDay = to
            isOffline = false
            lastUpdated = Date()
        } catch is CancellationError {
            // poll cancelled — keep state
        } catch {
            isOffline = true   // keep last good values
        }
    }

    /// Fetch + cache a past day's stretch payload for the Verlauf detail. Today
    /// is served live from `today`, so callers should prefer that for today.
    func loadDay(_ date: String) async {
        if dayCache[date] != nil { return }
        do { dayCache[date] = try await api.day(date) } catch { /* keep absent */ }
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
}
