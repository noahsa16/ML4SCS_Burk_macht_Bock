import SwiftUI

@MainActor
final class FocusStore: ObservableObject {
    static let shared = FocusStore()

    @Published private(set) var today: FocusTodayDTO?
    @Published private(set) var week: FocusRangeDTO?
    @Published private(set) var history: FocusRangeDTO?
    @Published private(set) var isOffline = false
    @Published private(set) var lastUpdated: Date?

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
            let (td, wk, hi) = try await (t, w, h)
            today = td
            week = wk
            history = hi
            isOffline = false
            lastUpdated = Date()
        } catch is CancellationError {
            // poll cancelled — keep state
        } catch {
            isOffline = true   // keep last good values
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

    var hasData: Bool { today != nil || history != nil }
}
