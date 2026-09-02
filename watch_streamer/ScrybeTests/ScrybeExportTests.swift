import Testing
import Foundation
@testable import WatchStreamer

@Suite("ScrybeExport")
struct ScrybeExportTests {

    private func decoded(_ data: Data) throws -> [String: Any] {
        try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    @Test("the export is valid JSON with a schema version and a timestamp")
    func hasEnvelope() throws {
        let obj = try decoded(ScrybeExport.makeJSON(history: nil, today: nil))
        #expect(obj["schema_version"] as? Int == ScrybeExport.schemaVersion)
        #expect((obj["exported_at"] as? String)?.isEmpty == false)
        #expect(obj["app"] as? String == "Scrybe")
    }

    // The label and the privacy paragraph promise a portable copy of the
    // user's data, so the payload has to say what it leaves out.
    @Test("the payload names both what it contains and what it excludes")
    func statesScope() throws {
        let obj = try decoded(ScrybeExport.makeJSON(history: nil, today: nil))
        let contains = try #require(obj["contains"] as? [String])
        let excludes = try #require(obj["excludes"] as? [String])
        #expect(contains.contains("daily_writing_seconds"))
        #expect(contains.contains("local_settings"))
        #expect(excludes.contains("raw_motion_samples"))
        #expect(excludes.contains("server_side_recordings"))
    }

    @Test("settings are included")
    func includesSettings() throws {
        let obj = try decoded(ScrybeExport.makeJSON(history: nil, today: nil))
        let settings = try #require(obj["settings"] as? [String: Any])
        #expect(settings["daily_goal_seconds"] != nil)
        #expect(settings["language"] != nil)
    }

    @Test("an empty data set still produces a well-formed export")
    func emptyIsWellFormed() throws {
        let obj = try decoded(ScrybeExport.makeJSON(history: nil, today: nil))
        #expect((obj["days"] as? [Any])?.isEmpty == true)
        #expect((obj["today_stretches"] as? [Any])?.isEmpty == true)
    }

    @Test("the filename is dated and carries the json extension")
    func filenameIsNamed() {
        var components = DateComponents()
        components.year = 2026; components.month = 8; components.day = 29
        let date = Calendar.current.date(from: components)!
        #expect(ScrybeExport.filename(now: date) == "scrybe-export-2026-08-29.json")
    }

    @Test("writing produces a real file that reads back as the same JSON")
    func writesARealFile() throws {
        let url = try #require(ScrybeExport.writeTemporaryFile(history: nil, today: nil))
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(url.pathExtension == "json")
        #expect(FileManager.default.fileExists(atPath: url.path))
        let obj = try decoded(try Data(contentsOf: url))
        #expect(obj["schema_version"] as? Int == ScrybeExport.schemaVersion)
    }
}
