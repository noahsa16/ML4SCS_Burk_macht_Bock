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
        guard reply[WatchPayloadKey.ok] as? Bool ?? false else {
            let raw = reply[WatchPayloadKey.error] as? String ?? ""
            guard let refusal = FocusStartRefusal(rawValue: raw) else { return .noAnswer }
            return .refused(refusal)
        }
        return .started
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
public enum WatchPayloadValue {
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
