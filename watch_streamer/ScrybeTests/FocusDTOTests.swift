import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus DTO decoding")
struct FocusDTOTests {
    @Test("today decodes snake_case")
    func today() throws {
        let json = """
        {"date":"2026-06-22","day_start_ms":1,"day_end_ms":2,"now_ms":1,
         "total_writing_seconds":6420.0,"tick_count":42,
         "stretches":[{"start_ms":10,"end_ms":20,"duration_s":10.0}]}
        """.data(using: .utf8)!
        let dto = try JSONDecoder().decode(FocusTodayDTO.self, from: json)
        #expect(dto.totalWritingSeconds == 6420.0)
        #expect(dto.tickCount == 42)
        let first = try #require(dto.stretches.first)
        #expect(first.durationS == 10.0)
    }

    @Test("range (week/history) decodes")
    func range() throws {
        let json = """
        {"today":"2026-06-22","max_seconds":9000.0,
         "days":[{"date":"2026-06-21","weekday":"Sun","writing_seconds":3600.0,"is_today":false},
                 {"date":"2026-06-22","weekday":"Mon","writing_seconds":9000.0,"is_today":true}]}
        """.data(using: .utf8)!
        let dto = try JSONDecoder().decode(FocusRangeDTO.self, from: json)
        #expect(dto.days.count == 2)
        #expect(dto.days.last?.isToday == true)
        #expect(dto.maxSeconds == 9000.0)
    }
}
