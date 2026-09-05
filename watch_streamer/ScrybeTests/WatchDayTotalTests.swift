import Testing
import Foundation
@testable import WatchStreamer

@Suite("Watch day total")
struct WatchDayTotalTests {

    @Test("round-trips through a payload")
    func payloadRoundTrip() {
        let total = WatchDayTotal(day: "2026-09-02", writingSeconds: 1_830)
        #expect(WatchDayTotal.from(payload: total.payloadFields) == total)
    }

    @Test("a payload without both fields is no total")
    func partialPayloadIsNil() {
        #expect(WatchDayTotal.from(payload: [WatchPayloadKey.todayDay: "2026-09-02"]) == nil)
        #expect(WatchDayTotal.from(payload: [WatchPayloadKey.todayWritingSeconds: 12.0]) == nil)
        #expect(WatchDayTotal.from(payload: [WatchPayloadKey.todayDay: "gestern",
                                             WatchPayloadKey.todayWritingSeconds: 12.0]) == nil)
        #expect(WatchDayTotal.from(payload: [WatchPayloadKey.todayDay: "2026-09-02",
                                             WatchPayloadKey.todayWritingSeconds: -1.0]) == nil)
    }

    // The mirror lives in UserDefaults across midnight; yesterday's total
    // must not be shown as today's.
    @Test("a total is only reported on its own day")
    func totalExpiresWithItsDay() {
        let now = Date()
        let today = WatchDayTotal(day: WatchDayTotal.isoDay(now), writingSeconds: 600)
        let yesterday = WatchDayTotal(day: WatchDayTotal.isoDay(now.addingTimeInterval(-86_400)),
                                      writingSeconds: 600)
        #expect(today.writingSeconds(on: now) == 600)
        #expect(yesterday.writingSeconds(on: now) == nil)
    }

    @Test("stores and loads through UserDefaults")
    func defaultsRoundTrip() {
        let suite = "watch-day-total-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let total = WatchDayTotal(day: "2026-09-02", writingSeconds: 42)
        total.store(in: defaults)
        #expect(WatchDayTotal.load(from: defaults) == total)
    }
}
