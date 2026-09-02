import Testing
import Foundation
@testable import WatchStreamer

@Suite("TrendPaging")
struct TrendPagingTests {
    private func days(_ seconds: [Double]) -> [FocusDayDTO] {
        seconds.enumerated().map { i, s in
            let day = Calendar(identifier: .gregorian)
                .date(byAdding: .day, value: i, to: DateComponents(calendar: .init(identifier: .gregorian),
                                                                  year: 2026, month: 6, day: 1).date!)!
            let f = DateFormatter()
            f.calendar = Calendar(identifier: .gregorian)
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd"
            return FocusDayDTO(date: f.string(from: day), weekday: "",
                               writingSeconds: s, isToday: i == seconds.count - 1)
        }
    }

    @Test("the current week is the last seven days, and the one before it compares")
    func currentWeek() {
        let d = days(Array(repeating: 60, count: 14) + [0, 0, 0, 0, 0, 0, 600])
        let p = TrendPaging(span: .week, offset: 0, days: d)
        #expect(p.window.count == 7)
        #expect(p.window.last?.writingSeconds == 600.0)
        #expect(p.sum == 600.0)
        let previous: Double? = 420.0
        #expect(p.previousSum == previous)
        #expect(p.caption == .thisWeek)
        #expect(p.isCurrent)
        #expect(p.canGoForward == false)
    }

    @Test("a comparison window is offered only when the history holds all of it")
    func partialComparisonIsNil() {
        let d = days(Array(repeating: 60, count: 10))
        let p = TrendPaging(span: .week, offset: 0, days: d)
        #expect(p.window.count == 7)
        #expect(p.previousWindow == nil)
        #expect(p.previousSum == nil)
    }

    @Test("the window shortens at the start of the history")
    func shortWindow() {
        let d = days(Array(repeating: 60, count: 10))
        let back = TrendPaging(span: .week, offset: 1, days: d)
        #expect(back.window.count == 3)
        #expect(back.window.first?.date == "2026-06-01")
    }

    @Test("paging stops at the window holding the first day with writing")
    func maxOffset() {
        var seconds = Array(repeating: 0.0, count: 30)
        seconds[9] = 300   // day 10 of 30 → 20 days back from today
        let d = days(seconds)
        #expect(TrendPaging(span: .week, offset: 0, days: d).maxOffset == 2)
        #expect(TrendPaging(span: .month, offset: 0, days: d).maxOffset == 0)
        #expect(TrendPaging(span: .week, offset: 0, days: days([0, 0, 0])).maxOffset == 0)
        #expect(TrendPaging(span: .week, offset: 0, days: []).maxOffset == 0)
        #expect(TrendPaging(span: .week, offset: 0, days: []).window.isEmpty)
    }

    @Test("captions name the first two windows, then the date range")
    func captions() {
        let d = days(Array(repeating: 60, count: 40))
        #expect(TrendPaging(span: .week, offset: 1, days: d).caption == .lastWeek)
        #expect(TrendPaging(span: .month, offset: 0, days: d).caption == .last30Days)
        #expect(TrendPaging(span: .month, offset: 1, days: d).caption == .previous30Days)
        let older = TrendPaging(span: .week, offset: 2, days: d)
        #expect(older.caption == .range(startISO: "2026-06-20", endISO: "2026-06-26"))
    }

    @Test("the default selection is the window's newest day")
    func defaultSelection() {
        let d = days(Array(repeating: 60, count: 9))
        #expect(TrendPaging(span: .week, offset: 0, days: d).defaultSelection == "2026-06-09")
        #expect(TrendPaging(span: .week, offset: 1, days: d).defaultSelection == "2026-06-02")
    }
}

@Suite("TrendInsights")
struct TrendInsightsTests {
    private func day(_ iso: String, _ seconds: Double) -> FocusDayDTO {
        FocusDayDTO(date: iso, weekday: "", writingSeconds: seconds, isToday: false)
    }

    @Test("an empty window has nothing to say")
    func emptyWindow() {
        let w = [day("2026-06-01", 0), day("2026-06-02", 0)]
        #expect(TrendInsights.insights(window: w, allDays: w, goalSeconds: 600).isEmpty)
    }

    @Test("active days, goal days, best day and average are reported in order")
    func fullWindow() {
        let w = [day("2026-06-01", 0), day("2026-06-02", 300),
                 day("2026-06-03", 900), day("2026-06-04", 600)]
        let out = TrendInsights.insights(window: w, allDays: w, goalSeconds: 600)
        #expect(out[0] == .activeDays(active: 3, of: 4))
        #expect(out[1] == .goalDays(met: 2))
        #expect(out[2] == .bestDay(iso: "2026-06-03", seconds: 900))
        #expect(out[3] == .averagePerActiveDay(seconds: 600))
    }

    @Test("a single active day gets no average and no unmet goal line")
    func singleDay() {
        let w = [day("2026-06-01", 0), day("2026-06-02", 300)]
        let out = TrendInsights.insights(window: w, allDays: w, goalSeconds: 600)
        #expect(out == [.activeDays(active: 1, of: 2), .bestDay(iso: "2026-06-02", seconds: 300)])
    }

    @Test("the weekday habit needs three active days on two weekdays with a clear leader")
    func weekdayHabit() {
        let cal = Calendar(identifier: .gregorian)
        // 2026-06-06 and 2026-06-13 are Saturdays (weekday 7); 2026-06-08 a Monday (2).
        let saturdays = [day("2026-06-06", 900), day("2026-06-13", 900), day("2026-06-08", 300)]
        #expect(TrendInsights.weekdayHabit(allDays: saturdays, calendar: cal) == 7)
        let tooFew = [day("2026-06-06", 900), day("2026-06-08", 300)]
        #expect(TrendInsights.weekdayHabit(allDays: tooFew, calendar: cal) == nil)
        let oneWeekday = [day("2026-06-06", 900), day("2026-06-13", 900), day("2026-06-20", 900)]
        #expect(TrendInsights.weekdayHabit(allDays: oneWeekday, calendar: cal) == nil)
        let tied = [day("2026-06-06", 600), day("2026-06-08", 600), day("2026-06-15", 0), day("2026-06-09", 100)]
        // Saturday 600 vs Monday 600: tied leaders → no habit, Tuesday 100 is third.
        #expect(TrendInsights.weekdayHabit(allDays: tied, calendar: cal) == nil)
    }

    @Test("the peak hour is the busiest bucket, or nil when nothing was written")
    func peakHour() {
        let buckets = (0..<24).map { FocusHourBucketDTO(hour: $0, seconds: $0 == 12 ? 500 : 20) }
        #expect(TrendInsights.peakHour(buckets: buckets) == 12)
        let silent = (0..<24).map { FocusHourBucketDTO(hour: $0, seconds: 0) }
        #expect(TrendInsights.peakHour(buckets: silent) == nil)
        #expect(TrendInsights.peakHour(buckets: []) == nil)
    }

    @Test("dayparts partition the clock")
    func dayparts() {
        let all = TrendInsights.DayPart.allCases.flatMap { Array($0.hours) }
        #expect(Set(all) == Set(0..<24))
        #expect(all.count == 24)
        let buckets = (0..<24).map { FocusHourBucketDTO(hour: $0, seconds: 10) }
        #expect(TrendInsights.seconds(for: .night, buckets: buckets) == 60)
        #expect(TrendInsights.seconds(for: .morning, buckets: buckets) == 60)
    }
}
