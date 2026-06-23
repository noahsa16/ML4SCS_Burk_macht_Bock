import Testing
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
}
