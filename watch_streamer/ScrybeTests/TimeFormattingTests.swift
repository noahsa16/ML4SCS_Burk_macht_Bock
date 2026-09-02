import Testing
import Foundation
@testable import WatchStreamer

@Suite("TimeFormatting")
struct TimeFormattingTests {
    @Test("clock formats hours:minutes", arguments: [
        (6420.0, "1:47"), (0.0, "0:00"), (59.0, "0:00"), (3600.0, "1:00"),
    ])
    func clock(seconds: Double, expected: String) {
        #expect(TimeFormatting.clock(seconds: seconds) == expected)
    }

    @Test("human formats compactly", arguments: [
        (6420.0, "1h 47m"), (2820.0, "47m"), (0.0, "0m"), (7200.0, "2h 0m"),
    ])
    func human(seconds: Double, expected: String) {
        #expect(TimeFormatting.human(seconds: seconds) == expected)
    }

    @Test("abbreviated follows the locale", arguments: [
        ("de", 1500.0, "25 Min."), ("en", 1500.0, "25 min"),
    ])
    func abbreviated(locale: String, seconds: Double, expected: String) {
        #expect(TimeFormatting.abbreviated(seconds: seconds,
                                           locale: Locale(identifier: locale)) == expected)
    }

    @Test("abbreviated drops seconds and never goes negative")
    func abbreviatedEdges() {
        let de = Locale(identifier: "de")
        #expect(TimeFormatting.abbreviated(seconds: 1559, locale: de) == "25 Min.")
        #expect(TimeFormatting.abbreviated(seconds: -5, locale: de) == "0 Min.")
    }
}
