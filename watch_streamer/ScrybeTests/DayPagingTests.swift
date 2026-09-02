import Testing
import Foundation
@testable import WatchStreamer

@Suite("DayPaging")
struct DayPagingTests {
    private func days(_ seconds: [Double]) -> [FocusDayDTO] {
        seconds.enumerated().map { i, s in
            FocusDayDTO(date: String(format: "2026-08-%02d", i + 1), weekday: "",
                        writingSeconds: s, isToday: i == seconds.count - 1)
        }
    }

    @Test("today is offset zero and cannot go forward")
    func today() {
        let p = DayPaging(offset: 0, days: days([0, 600, 0, 300]))
        #expect(p.isToday)
        #expect(!p.canGoForward)
        #expect(p.canGoBack)
        #expect(p.day?.date == "2026-08-04")
        #expect(p.caption == .today)
    }

    @Test("paging stops at the first day with writing")
    func maxOffsetStopsAtFirstWriting() {
        #expect(DayPaging(offset: 0, days: days([0, 0, 600, 0, 300])).maxOffset == 2)
        #expect(DayPaging(offset: 0, days: days([0, 0, 0])).maxOffset == 0)
        #expect(DayPaging(offset: 0, days: []).maxOffset == 0)
    }

    @Test("captions: yesterday, then weekday, then date")
    func captions() {
        let d = days(Array(repeating: 60, count: 10))
        #expect(DayPaging(offset: 1, days: d).caption == .yesterday)
        if case .weekday(let name) = DayPaging(offset: 2, days: d).caption {
            #expect(!name.isEmpty)
        } else { Issue.record("expected a weekday") }
        if case .date(let text) = DayPaging(offset: 7, days: d).caption {
            #expect(!text.isEmpty)
        } else { Issue.record("expected a date") }
    }

    @Test("window ends on the shown day and shortens at the start")
    func window() {
        let d = days(Array(repeating: 60, count: 10))
        let mid = DayPaging(offset: 1, days: d)
        #expect(mid.window.map(\.date).last == "2026-08-09")
        #expect(mid.window.count == 7)
        let early = DayPaging(offset: 8, days: d)
        #expect(early.window.count == 2)
        #expect(early.window.first?.date == "2026-08-01")
    }
}
