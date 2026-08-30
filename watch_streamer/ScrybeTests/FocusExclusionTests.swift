import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus and recording are exclusive")
struct FocusExclusionTests {

    // Both claim the same sensor stream and the same HKWorkoutSession, and
    // MotionManager deliberately never ends its own.
    @Test("focus_start is refused while a recording runs")
    func focusRefusedDuringRecording() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: true,
                                                     healthKitAuthorized: true)
        #expect(reply.ok == false)
        #expect(reply.error?.isEmpty == false)
    }

    // Without the workout session the stream dies when the wrist lowers, so
    // starting anyway would fail silently halfway through a session.
    @Test("focus_start is refused without workout permission")
    func focusRefusedWithoutHealthKit() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: false,
                                                     healthKitAuthorized: false)
        #expect(reply.ok == false)
    }

    @Test("focus_start is accepted when idle and requests 50 Hz")
    func focusAcceptedWhenIdle() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: false,
                                                     healthKitAuthorized: true)
        #expect(reply.ok)
        #expect(reply.requestedHz == 50)
    }
}
