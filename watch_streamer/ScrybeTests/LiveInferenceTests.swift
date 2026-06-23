import Testing
import Foundation
@testable import WatchStreamer

@Suite("LiveInferencePayload decoding")
struct LiveInferenceTests {
    @Test("normal tick decodes; optional fields absent")
    func normal() throws {
        let json = """
        {"writing":true,"proba":0.91,"model_id":"rf_noah","person_id":"noah",
         "fs_hz":100.0,"window_samples":100,"today_writing_seconds":6420.0}
        """.data(using: .utf8)!
        let p = try JSONDecoder().decode(LiveInferencePayload.self, from: json)
        #expect(p.writing == true)
        #expect(p.proba == 0.91)
        #expect(p.todayWritingSeconds == 6420.0)
        #expect(p.rateMismatch == nil)
    }

    @Test("rate-mismatch tick decodes with null model_id")
    func mismatch() throws {
        let json = """
        {"writing":false,"proba":0.0,"model_id":null,"person_id":null,
         "fs_hz":40.0,"trained_fs_hz":100.0,"rate_mismatch":true,
         "today_writing_seconds":12.0}
        """.data(using: .utf8)!
        let p = try JSONDecoder().decode(LiveInferencePayload.self, from: json)
        #expect(p.rateMismatch == true)
        #expect(p.modelId == nil)
        #expect(p.writing == false)
    }
}
