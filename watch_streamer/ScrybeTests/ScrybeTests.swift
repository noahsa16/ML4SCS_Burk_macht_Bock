import Testing
@testable import WatchStreamer

@Suite("Scrybe test target smoke")
struct SmokeTests {
    @Test("target runs and app module imports")
    func targetRuns() {
        #expect(Bool(true))
    }
}
