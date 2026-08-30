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

    // MARK: - Keys the source uses but the catalog does not hold

    /// Every string literal the Scrybe screens hand to `Text`, `Label`,
    /// `String(localized:)` or `.accessibilityLabel`, with its file and line.
    ///
    /// Two deliberate exclusions, both of which would otherwise report
    /// literals that are not catalog keys at all:
    /// - anything containing a backslash. An interpolated literal becomes a
    ///   key with format specifiers (`"\(minutes) Min"` → `"%lld Min"`), and
    ///   deriving those from source would mean re-implementing the compiler's
    ///   type-to-specifier mapping.
    /// - whitespace-only literals, which are layout spacers rather than copy
    ///   (`Text(" ").hidden()`).
    ///
    /// Scoped to `Scrybe/`: the Admin panel behind the PIN is an operator
    /// surface that is German only by design, and the English override the
    /// Profile screen offers does not claim to translate it.
    private func literalsInSource(file: StaticString = #filePath) throws -> [(key: String, site: String)] {
        let root = URL(fileURLWithPath: "\(file)")
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("WatchStreamer/Scrybe")
        let patterns = try [
            #"\bText\(\s*"((?:[^"\\]|\\.)*)""#,
            #"\bLabel\(\s*"((?:[^"\\]|\\.)*)""#,
            #"String\(\s*localized:\s*"((?:[^"\\]|\\.)*)""#,
            #"accessibilityLabel\(\s*"((?:[^"\\]|\\.)*)""#,
        ].map { try NSRegularExpression(pattern: $0) }

        let files = try #require(
            FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil),
            "no source tree at \(root.path)")
        var found: [(key: String, site: String)] = []
        for case let url as URL in files where url.pathExtension == "swift" {
            let source = try String(contentsOf: url, encoding: .utf8)
            // Comment lines are dropped rather than parsed: a documentation
            // comment quoting `Text("…")` is prose, not a key in use.
            let lines = source.components(separatedBy: "\n")
            for (index, line) in lines.enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                let range = NSRange(line.startIndex..<line.endIndex, in: line)
                for pattern in patterns {
                    for match in pattern.matches(in: line, range: range) {
                        guard let captured = Range(match.range(at: 1), in: line) else { continue }
                        let key = String(line[captured])
                        guard !key.contains("\\"),
                              !key.trimmingCharacters(in: .whitespaces).isEmpty else { continue }
                        found.append((key, "\(url.lastPathComponent):\(index + 1)"))
                    }
                }
            }
        }
        return found
    }

    // The gate the suite above cannot be: validating only the keys the catalog
    // already holds passes a *missing* key by construction, which is how
    // "Schreibseite dieser Sitzung" shipped untranslated.
    @Test("every literal the screens use exists in the catalog")
    func everySourceKeyIsInTheCatalog() throws {
        let keys = try catalog().strings.keys
        let literals = try literalsInSource()
        #expect(literals.count > 40, "the source scan found almost nothing — check the paths")

        let missing = literals
            .filter { !keys.contains($0.key) }
            .map { "\($0.site) \"\($0.key)\"" }
            .sorted()
        #expect(missing.isEmpty,
                "keys used in source but absent from the catalog: \(missing.joined(separator: ", "))")
    }
}
