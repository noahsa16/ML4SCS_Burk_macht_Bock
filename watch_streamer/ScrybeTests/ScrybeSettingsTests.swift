import Testing
import Foundation
@testable import WatchStreamer

@Suite("Scrybe settings keys")
struct ScrybeSettingsTests {

    /// Why: the focus duration is not the daily goal. Sharing a key would let
    /// picking a 25-minute session rewrite the day's target.
    @Test func focusDurationHasItsOwnKey() {
        #expect(ScrybeSettings.focusDurationKey != ScrybeSettings.goalKey)
        #expect(ScrybeSettings.defaultFocusMinutes == 25)
    }

    /// "Delete all local data" must mean it. A key left behind is the class of
    /// mismatch between promise and storage that the privacy pass closed.
    @Test func focusDurationIsErasedByReset() {
        #expect(ScrybeSettings.resettableKeys.contains(ScrybeSettings.focusDurationKey))
    }
}
