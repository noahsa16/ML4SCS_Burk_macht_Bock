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

    // The stop direction, and the damaging one. A study recording preempts a
    // running focus session on the Watch and tells the phone nothing, so the
    // phone still holds a session it believes is live — and sends focus_stop
    // when the user taps "Beenden", or unprompted when its own hour cap
    // fires. focus_stop calls stop(), which ends whatever is capturing.
    @Test("focus_stop is refused while a recording runs")
    func focusStopRefusedDuringRecording() {
        let reply = FocusCommandPolicy.replyForStop(hasFocusSession: false,
                                                    isRecording: true)
        #expect(reply.ok == false)
        #expect(reply.error == FocusStopRefusal.recordingInProgress.rawValue)
    }

    // A session already ended — by the Watch's own cap, or by an earlier
    // stop. Nothing to stop, and answering ok would claim otherwise.
    @Test("focus_stop is refused when nothing is running")
    func focusStopRefusedWhenIdle() {
        let reply = FocusCommandPolicy.replyForStop(hasFocusSession: false,
                                                    isRecording: false)
        #expect(reply.ok == false)
        #expect(reply.error == FocusStopRefusal.noFocusSession.rawValue)
    }

    @Test("focus_stop is obeyed for a running focus session")
    func focusStopObeyedForItsOwnSession() {
        let reply = FocusCommandPolicy.replyForStop(hasFocusSession: true,
                                                    isRecording: true)
        #expect(reply.ok)
        #expect(reply.error == nil)
    }
}

// A refusal is a definite answer — the Watch checked and reported that no
// focus session holds its sensors, which is exactly what the stop asked it to
// establish. Only silence leaves the sensor stream in doubt, and only that
// may reach the user as "the stop was not confirmed".
@Suite("Reading a focus_stop reply")
struct FocusStopOutcomeTests {

    @Test("an ok reply is a stop")
    func okIsStopped() {
        let outcome = FocusStopOutcome.from(reply: [WatchPayloadKey.ok: true])
        #expect(outcome == .stopped)
        #expect(outcome.focusSessionIsStopped)
    }

    @Test("every named refusal still confirms no focus session is streaming",
          arguments: FocusStopRefusal.allCases)
    func refusalConfirmsNoSession(_ refusal: FocusStopRefusal) {
        let outcome = FocusStopOutcome.from(reply: [WatchPayloadKey.ok: false,
                                                    WatchPayloadKey.error: refusal.rawValue])
        #expect(outcome == .refused(refusal))
        #expect(outcome.focusSessionIsStopped)
    }

    // A refusal this build cannot name, or no reply at all: the Watch may
    // still be streaming, and saying otherwise would be a guess.
    @Test("an unrecognised refusal leaves the stream in doubt")
    func unknownRefusalIsNoAnswer() {
        let outcome = FocusStopOutcome.from(reply: [WatchPayloadKey.ok: false,
                                                    WatchPayloadKey.error: "something new"])
        #expect(outcome == .noAnswer)
        #expect(!outcome.focusSessionIsStopped)
    }

    @Test("an empty reply leaves the stream in doubt")
    func emptyReplyIsNoAnswer() {
        #expect(FocusStopOutcome.from(reply: [:]) == .noAnswer)
    }
}

// The precedence rule for what rate a study recording's own "start" should
// apply. This is the piece that already produced a bug once: an unconditional
// restore of a saved focus-session rate clobbered an explicit rate sent in
// the very same message.
@Suite("Recording-start rate precedence")
struct RecordingStartRatePrecedenceTests {

    // The phone's live setting, carried by this exact message, must win over
    // a stale rate saved from an ended focus session — that stale value could
    // be older than the message's own request.
    @Test("an explicit rate wins over a pending focus-session restore")
    func explicitRateWinsOverRestore() {
        let resolved = FocusCommandPolicy.resolveRateForStart(explicitHz: 80,
                                                              preFocusHz: 100,
                                                              currentHz: 50)
        #expect(resolved.hz == 80)
        #expect(resolved.preFocusHz == nil)
    }

    // No explicit rate in this message: fall back to the rate a focus session
    // had saved before it started, rather than leaving the focus session's
    // 50 Hz in place for the new recording.
    @Test("a pending restore applies when no explicit rate is given")
    func restoreAppliesWithoutExplicitRate() {
        let resolved = FocusCommandPolicy.resolveRateForStart(explicitHz: nil,
                                                              preFocusHz: 100,
                                                              currentHz: 50)
        #expect(resolved.hz == 100)
        #expect(resolved.preFocusHz == nil)
    }

    // Neither signal present: nothing to reconcile, so the current rate must
    // pass through unchanged rather than being reset to some default.
    @Test("neither explicit rate nor pending restore is a no-op")
    func noSignalsIsNoOp() {
        let resolved = FocusCommandPolicy.resolveRateForStart(explicitHz: nil,
                                                              preFocusHz: nil,
                                                              currentHz: 100)
        #expect(resolved.hz == 100)
        #expect(resolved.preFocusHz == nil)
    }

    // An explicit rate outside CaptureSettings.hzRange (10...200) is the same
    // malformed-payload case applyMotionConfig already guards against — it
    // must not silently apply, but fall through to whatever a pending restore
    // would have produced.
    @Test("an out-of-range explicit rate falls back to a pending restore")
    func invalidExplicitRateFallsBackToRestore() {
        let resolved = FocusCommandPolicy.resolveRateForStart(explicitHz: 999,
                                                              preFocusHz: 100,
                                                              currentHz: 50)
        #expect(resolved.hz == 100)
        #expect(resolved.preFocusHz == nil)
    }
}
