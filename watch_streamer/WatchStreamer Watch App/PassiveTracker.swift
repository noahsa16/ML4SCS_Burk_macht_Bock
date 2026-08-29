import Combine
import Foundation
import WatchConnectivity

/// Reads the real `CMSensorRecorder` through the same code path the diagnostic
/// probe uses, so a probe measures what the tracker actually performs.
nonisolated struct RecorderSampleSource: PassiveSampleSource {
    func fetch(from: Date, to: Date) -> [PassiveSample] {
        SensorProbe.fetch(from: from, to: to)
    }
}

extension WatchScrybeModel: PassiveClassifier {}

/// Observable Watch-side facade over `PassiveTrackerEngine`.
///
/// **Not validated on hardware** — see `PassiveTrackerEngine`. The engine holds
/// the logic and is unit-tested against injected fakes; this type supplies the
/// recorder and the Core ML model, owns the cycle cadence, and publishes the
/// state SwiftUI reads.
@MainActor
final class PassiveTracker: ObservableObject {
    static let shared = PassiveTracker()

    @Published private(set) var state: PassiveTrackerEngine.State = .disabled
    @Published private(set) var writingSecondsToday: Double = 0
    @Published private(set) var lastCycleAt: Date?
    @Published private(set) var isCycling = false

    private let engine: PassiveTrackerEngine
    private var cycleTimer: Timer?

    /// Why 15 minutes: the recorder withholds samples for up to three minutes
    /// and then stores them for days, so a tighter cadence buys no freshness
    /// and costs wrist battery.
    private static let cycleInterval: TimeInterval = 15 * 60

    init(engine: PassiveTrackerEngine? = nil) {
        // Why built here rather than as a default argument: a default argument
        // is evaluated in a nonisolated context, and SensorProbe's constants
        // are main-actor isolated under this target's default isolation.
        self.engine = engine ?? PassiveTrackerEngine(
            source: RecorderSampleSource(),
            store: PassiveDecisionStore(fileURL: PassiveDecisionStore.defaultFileURL()),
            makeClassifier: {
                try WatchScrybeModel(resourceName: "ScrybePassive",
                                     channels: 3, seqLen: 250)
            },
            headroomSeconds: SensorProbe.headroomSeconds,
            maxFetchSpanSeconds: SensorProbe.maxFetchSpanSeconds)
        state = self.engine.state
        writingSecondsToday = self.engine.writingSecondsToday()
        if self.engine.isEnabled { startCycleTimer() }
    }

    var isEnabled: Bool { engine.isEnabled }

    func enable() {
        engine.enable()
        state = engine.state
        startCycleTimer()
        Task { await runCycle() }
    }

    func disable() {
        engine.disable()
        state = engine.state
        cycleTimer?.invalidate()
        cycleTimer = nil
    }

    /// Runs one retrieval cycle off the main actor and publishes the outcome.
    func runCycle() async {
        guard !isCycling else { return }
        isCycling = true
        defer { isCycling = false }

        let engine = self.engine
        let outcome = await Task.detached(priority: .utility) {
            let result = engine.runRetrievalCycle()
            return (result, engine.writingSecondsToday())
        }.value

        state = outcome.0.state
        writingSecondsToday = outcome.1
        lastCycleAt = Date()
        syncPendingDecisions()
    }

    /// Decisions the phone has not seen yet.
    func pendingDecisions(since ms: Int64) -> [PassiveDecision] {
        engine.pendingDecisions(since: ms)
    }

    /// Hands unsent decisions to the phone.
    ///
    /// `transferUserInfo` rather than `sendMessage`: the phone is routinely out
    /// of range on a passive day, and these must survive that. The batch is
    /// idempotent — every decision carries its own `startMs`, so a re-delivery
    /// is recognised rather than double-counted, and the high-water mark only
    /// advances once the transfer is handed over.
    @discardableResult
    func syncPendingDecisions() -> Int {
        let pending = engine.pendingDecisions(since: syncedThroughMs)
        guard !pending.isEmpty else { return 0 }
        guard let payload = try? JSONEncoder().encode(pending) else { return 0 }
        WCSession.default.transferUserInfo([
            WatchPayloadKey.type: WatchPayloadKey.passiveDecisionsType,
            WatchPayloadKey.decisions: payload
        ])
        syncedThroughMs = pending[pending.count - 1].startMs
        return pending.count
    }

    /// Answers a phone pull: hands over everything already computed, then
    /// starts a retrieval cycle for whatever the recorder has since gathered.
    ///
    /// Why the cycle is not awaited: it reads up to twelve hours of recorder
    /// history and runs Core ML over every window, which would outlast the
    /// phone's `sendMessage` timeout and leave the pull with no reply at all.
    /// The pull therefore promises what the watch *has*, and the fresh windows
    /// arrive on their own — `transferUserInfo` is durable.
    @discardableResult
    func syncNow() -> Int {
        let handed = syncPendingDecisions()
        Task { await runCycle() }
        return handed
    }

    private static let syncedThroughKey = "passiveTracker.syncedThroughMs"
    private var syncedThroughMs: Int64 {
        get { Int64(UserDefaults.standard.double(forKey: Self.syncedThroughKey)) }
        set { UserDefaults.standard.set(Double(newValue), forKey: Self.syncedThroughKey) }
    }

    private func startCycleTimer() {
        cycleTimer?.invalidate()
        let timer = Timer(timeInterval: Self.cycleInterval, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in await self?.runCycle() }
        }
        cycleTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }
}
