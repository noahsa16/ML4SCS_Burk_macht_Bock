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
        case .drainSpill, .clearSpill, .sensorProbeStart:
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
        case .start, .stop, .drainSpill, .clearSpill:
            return false
        }
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
