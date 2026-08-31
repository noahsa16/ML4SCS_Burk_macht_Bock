import Foundation

/// The command vocabulary shared by the iPhone and the Watch.
///
/// This type exists because WatchConnectivity offers three transports with
/// different delivery semantics, and driving every command through one code
/// path made those semantics implicit:
///
/// - `sendMessage` is live request/response. It fails when the counterpart is
///   unreachable and is the only transport with a reply channel.
/// - `updateApplicationContext` keeps a single latest-state slot. Writing it
///   overwrites whatever recovery state was there.
/// - `transferUserInfo` is a durable FIFO. Entries survive unreachability and
///   can arrive minutes late.
///
/// Before this type, a read-only diagnostic query cancelled every queued
/// transfer and overwrote the application context on its way out, so a probe
/// report could erase pending start/stop recovery state. `transport` makes the
/// permitted delivery paths a property of the command itself.
public enum WatchCommandName: String, CaseIterable, Sendable {
    case start
    case stop
    case drainSpill = "drain_spill"
    case clearSpill = "clear_spill"
    case sensorProbeStart = "sensor_probe_start"
    case sensorProbeReport = "sensor_probe_report"
    case parityCheck = "parity_check"
    /// Run a retrieval cycle now and hand over pending decisions.
    case syncDecisions = "sync_decisions"
    /// Begin a focus session: switch the stream to 50 Hz and consume locally.
    case focusStart = "focus_start"
    /// End a focus session and restore the previous capture configuration.
    case focusStop = "focus_stop"
}

/// How a command may be delivered.
public enum WatchCommandTransport: Sendable {
    /// Durable recording state. Mirrored through every transport so a missed
    /// push is recovered from application context or the Watch's poll.
    case durableState
    /// A one-shot operation carrying its own identity. Delivered live only —
    /// a late duplicate must never re-trigger it.
    case idempotentOperation
    /// A read-only question whose whole value is the reply. Delivered live
    /// only; the Watch discards context and user-info copies, so queueing one
    /// as a fallback produces a delivery that is guaranteed to be ignored.
    case directQuery
}

extension WatchCommandName {
    public var transport: WatchCommandTransport {
        switch self {
        case .start, .stop:
            return .durableState
        case .drainSpill, .clearSpill, .sensorProbeStart, .syncDecisions, .focusStart, .focusStop:
            return .idempotentOperation
        case .sensorProbeReport, .parityCheck:
            return .directQuery
        }
    }

    /// Only durable state may overwrite the application-context slot or cancel
    /// the queued-command FIFO. Both are destructive to recovery state.
    public var mayReplaceDurableState: Bool {
        transport == .durableState
    }

    /// Only durable state may be re-sent through `transferUserInfo` when the
    /// live send fails. For every other class the queued copy would be
    /// discarded by the Watch, so promising the caller it was "queued" is a lie.
    public var mayFallBackToUserInfo: Bool {
        transport == .durableState
    }

    /// Commands the Watch must answer without entering the recording command
    /// dispatcher — they run off the main thread and must not touch capture
    /// configuration or recording state.
    public var isDiagnostic: Bool {
        switch self {
        case .sensorProbeStart, .sensorProbeReport, .parityCheck:
            return true
        case .start, .stop, .drainSpill, .clearSpill, .syncDecisions, .focusStart, .focusStop:
            return false
        }
    }

    /// Commands answered off the recording dispatcher: they run on a background
    /// queue and must not touch capture configuration or recording state.
    ///
    /// Broader than `isDiagnostic` since the passive sync and the focus
    /// commands join them — the passive sync may run a Core ML retrieval
    /// cycle, which would blow the phone's sendMessage timeout on the main
    /// thread, and focus start/stop must not race the dispatcher's own
    /// start/stop handling, but none of the three is a diagnostic.
    public var bypassesRecordingDispatcher: Bool {
        isDiagnostic || self == .syncDecisions || self == .focusStart || self == .focusStop
    }
}

/// Field keys for the WatchConnectivity payloads.
///
/// Previously spelled as literals on both sides, which had already produced
/// drift: the Watch's poll payload says `is_running` while its command reply
/// says `isRunning` for the same concept.
public enum WatchPayloadKey {
    public static let command = "command"
    public static let commandID = "command_id"
    public static let operationID = "operation_id"
    public static let sessionID = "session_id"
    public static let personID = "person_id"
    public static let serverIP = "server_ip"
    public static let source = "source"
    public static let type = "type"
    public static let ok = "ok"
    public static let error = "error"
    public static let requestedHz = "requested_hz"
    public static let batchSize = "batch_size"
    public static let durationSeconds = "duration_seconds"

    /// Envelope type for a batch of passive writing decisions travelling from
    /// the Watch to the phone. Sent over `transferUserInfo` because it is
    /// durable state that must survive the phone being out of range, and
    /// idempotent because each decision is keyed by its own start time.
    public static let passiveDecisionsType = "passive_decisions"
    public static let decisions = "decisions"
    /// Count of decisions the Watch handed over for a sync request.
    public static let pendingCount = "pending_count"

    /// Snake-case status fields, used in the Watch → iPhone poll payload.
    public enum Status {
        public static let isRunning = "is_running"
        public static let sampleCount = "sample_count"
        public static let queuedSamples = "queued_samples"
        public static let deliveredSamples = "delivered_samples"
        public static let spilledSamples = "spilled_samples"
        public static let failedBatches = "failed_batches"
        public static let lastCommandID = "last_command_id"
        public static let uploadMode = "upload_mode"
        /// The Watch could not run the workout session its capture depends on.
        public static let workoutFailed = "workout_failed"
        /// Stamped on the copy the Watch queues over `transferUserInfo` when a
        /// poll's reply handler failed. That copy is durable, so it can be
        /// delivered minutes late — anything that reads a poll as *news* has
        /// to know which of the two it is holding.
        public static let fallback = "fallback"
        /// What the Watch's sensors are doing right now. `is_running` cannot
        /// answer this: it is true for a study recording and for a focus
        /// session alike, and resuming the wrong one would end a proband run.
        public static let captureMode = "capture_mode"
        /// Unix ms the focus session began, present only when `capture_mode`
        /// is `focus`. The phone holds no copy — the store is in-memory on
        /// purpose — so this is the only way back after a force-quit.
        public static let focusStartedAtMs = "focus_started_at_ms"
    }

    /// Camel-case reply fields, used in the Watch's command replies. Kept
    /// distinct from `Status` rather than unified, because the server's
    /// `watch_ack` schema already consumes these names.
    public enum Reply {
        public static let isRunning = "isRunning"
        public static let sampleCount = "sampleCount"
        public static let uploadMode = "uploadMode"
    }
}

/// What the Watch's sensors are doing, as read from a poll reply.
public nonisolated enum CaptureMode: String, Sendable, CaseIterable {
    case idle
    case recording
    case focus

    /// Why idle on anything unrecognised: an older Watch build sends no mode,
    /// and a build that sends one this app does not know is not a session this
    /// app may adopt.
    public static func from(poll: [String: Any]) -> CaptureMode {
        guard let raw = poll[WatchPayloadKey.Status.captureMode] as? String,
              let mode = CaptureMode(rawValue: raw) else { return .idle }
        return mode
    }

    public static func focusStartedAtMs(poll: [String: Any]) -> Int64? {
        guard from(poll: poll) == .focus else { return nil }
        return WatchPayloadValue.int64(poll[WatchPayloadKey.Status.focusStartedAtMs])
    }
}

/// Where a command reached the Watch from.
///
/// The Watch polls the phone once a second and feeds the reply into the same
/// `handleCommand` path a pushed command takes, but the two have opposite
/// staleness properties: a poll reply is synchronous and current, a pushed
/// one can sit in the `transferUserInfo` FIFO for minutes. Several decisions
/// turn on the difference, so the reply says which it is.
public nonisolated enum WatchCommandSource {
    /// The `source` value the phone stamps on a reply to `command_poll`.
    public static let commandPoll = "iphone_command_poll"

    public static func isCommandPoll(_ message: [String: Any]) -> Bool {
        (message[WatchPayloadKey.source] as? String) == commandPoll
    }

    /// Whether this Watch → phone poll snapshot came by the durable queue
    /// rather than as a live reply. The same staleness split as above, in the
    /// other direction: the Watch queues a copy over `transferUserInfo` when
    /// the reply handler failed, and that copy can arrive minutes later.
    public static func isFallbackDelivery(_ message: [String: Any]) -> Bool {
        (message[WatchPayloadKey.Status.fallback] as? Bool) ?? false
    }
}

/// Why the Watch refused a focus session.
///
/// The raw values are the strings that travel on the wire, so the phone can
/// turn a refusal back into something it can say in the user's language. The
/// two cases mean opposite things to a user — wait, versus grant a permission
/// — and collapsing them into one message throws away the only actionable
/// half of the answer.
public nonisolated enum FocusStartRefusal: String, Sendable, CaseIterable {
    case recordingInProgress = "recording in progress"
    case workoutPermissionMissing = "workout permission missing"
}

/// What came back from a `focus_start`.
public nonisolated enum FocusStartOutcome: Equatable, Sendable {
    case started
    case refused(FocusStartRefusal)
    /// No usable answer: the deadline passed, the transport failed, or the
    /// Watch refused for a reason this build does not recognise.
    case noAnswer

    /// Reads the Watch's reply. Lives here rather than in the caller so the
    /// decode is testable without WatchConnectivity.
    public static func from(reply: [String: Any]) -> FocusStartOutcome {
        guard WatchPayloadValue.bool(reply[WatchPayloadKey.ok]) ?? false else {
            let raw = reply[WatchPayloadKey.error] as? String ?? ""
            guard let refusal = FocusStartRefusal(rawValue: raw) else { return .noAnswer }
            return .refused(refusal)
        }
        return .started
    }
}

/// Why the Watch refused a `focus_stop`.
///
/// Both cases assert the same fact the caller needs — no focus session holds
/// the Watch's sensors — but they say different things about what does. The
/// first is the dangerous one: a study recording preempted the session
/// without the phone hearing about it, and `focus_stop` would otherwise end a
/// proband recording mid-run.
public nonisolated enum FocusStopRefusal: String, Sendable, CaseIterable {
    case recordingInProgress = "recording in progress"
    case noFocusSession = "no focus session"
}

/// What came back from a `focus_stop`.
public nonisolated enum FocusStopOutcome: Equatable, Sendable {
    case stopped
    case refused(FocusStopRefusal)
    /// No usable answer: the deadline passed, the transport failed, or the
    /// Watch refused for a reason this build does not recognise.
    case noAnswer

    /// Whether the answer establishes that no focus session is streaming.
    /// A refusal does establish it — the Watch checked and said so — which is
    /// the whole question the caller asked. Only silence leaves it open.
    public var focusSessionIsStopped: Bool {
        switch self {
        case .stopped, .refused: return true
        case .noAnswer: return false
        }
    }

    public static func from(reply: [String: Any]) -> FocusStopOutcome {
        guard WatchPayloadValue.bool(reply[WatchPayloadKey.ok]) ?? false else {
            let raw = reply[WatchPayloadKey.error] as? String ?? ""
            guard let refusal = FocusStopRefusal(rawValue: raw) else { return .noAnswer }
            return .refused(refusal)
        }
        return .stopped
    }
}

/// Whether a focus session may start, and at what rate.
///
/// Split out of `MotionManager` because the decision is the part worth testing
/// and CoreMotion cannot run in a unit test.
public nonisolated enum FocusCommandPolicy {
    public struct StartReply: Equatable {
        public let ok: Bool
        public let error: String?
        public let requestedHz: Int
    }

    /// The shipped active model was trained on 50 Hz and never saw 100 Hz, so a
    /// session states the rate rather than resampling into it afterwards.
    public static let sessionHz = 50

    /// Longest a focus session may stream before it is ended.
    ///
    /// Shared rather than defined twice because both ends enforce it: the phone
    /// for the clean stop, the Watch as the floor under it. A force-quit voids
    /// every phone-side path while the workout session keeps the sensors
    /// running, so the cap also has to live where the sensor does.
    public static let sessionCapSeconds: TimeInterval = 60 * 60

    public static func replyForStart(isRecording: Bool,
                                     healthKitAuthorized: Bool) -> StartReply {
        guard !isRecording else {
            return StartReply(ok: false,
                              error: FocusStartRefusal.recordingInProgress.rawValue,
                              requestedHz: 0)
        }
        // Why refused rather than attempted: without a workout session the
        // motion stream stops as soon as the wrist lowers, and the page would
        // quietly stop growing mid-session with no visible cause.
        guard healthKitAuthorized else {
            return StartReply(ok: false,
                              error: FocusStartRefusal.workoutPermissionMissing.rawValue,
                              requestedHz: 0)
        }
        return StartReply(ok: true, error: nil, requestedHz: sessionHz)
    }

    public struct StopReply: Equatable {
        public let ok: Bool
        public let error: String?
    }

    /// Whether a `focus_stop` may be obeyed.
    ///
    /// `focus_stop` calls `stop()`, which ends whatever the Watch is
    /// capturing — it is not scoped to focus sessions by anything but this
    /// check. A study recording preempts a running focus session and tells
    /// the phone nothing, so the phone can still send `focus_stop` long
    /// after: when the user taps "Beenden", or with no user action at all
    /// when its own session cap fires up to an hour later. Obeying that would
    /// end a proband recording mid-run, and answering `ok` would hide it.
    ///
    /// The Watch is the only side that knows what it is running, so the
    /// decision belongs here.
    public static func replyForStop(hasFocusSession: Bool,
                                    isRecording: Bool) -> StopReply {
        guard !hasFocusSession else { return StopReply(ok: true, error: nil) }
        let refusal: FocusStopRefusal = isRecording ? .recordingInProgress : .noFocusSession
        return StopReply(ok: false, error: refusal.rawValue)
    }

    /// What the Watch does with a study-vocabulary `stop`.
    public enum StopAdmission: Equatable, Sendable {
        /// End whatever is running.
        case obey
        /// A pushed stop naming a session other than the running one — it can
        /// have sat in the durable FIFO for minutes.
        case ignoreStaleSession
        /// A stop that names no session, or a polled one, while a focus
        /// session holds the sensors.
        case ignoreFocusSession
    }

    /// Whether a study `stop` may end what the Watch is currently running.
    ///
    /// The phone builds a `stop` from a nil `currentSessionId` whenever no
    /// *study* session is active, and a focus session is not a study session —
    /// so a bare `stop` goes out throughout every focus session. It reaches
    /// the Watch by two paths that both bypass the stale-session guard: the
    /// reply to the 1 Hz `command_poll` (which skips the guard deliberately,
    /// a synchronous reply cannot be stale), and every pushed
    /// `refreshWatchContext()` — sent on each return to the foreground —
    /// whose missing `session_id` makes the guard's comparison `nil != nil`.
    /// Either one ended the session silently: capture stopped, the page never
    /// grew, and the user's own "Beenden" came back `no focus session`.
    ///
    /// So the rule is about the command, not its delivery: a `stop` that
    /// names no session names nothing the Watch could mean by it while a
    /// focus session runs, and may not end one. A `stop` that *does* name a
    /// session is aimed at a study recording and is judged exactly as before
    /// — during a focus session `runningSessionID` is nil, so the stale guard
    /// already refuses it. A focus session's own end comes from `focus_stop`,
    /// from the Watch's session cap, or from a study recording starting.
    ///
    /// A polled stop still ends a study *recording*: that is the lost-push
    /// recovery the poll path exists for.
    public static func admitStop(fromPoll: Bool,
                                 hasFocusSession: Bool,
                                 isRunning: Bool,
                                 commandSessionID: String?,
                                 runningSessionID: String?) -> StopAdmission {
        let namesASession = !(commandSessionID ?? "").isEmpty
        if hasFocusSession, fromPoll || !namesASession {
            return .ignoreFocusSession
        }
        if fromPoll {
            return .obey
        }
        if isRunning, commandSessionID != runningSessionID {
            return .ignoreStaleSession
        }
        return .obey
    }

    /// Whether a Watch status snapshot is news that a workout failure ended a
    /// focus session.
    ///
    /// The Watch stops capturing when the workout session its stream depends
    /// on cannot run — HealthKit unavailable, or the authorization prompt
    /// denied after `focus_start` was already answered `ok`. That ending is
    /// correct; its silence was not. The phone kept a session it believed
    /// live, so the page stopped growing with nothing said, and the user's
    /// later `focus_stop` was answered `no focus session` — which
    /// `FocusStopOutcome` reads as a *confirmed* stop.
    ///
    /// The fact already travels: the poll payload has carried
    /// `workout_failed` since before this, and the Watch clears it at the
    /// start of every focus session, so a `true` is about the session running
    /// now. What it needed was a reader.
    ///
    /// Two conditions beyond the flag. `watchIsRunning` must be false — a
    /// workout that failed while the stream survives has not ended anything
    /// to report. And the snapshot must not be a fallback delivery: a queued
    /// copy can be minutes old, and failing a session the user just started
    /// with news about the previous one is the same stale-delivery mistake
    /// this file guards against for `stop`.
    public static func workoutFailureEndedFocusSession(workoutFailed: Bool,
                                                       watchIsRunning: Bool,
                                                       deliveredAsFallback: Bool) -> Bool {
        workoutFailed && !watchIsRunning && !deliveredAsFallback
    }

    /// Whether a study `start` may end what the Watch is running to take the
    /// stream for the recording it names.
    ///
    /// A study recording outranks a focus session and preempts it rather than
    /// losing to it — the opposite of `focus_start`, which refuses while a
    /// recording runs. `fromPoll` is what protects a running *recording* from
    /// being stopped and restarted by a poll reply built off-main from a
    /// seconds-stale `currentSessionId` (the "starts itself again" bug), and
    /// that protection is unchanged.
    ///
    /// It does not extend to focus sessions. Before a focus session survived
    /// the poll's stray `stop`, it was gone within a second and a later
    /// polled `start` simply found the Watch idle; now the session persists,
    /// and without this a polled `start` would be inert for as long as one
    /// runs — the poll's documented recovery role, silently narrowed. A focus
    /// session carries no `serverSessionId` and nothing stale can be said
    /// about it, so a poll may preempt one.
    public static func startMayPreempt(fromPoll: Bool,
                                       hasFocusSession: Bool,
                                       isRunning: Bool,
                                       commandSessionID: String?,
                                       runningSessionID: String?) -> Bool {
        guard isRunning,
              let sessionID = commandSessionID, !sessionID.isEmpty,
              sessionID != runningSessionID
        else { return false }
        return !fromPoll || hasFocusSession
    }

    /// The capture rate a configuration push should apply, or nil to leave the
    /// running one alone.
    ///
    /// Every message from the phone may carry `requested_hz`, including the
    /// reply to the Watch's own 1 Hz poll, which restates the phone's setting
    /// on every tick. A focus session states its rate instead
    /// (`sessionHz`), and CoreMotion's interval is fixed once inside
    /// `start()` — so applying the poll's rate mid-session did not change what
    /// the sensor did, it only made `effectiveHz` disagree with it about a
    /// second into every session. Refusing the change keeps the field's
    /// meaning intact: the rate the sensor is actually running at, not the
    /// rate the phone last asked for.
    ///
    /// `preFocusHz` is unaffected — it is captured before the session sets
    /// `sessionHz` and is what `restorePreFocusRateIfNeeded()` puts back. A
    /// rate the phone changed during a session is simply applied by the next
    /// poll once the session ends.
    public static func rateToApply(requestedHz: Double?,
                                   currentHz: Double,
                                   hasFocusSession: Bool) -> Double? {
        guard !hasFocusSession else { return nil }
        guard let requestedHz, CaptureSettings.isValidHz(requestedHz),
              requestedHz != currentHz
        else { return nil }
        return requestedHz
    }

    /// Resolves the capture rate for a study recording's own "start", given
    /// three possibly-present rate signals with a fixed precedence.
    ///
    /// 1. An explicit, valid rate carried by this exact message wins — it is
    ///    the phone's live setting, sent with every study "start"
    ///    (`ServerCommandListener.watchPayload`), and more authoritative than
    ///    anything saved earlier.
    /// 2. Otherwise, a still-pending focus-session rate (`preFocusHz`) is
    ///    restored — a study recording must never inherit an active focus
    ///    session's 50 Hz.
    /// 3. Otherwise, the current rate is left untouched.
    ///
    /// Pure and framework-free on purpose: this precedence is the one piece
    /// of the whole focus/recording interaction subtle enough to have
    /// produced a bug on first writing (an unconditional restore clobbered an
    /// explicit rate sent in the same message), so it needs to be testable
    /// without `MotionManager`, CoreMotion, or HealthKit.
    public static func resolveRateForStart(explicitHz: Double?,
                                           preFocusHz: Double?,
                                           currentHz: Double) -> (hz: Double, preFocusHz: Double?) {
        if let explicitHz, CaptureSettings.isValidHz(explicitHz) {
            return (explicitHz, nil)
        }
        if let preFocusHz {
            return (preFocusHz, nil)
        }
        return (currentHz, preFocusHz)
    }
}

/// Tolerant numeric coercion for values crossing a WatchConnectivity or JSON
/// round trip, which may surface a number as `Int`, `Int64`, `Double`, `NSNumber`
/// or `String` depending on transport. Was implemented three times with
/// slightly different tolerances.
///
/// `nonisolated` because the decoders that need it are: `FocusStartOutcome`
/// and `FocusStopOutcome` read a reply off the WatchConnectivity callback,
/// outside the main actor, and pure coercion has no state to protect.
public nonisolated enum WatchPayloadValue {
    public static func int64(_ value: Any?) -> Int64? {
        switch value {
        case let v as Int64:  return v
        case let v as Int:    return Int64(v)
        case let v as Double: return Int64(v)
        case let v as String: return Int64(v)
        default:              return nil
        }
    }

    public static func int(_ value: Any?) -> Int? {
        switch value {
        case let v as Int:    return v
        case let v as Int64:  return Int(v)
        case let v as Double: return Int(v)
        case let v as String: return Int(v)
        default:              return nil
        }
    }

    public static func double(_ value: Any?) -> Double? {
        switch value {
        case let v as Double: return v
        case let v as Int:    return Double(v)
        case let v as Int64:  return Double(v)
        case let v as String: return Double(v)
        default:              return nil
        }
    }

    public static func bool(_ value: Any?) -> Bool? {
        switch value {
        case let v as Bool:   return v
        case let v as Int:    return v != 0
        case let v as String: return (v as NSString).boolValue
        default:              return nil
        }
    }
}
