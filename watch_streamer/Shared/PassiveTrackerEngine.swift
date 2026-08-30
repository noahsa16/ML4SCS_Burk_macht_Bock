import Foundation

/// Abstracts the recorder read so the pipeline is testable without hardware.
public nonisolated protocol PassiveSampleSource {
    func fetch(from: Date, to: Date) -> [PassiveSample]
}

/// Abstracts inference so the pipeline is testable without a Core ML bundle.
public nonisolated protocol PassiveClassifier {
    func logit(window: [Float]) throws -> Float
}

/// Arms the system recorder that supplies ``PassiveSampleSource`` later.
/// Kept separate from fetching so the engine can prove that enabling passive
/// tracking actually starts capture instead of only polling an empty store.
public nonisolated protocol PassiveRecordingController {
    @discardableResult
    func armRecording(for duration: TimeInterval) -> Bool
}

/// A run of writing windows, as a person would describe it: one sitting.
public nonisolated struct WritingPhase: Equatable, Sendable {
    public let startMs: Int64
    public let endMs: Int64
    /// Credited writing time — the sum of the windows' strides, not the wall
    /// extent. The windows overlap, so the extent would double-count.
    public let seconds: Double

    public init(startMs: Int64, endMs: Int64, seconds: Double) {
        self.startMs = startMs
        self.endMs = endMs
        self.seconds = seconds
    }
}

/// The autonomous writing tracker's engine.
///
/// **Not validated on hardware.** Every branch below is exercised by unit
/// tests against injected fakes, but this code has never run against a real
/// `CMSensorRecorder` on a worn Apple Watch. Until it has — including the
/// 12-hour retrieval probe — the connected live pipeline remains the only
/// measured path, and no claim that the Watch tracks writing autonomously is
/// supported by evidence.
///
/// How it works: `CMSensorRecorder` stores raw accelerometer data that becomes
/// readable a few minutes after capture. Each cycle reads the span between a
/// persisted cursor and `now - headroom`, cuts it into fixed-length windows,
/// runs the passive model, and appends the verdicts to a durable log. The
/// cursor advances only past spans that were actually consumed, so a failed
/// cycle costs latency rather than data.
/// `nonisolated` on purpose: a twelve-hour backlog is roughly 17 000
/// windows, and running that many Core ML passes on the main actor would
/// freeze the Watch UI. The facade hops results back to main.
public nonisolated final class PassiveTrackerEngine {

    public enum State: Equatable {
        case disabled
        case idle(lastRun: Date?, decisionsLastRun: Int)
        case running
        case failed(String)
    }

    public struct CycleResult: Equatable {
        public let decisionsRecorded: Int
        public let cursorAdvancedTo: Date?
        public let state: State
    }

    /// Defaults mirror the Apple-documented recorder behaviour: samples are
    /// readable only after a delay, and one fetch spans at most 12 hours.
    public static let defaultHeadroomSeconds: TimeInterval = 300
    public static let defaultMaxFetchSpanSeconds: TimeInterval = 12 * 3600
    public static let retentionDays = 90

    public private(set) var state: State = .disabled

    private let source: PassiveSampleSource
    private let recordingController: PassiveRecordingController?
    private let store: PassiveDecisionStore
    private let defaults: UserDefaults
    private let makeClassifier: () throws -> PassiveClassifier
    private var classifier: PassiveClassifier?
    private var builder: PassiveWindowBuilder
    private let threshold: Float
    private let headroomSeconds: TimeInterval
    private let maxFetchSpanSeconds: TimeInterval

    private let enabledKey: String
    private let cursorKey: String

    public init(source: PassiveSampleSource,
                store: PassiveDecisionStore,
                makeClassifier: @escaping () throws -> PassiveClassifier,
                recordingController: PassiveRecordingController? = nil,
                defaults: UserDefaults = .standard,
                seqLen: Int = 250,
                strideSamples: Int = 125,
                nominalHz: Double = 50,
                // Why: the shipped model emits a logit, and proba >= 0.5 is
                // logit >= 0 — the threshold from ScrybePassive.json expressed
                // on the output the model actually produces.
                threshold: Float = 0,
                headroomSeconds: TimeInterval = defaultHeadroomSeconds,
                maxFetchSpanSeconds: TimeInterval = defaultMaxFetchSpanSeconds,
                keyPrefix: String = "passiveTracker") {
        self.source = source
        self.recordingController = recordingController
        self.store = store
        self.makeClassifier = makeClassifier
        self.defaults = defaults
        self.threshold = threshold
        self.headroomSeconds = headroomSeconds
        self.maxFetchSpanSeconds = maxFetchSpanSeconds
        self.enabledKey = "\(keyPrefix).enabled"
        self.cursorKey = "\(keyPrefix).cursor"
        self.builder = PassiveWindowBuilder(seqLen: seqLen,
                                            strideSamples: strideSamples,
                                            nominalHz: nominalHz)
        if defaults.bool(forKey: enabledKey) {
            state = armRecording()
                ? .idle(lastRun: nil, decisionsLastRun: 0)
                : .failed("sensor recording unavailable")
        }
    }

    public var isEnabled: Bool {
        if case .disabled = state { return false }
        return true
    }

    public func enable() {
        defaults.set(true, forKey: enabledKey)
        guard armRecording() else {
            state = .failed("sensor recording unavailable")
            return
        }
        state = .idle(lastRun: nil, decisionsLastRun: 0)
    }

    public func disable() {
        defaults.set(false, forKey: enabledKey)
        state = .disabled
        builder.reset()
    }

    public var cursor: Date? {
        get {
            let t = defaults.double(forKey: cursorKey)
            return t > 0 ? Date(timeIntervalSinceReferenceDate: t) : nil
        }
        set {
            guard let newValue else { return }
            defaults.set(newValue.timeIntervalSinceReferenceDate, forKey: cursorKey)
        }
    }

    public func writingSecondsToday(now: Date = Date()) -> Double {
        store.writingSeconds(onDayContaining: now)
    }

    /// Silence that does not break a phase. Mirrors the phone's
    /// `PassiveFocusAggregator.stretchGapMs`, which is the training-time label
    /// closing gap, so watch and phone describe the same day the same way.
    public static let phaseGapMs: Int64 = 2_500

    /// The day's writing runs, oldest first.
    ///
    /// Lets the watch show *what* a retrieval cycle found rather than only a
    /// daily total — the total alone cannot tell "detected nothing" apart from
    /// "detected something an hour ago".
    public func writingPhases(onDayContaining date: Date = Date()) -> [WritingPhase] {
        let writing = store.decisions(onDayContaining: date)
            .filter(\.writing)
            .sorted { $0.startMs < $1.startMs }
        var phases: [WritingPhase] = []
        for d in writing {
            if let last = phases.last, d.startMs - last.endMs <= Self.phaseGapMs {
                phases[phases.count - 1] = WritingPhase(
                    startMs: last.startMs,
                    endMs: max(last.endMs, d.endMs),
                    seconds: last.seconds + d.creditSeconds)
            } else {
                phases.append(WritingPhase(startMs: d.startMs, endMs: d.endMs,
                                           seconds: d.creditSeconds))
            }
        }
        return phases
    }

    /// Decisions newer than `ms`, oldest first — what the phone has not seen.
    public func pendingDecisions(since ms: Int64) -> [PassiveDecision] {
        store.allDecisions().filter { $0.startMs > ms }.sorted { $0.startMs < $1.startMs }
    }

    /// Reads everything readable since the cursor, classifies it, and persists
    /// the verdicts. Safe to call repeatedly; a cycle with nothing new is a
    /// no-op.
    @discardableResult
    public func runRetrievalCycle(now: Date = Date()) -> CycleResult {
        guard isEnabled else {
            return CycleResult(decisionsRecorded: 0, cursorAdvancedTo: nil, state: state)
        }
        guard armRecording() else {
            state = .failed("sensor recording unavailable")
            return CycleResult(decisionsRecorded: 0, cursorAdvancedTo: nil, state: state)
        }
        state = .running

        let readable = now.addingTimeInterval(-headroomSeconds)
        // Why: the first run has no cursor. Start one window-span back rather
        // than reading the recorder's entire history on launch.
        let windowSpan = Double(builder.seqLen) / builder.nominalHz
        let from = cursor ?? readable.addingTimeInterval(-windowSpan)
        // Why: Apple caps one fetch at 12 hours. A longer backlog is consumed
        // over several cycles rather than silently truncated.
        let until = min(readable, from.addingTimeInterval(maxFetchSpanSeconds))

        guard until > from else {
            state = .idle(lastRun: now, decisionsLastRun: 0)
            return CycleResult(decisionsRecorded: 0, cursorAdvancedTo: nil, state: state)
        }

        let samples = source.fetch(from: from, to: until)
        guard !samples.isEmpty else {
            // Why: advance past an empty span anyway. The recorder held nothing
            // there, and re-reading it every cycle would stall the cursor
            // behind a gap in which the watch was simply off the wrist.
            cursor = until
            builder.reset()
            state = .idle(lastRun: now, decisionsLastRun: 0)
            return CycleResult(decisionsRecorded: 0, cursorAdvancedTo: until, state: state)
        }

        let model: PassiveClassifier
        do {
            model = try activeClassifier()
        } catch {
            // Why: leave the cursor untouched. The samples are still on the
            // recorder, so a repaired model can process them on a later cycle.
            state = .failed("model unavailable: \(error)")
            return CycleResult(decisionsRecorded: 0, cursorAdvancedTo: nil, state: state)
        }

        let windows = builder.append(samples)
        var decisions: [PassiveDecision] = []
        decisions.reserveCapacity(windows.count)
        var inferenceFailures = 0
        for w in windows {
            guard let logit = try? model.logit(window: w.values) else {
                inferenceFailures += 1
                continue
            }
            decisions.append(PassiveDecision(
                startMs: Self.epochMs(fromReferenceDate: w.startTimestamp),
                endMs: Self.epochMs(fromReferenceDate: w.endTimestamp),
                logit: logit,
                writing: logit >= threshold,
                creditSeconds: builder.secondsPerWindow))
        }

        if !decisions.isEmpty, !store.record(decisions) {
            state = .failed("could not persist decisions")
            return CycleResult(decisionsRecorded: 0, cursorAdvancedTo: nil, state: state)
        }

        cursor = until
        store.pruneOlderThan(days: Self.retentionDays, now: now)

        if inferenceFailures > 0, decisions.isEmpty {
            state = .failed("inference failed for every window")
        } else {
            state = .idle(lastRun: now, decisionsLastRun: decisions.count)
        }
        return CycleResult(decisionsRecorded: decisions.count,
                           cursorAdvancedTo: until,
                           state: state)
    }

    private func activeClassifier() throws -> PassiveClassifier {
        if let classifier { return classifier }
        let made = try makeClassifier()
        classifier = made
        return made
    }

    /// Re-arming extends capture to the recorder's 12-hour ceiling. The Watch
    /// facade calls a retrieval cycle every 15 minutes while it is alive, and
    /// construction re-arms after a relaunch, so a suspended or terminated app
    /// still has the longest system-supported capture window.
    private func armRecording() -> Bool {
        recordingController?.armRecording(for: maxFetchSpanSeconds) ?? true
    }

    /// `CMSensorRecorder` timestamps are reference-date based; the decision log
    /// and the server both speak Unix milliseconds.
    static func epochMs(fromReferenceDate t: TimeInterval) -> Int64 {
        Int64((t + Date.timeIntervalBetween1970AndReferenceDate) * 1000)
    }
}
