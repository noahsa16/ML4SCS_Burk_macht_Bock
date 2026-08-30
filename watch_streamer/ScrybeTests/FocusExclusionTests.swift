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

// `currentWatchCommandPayload()` builds a bare `stop` — no `session_id` field
// at all — whenever no *study* session is active, which is the whole duration
// of every focus session. It reaches the Watch two ways, and both bypass the
// stale-session guard: as the reply to the 1 Hz poll (which skips the guard
// deliberately), and as a push on every return to the foreground, where the
// guard's comparison is `nil != nil` and admits it. Either one ended the
// session silently: capture stopped, the writing page never grew, and the
// user's own "Beenden" came back "no focus session".
@Suite("A study stop and a focus session")
struct PolledStopTests {

    /// The reply `currentWatchCommandPayload()` builds with no study session
    /// running, stamped by `handleWatchCommandPoll` on its way back.
    private func polledStop(sessionID: String? = nil) -> [String: Any] {
        var message: [String: Any] = [WatchPayloadKey.command: WatchCommandName.stop.rawValue,
                                      WatchPayloadKey.ok: true,
                                      WatchPayloadKey.source: WatchCommandSource.commandPoll,
                                      WatchPayloadKey.requestedHz: 100.0]
        if let sessionID { message[WatchPayloadKey.sessionID] = sessionID }
        return message
    }

    /// A `stop` the phone pushed. With `sessionID` nil this is what
    /// `refreshWatchContext()` sends on every return to the foreground:
    /// `watchPayload` omits the field entirely when there is no session.
    private func pushedStop(sessionID: String? = nil) -> [String: Any] {
        var message: [String: Any] = [WatchPayloadKey.command: WatchCommandName.stop.rawValue,
                                      WatchPayloadKey.requestedHz: 100.0]
        if let sessionID { message[WatchPayloadKey.sessionID] = sessionID }
        return message
    }

    private func admit(_ message: [String: Any],
                       hasFocusSession: Bool,
                       isRunning: Bool = true,
                       runningSessionID: String?) -> FocusCommandPolicy.StopAdmission {
        FocusCommandPolicy.admitStop(
            fromPoll: WatchCommandSource.isCommandPoll(message),
            hasFocusSession: hasFocusSession,
            isRunning: isRunning,
            commandSessionID: message[WatchPayloadKey.sessionID] as? String,
            runningSessionID: runningSessionID)
    }

    // Only the poll stamps `source`, and only that stamp separates a reply
    // that cannot be stale from a push that can sit in the FIFO for minutes.
    @Test("the poll's stamp is what tells the two apart")
    func onlyThePollIsStamped() {
        #expect(WatchCommandSource.isCommandPoll(polledStop()))
        #expect(!WatchCommandSource.isCommandPoll(pushedStop(sessionID: "S042")))
    }

    // The blocker. A focus session is running; the poll says "stop" because no
    // study session is. Obeying it ends the session the user just started.
    @Test("a polled stop does not end a focus session")
    func polledStopSparesFocusSession() {
        #expect(admit(polledStop(), hasFocusSession: true, runningSessionID: nil)
                == .ignoreFocusSession)
    }

    // The behaviour the skipped stale guard exists for, unchanged: a study
    // recording whose "stop" push was lost is still recovered by the poll.
    @Test("a polled stop still ends a study recording")
    func polledStopStillEndsRecording() {
        #expect(admit(polledStop(), hasFocusSession: false, runningSessionID: "S042")
                == .obey)
    }

    // A pushed stop naming another session stays refused — a minutes-old
    // stop/start pair from the durable FIFO once cost three minutes of a
    // recording (S044).
    @Test("a pushed stop naming another session is still refused")
    func pushedStaleStopStillRefused() {
        #expect(admit(pushedStop(sessionID: "S041"), hasFocusSession: false,
                      runningSessionID: "S042") == .ignoreStaleSession)
    }

    @Test("a pushed stop naming the running session is obeyed")
    func pushedMatchingStopObeyed() {
        #expect(admit(pushedStop(sessionID: "S042"), hasFocusSession: false,
                      runningSessionID: "S042") == .obey)
    }

    // The second door, and the one that reopened after the poll was closed:
    // every return to the foreground pushes this exact payload, and the stale
    // guard compares `nil != nil` and admits it. A focus session ended
    // whenever the user picked the phone back up.
    @Test("a pushed stop naming no session does not end a focus session")
    func pushedBareStopSparesFocusSession() {
        #expect(admit(pushedStop(), hasFocusSession: true, runningSessionID: nil)
                == .ignoreFocusSession)
    }

    // The same message with the field present but empty — `watchPayload`
    // treats an empty id as no id, and so must this.
    @Test("an empty session id does not name a session")
    func emptySessionIDIsNotANamedStop() {
        #expect(admit(pushedStop(sessionID: ""), hasFocusSession: true,
                      runningSessionID: nil) == .ignoreFocusSession)
    }

    // The property is about the command, not its delivery: a stop that does
    // name a session cannot reach a focus session either, whichever path it
    // came by.
    @Test("a polled stop naming a session does not end a focus session")
    func polledNamedStopSparesFocusSession() {
        #expect(admit(polledStop(sessionID: "S042"), hasFocusSession: true,
                      runningSessionID: nil) == .ignoreFocusSession)
    }

    // Unchanged by the new guard, and the reason it is scoped to focus
    // sessions: a bare push while a recording runs was already refused by the
    // stale guard, and a bare push with nothing to protect is still obeyed.
    @Test("a pushed stop naming no session is still refused during a recording")
    func pushedBareStopStillRefusedDuringRecording() {
        #expect(admit(pushedStop(), hasFocusSession: false, runningSessionID: "S042")
                == .ignoreStaleSession)
    }

    @Test("a pushed stop naming no session is obeyed when nothing is running")
    func pushedBareStopObeyedWhenIdle() {
        #expect(admit(pushedStop(), hasFocusSession: false, isRunning: false,
                      runningSessionID: nil) == .obey)
    }
}

// A study recording outranks a focus session, so its `start` preempts one.
// The poll is the path that had to be reasoned about twice: it must never
// stop and restart a running *recording* (a poll reply is built off-main from
// a `currentSessionId` that can lag seconds behind), but before the focus
// session survived the poll's stray `stop` it was gone within a second and a
// polled `start` simply found the Watch idle. With the session now
// persisting, a poll that could not preempt would be inert for as long as one
// runs — losing the lost-push recovery the poll path exists for.
@Suite("A study start reaching a busy Watch")
struct StartPreemptionTests {

    private func mayPreempt(fromPoll: Bool,
                            hasFocusSession: Bool = false,
                            isRunning: Bool = true,
                            commandSessionID: String? = "S042",
                            runningSessionID: String? = nil) -> Bool {
        FocusCommandPolicy.startMayPreempt(fromPoll: fromPoll,
                                           hasFocusSession: hasFocusSession,
                                           isRunning: isRunning,
                                           commandSessionID: commandSessionID,
                                           runningSessionID: runningSessionID)
    }

    // The contract the stop-side fix narrowed without saying so.
    @Test("a polled start preempts a focus session")
    func polledStartPreemptsFocusSession() {
        #expect(mayPreempt(fromPoll: true, hasFocusSession: true))
    }

    // Untouched: this is the "starts itself again" bug, where a poll reply
    // carrying a stale session id stopped and restarted a live recording.
    @Test("a polled start does not preempt a study recording")
    func polledStartSparesRecording() {
        #expect(!mayPreempt(fromPoll: true, runningSessionID: "S041"))
    }

    // A push can be trusted with a session change, which is why the stale
    // guard exists only for polls.
    @Test("a pushed start preempts a recording of another session")
    func pushedStartPreemptsRecording() {
        #expect(mayPreempt(fromPoll: false, runningSessionID: "S041"))
    }

    // Nothing to preempt: the recording this start names is the one already
    // running, so stopping it would only interrupt itself.
    @Test("a start naming the running session does not preempt it")
    func matchingStartIsNoPreemption() {
        #expect(!mayPreempt(fromPoll: false, runningSessionID: "S042"))
    }

    // A start with no session to record cannot claim the stream from anything.
    @Test("a start naming no session preempts nothing",
          arguments: [nil, ""] as [String?])
    func unnamedStartIsNoPreemption(_ sessionID: String?) {
        #expect(!mayPreempt(fromPoll: false, hasFocusSession: true,
                            commandSessionID: sessionID))
    }

    @Test("an idle Watch has nothing to preempt")
    func idleWatchIsNoPreemption() {
        #expect(!mayPreempt(fromPoll: false, isRunning: false))
    }
}

// Every message from the phone may carry `requested_hz`, and the reply to the
// Watch's own 1 Hz poll restates the phone's setting on every tick. A focus
// session states its own rate instead, and CoreMotion's interval is fixed once
// inside start() — so the poll's rate could not change what the sensor did, it
// could only make the record of it wrong.
@Suite("Applying a rate while a focus session runs")
struct FocusRateConfigTests {

    /// The `requested_hz` a poll reply carries: the phone's own setting, which
    /// a focus session has deliberately overridden with `sessionHz`.
    private let phoneSetting = 100.0
    private var sessionRate: Double { Double(FocusCommandPolicy.sessionHz) }

    // Why: `effectiveHz` describes the rate the sensor is actually running at,
    // not the rate the phone last asked for. Without the guard the poll
    // overwrote it about a second into every focus session, leaving a field
    // that reads like the truth and is not — inert only until something
    // legitimately re-enters start() mid-session.
    @Test("a poll's rate is not applied while a focus session runs")
    func focusSessionRateSurvivesThePoll() {
        #expect(FocusCommandPolicy.rateToApply(requestedHz: phoneSetting,
                                               currentHz: sessionRate,
                                               hasFocusSession: true) == nil)
    }

    // The ordinary path, unchanged: outside a focus session the phone's
    // setting is exactly what the Watch should adopt.
    @Test("a new rate applies when no focus session is running")
    func rateAppliesOutsideAFocusSession() {
        #expect(FocusCommandPolicy.rateToApply(requestedHz: phoneSetting,
                                               currentHz: sessionRate,
                                               hasFocusSession: false) == phoneSetting)
    }

    // The poll restates the same rate every second; only a change is a change.
    @Test("a rate equal to the running one is not a change")
    func unchangedRateIsNoChange() {
        #expect(FocusCommandPolicy.rateToApply(requestedHz: phoneSetting,
                                               currentHz: phoneSetting,
                                               hasFocusSession: false) == nil)
    }

    // A value outside CaptureSettings.hzRange is ignored rather than clamped,
    // so a malformed payload cannot quietly reconfigure a running study.
    @Test("an out-of-range rate is ignored", arguments: [0.0, 9.0, 201.0])
    func outOfRangeRateIsIgnored(_ hz: Double) {
        #expect(FocusCommandPolicy.rateToApply(requestedHz: hz,
                                               currentHz: sessionRate,
                                               hasFocusSession: false) == nil)
    }

    @Test("a message without a rate leaves the running one alone")
    func missingRateIsNoChange() {
        #expect(FocusCommandPolicy.rateToApply(requestedHz: nil,
                                               currentHz: sessionRate,
                                               hasFocusSession: false) == nil)
    }
}

// The Watch stops capturing when the workout session its stream depends on
// cannot run, and it does that alone: the phone kept a session it believed
// live, the page stopped growing with nothing said, and the `focus_stop` that
// followed was answered `no focus session` — which `FocusStopOutcome` reads as
// a *confirmed* stop. The flag was already on the wire; it had no reader.
@Suite("A workout failure the Watch reports")
struct WorkoutFailureNoticeTests {

    /// The poll snapshot the Watch sends after `handleWorkoutSessionFailure`:
    /// the flag set, capture ended, delivered as a live reply.
    private func failureSnapshot(fallback: Bool = false) -> [String: Any] {
        var message: [String: Any] = [WatchPayloadKey.type: "command_poll",
                                      WatchPayloadKey.Status.isRunning: false,
                                      WatchPayloadKey.Status.workoutFailed: true]
        if fallback { message[WatchPayloadKey.Status.fallback] = true }
        return message
    }

    private func endsSession(_ message: [String: Any]) -> Bool {
        FocusCommandPolicy.workoutFailureEndedFocusSession(
            workoutFailed: message[WatchPayloadKey.Status.workoutFailed] as? Bool ?? false,
            watchIsRunning: message[WatchPayloadKey.Status.isRunning] as? Bool ?? false,
            deliveredAsFallback: WatchCommandSource.isFallbackDelivery(message))
    }

    // The silence itself: this snapshot is the only thing that says the
    // session is over, and before it had a reader nothing did.
    @Test("a live poll reporting a failed workout ends the session")
    func liveFailureIsNews() {
        #expect(endsSession(failureSnapshot()))
    }

    // A queued copy can be minutes old. Acting on one would fail the session
    // the user just started with news about the previous one — the same
    // stale-delivery mistake the stop path guards against.
    @Test("a fallback delivery is not news")
    func fallbackDeliveryIsNotNews() {
        #expect(!endsSession(failureSnapshot(fallback: true)))
    }

    // The flag is also set when a *recording's* workout fails, and the Watch
    // clears it at the start of every focus session. A Watch that is still
    // capturing has not ended anything to report.
    @Test("a failure while the Watch still captures ends nothing")
    func stillRunningIsNotNews() {
        var message = failureSnapshot()
        message[WatchPayloadKey.Status.isRunning] = true
        #expect(!endsSession(message))
    }

    // The ordinary snapshot, once a second, for the whole of every healthy
    // session.
    @Test("a healthy poll ends nothing")
    func healthyPollIsNotNews() {
        var message = failureSnapshot()
        message[WatchPayloadKey.Status.workoutFailed] = false
        message[WatchPayloadKey.Status.isRunning] = true
        #expect(!endsSession(message))
    }

    // A poll from a Watch too old to carry the field, or a malformed one:
    // absent is not a failure.
    @Test("a snapshot without the field ends nothing")
    func missingFieldIsNotNews() {
        #expect(!endsSession([WatchPayloadKey.type: "command_poll"]))
    }
}
