import Testing
import Foundation
@testable import WatchStreamer

@Suite("Capture mode in the poll")
struct CaptureModeTests {

    @Test func focusPollCarriesModeAndStart() {
        let poll: [String: Any] = [
            WatchPayloadKey.Status.captureMode: "focus",
            WatchPayloadKey.Status.focusStartedAtMs: Int64(1_724_000_000_000),
        ]
        #expect(CaptureMode.from(poll: poll) == .focus)
        #expect(CaptureMode.focusStartedAtMs(poll: poll) == 1_724_000_000_000)
    }

    /// Why: a study recording must never be mistaken for a focus session —
    /// resuming one would let the consumer feature end a proband run.
    @Test func recordingIsNotFocus() {
        let poll: [String: Any] = [WatchPayloadKey.Status.captureMode: "recording"]
        #expect(CaptureMode.from(poll: poll) == .recording)
        #expect(CaptureMode.focusStartedAtMs(poll: poll) == nil)
    }

    /// An older Watch build sends no mode at all. It must read as idle, not
    /// crash and not resume.
    @Test func missingModeIsIdle() {
        #expect(CaptureMode.from(poll: [:]) == .idle)
    }

    @Test func unknownModeIsIdle() {
        let poll: [String: Any] = [WatchPayloadKey.Status.captureMode: "banana"]
        #expect(CaptureMode.from(poll: poll) == .idle)
    }
}
