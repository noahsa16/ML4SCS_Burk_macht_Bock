import Testing
import Foundation
@testable import WatchStreamer

/// The Profile screen offers an English override, so a key with only a German
/// value makes the visible UI switch language while VoiceOver and status text
/// stay German. This test is the gate that keeps the catalog whole.
@Suite("Localization completeness")
struct LocalizationCompletenessTests {

    private struct Catalog: Decodable {
        let sourceLanguage: String
        let strings: [String: Entry]

        struct Entry: Decodable {
            let localizations: [String: Localization]?
        }
        struct Localization: Decodable {
            let stringUnit: Unit?
        }
        struct Unit: Decodable {
            let state: String
            let value: String
        }
    }

    /// Reads the catalog from the source tree.
    ///
    /// Why not `Bundle`: Xcode compiles `.xcstrings` into per-language
    /// `.strings` at build time, so the catalog itself never reaches the
    /// bundle. Completeness is a property of the source artifact, and that is
    /// where it has to be checked.
    private func catalog(file: StaticString = #filePath) throws -> Catalog {
        let testFile = URL(fileURLWithPath: "\(file)")
        let url = testFile
            .deletingLastPathComponent()      // ScrybeTests
            .deletingLastPathComponent()      // watch_streamer
            .appendingPathComponent("WatchStreamer/Localizable.xcstrings")
        try #require(FileManager.default.fileExists(atPath: url.path),
                     "catalog not found at \(url.path)")
        return try JSONDecoder().decode(Catalog.self, from: Data(contentsOf: url))
    }

    @Test("the catalog declares German as its source")
    func sourceLanguage() throws {
        #expect(try catalog().sourceLanguage == "de")
    }

    @Test("every key has an English value")
    func everyKeyHasEnglish() throws {
        let strings = try catalog().strings
        let missing = strings
            .filter { $0.value.localizations?["en"]?.stringUnit == nil }
            .keys
            .sorted()
        #expect(missing.isEmpty,
                "keys without English: \(missing.joined(separator: ", "))")
    }

    @Test("no English value is left empty")
    func noEmptyEnglishValues() throws {
        let strings = try catalog().strings
        let empty = strings.filter { key, entry in
            guard !key.isEmpty else { return false }
            guard let unit = entry.localizations?["en"]?.stringUnit else { return false }
            return unit.value.isEmpty
        }.keys.sorted()
        #expect(empty.isEmpty, "empty English values: \(empty.joined(separator: ", "))")
    }

    @Test("the catalog is not empty")
    func catalogHasContent() throws {
        #expect(try catalog().strings.count > 50)
    }
}
