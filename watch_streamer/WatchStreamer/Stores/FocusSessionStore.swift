import Combine
import Foundation
import SwiftUI

/// A deliberately started writing session.
///
/// Holds everything in memory on purpose. Live and recorder windows never share
/// a `startMs`, so persisting both would double-count the day and idempotency
/// could not catch it. The passive path stays the single source of truth for
/// writing time; the only thing a session leaves behind is the writing seconds
/// it credits to the creature in `BestiaryStore`.
@MainActor
final class FocusSessionStore: ObservableObject {
    static let shared = FocusSessionStore()

    /// Longest a session may run before it ends itself.
    ///
    /// Not a nicety: the Watch streams raw sensors for the whole session, so a
    /// forgotten one drains the wrist battery. The number lives in
    /// `FocusCommandPolicy` because the Watch enforces the same cap
    /// independently; this is the phone's half of one guarantee, not a second
    /// one. `nonisolated` so it can be read from a default argument, which is
    /// evaluated outside the actor.
    nonisolated static let hardCapSeconds: TimeInterval = FocusCommandPolicy.sessionCapSeconds

    enum Phase: Equatable {
        case idle
        case starting
        case running(startedAt: Date, targetSeconds: Double)
        /// The session could not start classifying. Carries the reason so the
        /// screen can say what went wrong instead of drawing an empty page.
        case failed(String)
        case finished(BestiaryEntry)
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var decisions: [PassiveDecision] = []
    /// Set when a session ended but the Watch never confirmed the stop. The
    /// screen says so rather than implying a clean close, because an
    /// unconfirmed stop means the sensor stream may still be running.
    @Published private(set) var stopUnconfirmed = false

    private var builder = PassiveWindowBuilder(seqLen: 250, strideSamples: 125,
                                               nominalHz: 50, channels: 6)
    private let injected: PassiveClassifier?
    private let makeClassifier: () throws -> PassiveClassifier
    private let injectedBestiary: BestiaryStore?
    private let hardCapSeconds: TimeInterval
    private let stopOnWatch: @MainActor () async -> FocusStopOutcome
    private var classifier: PassiveClassifier?
    private var hardStopTask: Task<Void, Never>?
    // Why tracked rather than derived from `phase`: `focus_stop` ends the
    // Watch's capture outright. Sending it after a start the Watch refused
    // would stop a study recording this session never owned.
    private var watchIsStreaming = false
    // Why a stored message and not a bool: a missing or malformed bundle
    // resource will not fix itself while the process is alive, so one failed
    // attempt is final for the store's lifetime — not just for this session —
    // and every later `consume` (this session's or a later one) needs the
    // same reason to hand the phase without paying for a doomed retry.
    private var loadFailureMessage: String?

    init(classifier: PassiveClassifier? = nil,
         makeClassifier: @escaping () throws -> PassiveClassifier = {
             try ScrybeModel(resourceName: "ScrybeActive", channels: 6, seqLen: 250)
         },
         bestiary: BestiaryStore? = nil,
         hardCapSeconds: TimeInterval = FocusSessionStore.hardCapSeconds,
         stopOnWatch: @escaping @MainActor () async -> FocusStopOutcome = {
             await ServerCommandListener.shared.stopFocusSession()
         }) {
        self.injected = classifier
        self.makeClassifier = makeClassifier
        self.injectedBestiary = bestiary
        self.hardCapSeconds = hardCapSeconds
        self.stopOnWatch = stopOnWatch
    }

    /// Resolved here rather than in `init` so the default argument does not
    /// have to touch a `@MainActor` singleton from outside the actor.
    private var bestiary: BestiaryStore { injectedBestiary ?? .shared }

    var writingSeconds: Double {
        decisions.filter(\.writing).reduce(0) { $0 + $1.creditSeconds }
    }

    var segments: [FocusSegment] { FocusStrokes.segments(from: decisions) }

    /// Whether a session is being started or is running. Both states own the
    /// Watch's sensor stream, and neither may be left by resetting.
    var isActive: Bool {
        switch phase {
        case .starting, .running: return true
        case .idle, .failed, .finished: return false
        }
    }

    /// Wall-clock bounds of the session the `finished` phase describes. The
    /// page's signature needs the end, which the phase does not carry.
    private(set) var lastSessionStart: Date?
    private(set) var lastSessionEnd: Date?

    // MARK: - The creature in the margin

    /// The creature this session draws, read from `BestiaryStore` when the
    /// session begins. A half-drawn animal continues rather than restarting,
    /// and starting again cannot reroll for a different one.
    private(set) var currentSpecies: Int = 0
    private(set) var strokesTotal: Int = 0

    /// Writing time the creature already carries from earlier sittings. Only
    /// drawn against, never credited again — it came out of the creature in
    /// the first place.
    private(set) var carriedSeconds: Double = 0

    /// Grows with credited writing time, never with the number of bursts —
    /// see `Bestiary.strokesDrawn`. Pauses hold it still and never reduce it,
    /// and stopping early simply leaves the creature partly drawn.
    ///
    /// Measured against `Bestiary.secondsPerCreature`, not against the
    /// session's own target: the target sets how long this sitting runs, never
    /// what the animal costs.
    var strokesDrawn: Int {
        guard case .running = phase else { return 0 }
        return Bestiary.strokesDrawn(writingSeconds: carriedSeconds + writingSeconds,
                                     targetSeconds: Bestiary.secondsPerCreature,
                                     strokesTotal: strokesTotal)
    }

    // MARK: - Phases

    /// Enters `starting` while the Watch is asked. Bounded by
    /// `ServerCommandListener.startFocusSession`'s own deadline, so this phase
    /// cannot outlive that timeout.
    func markStarting() {
        guard case .idle = phase else { return }
        phase = .starting
    }

    /// The Watch refused the start or never answered. No session was started,
    /// so nothing is asked to stop.
    func failToStart(_ reason: String) {
        watchIsStreaming = false
        hardStopTask?.cancel()
        hardStopTask = nil
        phase = .failed(reason)
    }

    /// Starts the session clock, seeded from the creature already in progress.
    ///
    /// Called once the Watch has confirmed the start, so from here the Watch
    /// is streaming and every exit — the user's, a failure, or the hard cap —
    /// has to stop it again.
    func begin(targetSeconds: Double, at date: Date = Date()) {
        reset()
        stopUnconfirmed = false
        let creature = bestiary.creatureInProgress(now: date)
        currentSpecies = creature.speciesId
        strokesTotal = creature.strokesTotal
        carriedSeconds = creature.writingSeconds
        watchIsStreaming = true
        phase = .running(startedAt: date, targetSeconds: targetSeconds)
        scheduleHardStop(from: date)
    }

    /// Test seam: enter `running` without the Watch round-trip. Uses the same
    /// path a real start does, so an injected `BestiaryStore` is what keeps a
    /// test off the app's real collection.
    func beginForTesting(targetSeconds: Double, at date: Date = Date()) {
        begin(targetSeconds: targetSeconds, at: date)
    }

    /// Ends the session: credits its writing time, freezes the page, and asks
    /// the Watch to stop.
    ///
    /// The phase moves immediately and does not wait for the Watch. A stop the
    /// Watch never confirms is reported through `stopUnconfirmed` rather than
    /// holding the screen in a state it might never leave.
    func end(at date: Date = Date()) {
        guard case .running(let startedAt, _) = phase else { return }
        hardStopTask?.cancel()
        hardStopTask = nil
        let entry = creditWritingTime(at: date)
        lastSessionStart = startedAt
        lastSessionEnd = date
        phase = .finished(entry)
        stopWatchIfStreaming()
    }

    /// A study recording has taken the Watch.
    ///
    /// The research path outranks this feature and the Watch preempts without
    /// asking, so the session closes here rather than running on against a
    /// stream that is no longer its own. No `focus_stop` goes out: the Watch
    /// is at this moment being told to record, and stopping it is exactly
    /// what must not happen.
    func watchPreemptedByRecording() {
        guard case .running = phase else { return }
        watchIsStreaming = false
        end()
    }

    /// Leaves `failed` or `finished` for the picker again. A live session is
    /// never discarded this way — it has to be ended.
    func returnToIdle() {
        guard !isActive else { return }
        reset()
        stopUnconfirmed = false
        phase = .idle
    }

    /// Feeds samples handed over by `PhoneBridge` while a session runs.
    ///
    /// Windows off each sample's own `timestamp` — no synthetic clock. A gap
    /// in the caller's stream (a WatchConnectivity stall, routine on the live
    /// path) must reset the buffer rather than being concatenated across, or
    /// the model would classify a window spanning signal that never happened.
    /// See `PassiveWindowBuilder`'s header for why that invariant lives there,
    /// not here.
    func consume(_ samples: [PassiveSample]) {
        guard case .running(let startedAt, _) = phase else { return }
        // Why the cap is checked here as well as on its own task: a suspended
        // app runs no timers. Re-checking against the wall clock whenever
        // samples arrive means a session cannot outlive the cap merely
        // because the phone was asleep when the deadline passed.
        if Date().timeIntervalSince(startedAt) >= hardCapSeconds {
            end(at: startedAt.addingTimeInterval(hardCapSeconds))
            return
        }
        if let loadFailureMessage {
            // Why not re-attempt: the previous failure already established
            // the model will not load this run; re-throwing the same load
            // every batch would cost a bundle lookup and a manifest parse
            // for no new information.
            failWhileRunning(loadFailureMessage)
            return
        }
        if classifier == nil {
            do {
                classifier = try injected ?? makeClassifier()
            } catch {
                let message = "model unavailable: \(error)"
                loadFailureMessage = message
                failWhileRunning(message)
                return
            }
        }
        guard let classifier else { return }
        for window in builder.append(samples) {
            guard let logit = try? classifier.logit(window: window.values) else { continue }
            decisions.append(PassiveDecision(
                startMs: Int64(window.startTimestamp * 1000),
                endMs: Int64(window.endTimestamp * 1000),
                logit: logit,
                writing: logit >= 0,
                creditSeconds: builder.secondsPerWindow))
        }
    }

    // MARK: - Ending

    /// Credits only this session's own seconds. `carriedSeconds` came out of
    /// the creature, so crediting it again would count it twice.
    ///
    /// - Returns: the creature to show for the session just ended — the one it
    ///   finished if it finished one, otherwise the one it left partly drawn.
    private func creditWritingTime(at date: Date) -> BestiaryEntry {
        let completedBefore = bestiary.completed.count
        bestiary.addWritingSeconds(writingSeconds, now: date)
        if bestiary.completed.count > completedBefore, let finished = bestiary.completed.first {
            return finished
        }
        return bestiary.creatureInProgress(now: date)
    }

    private func failWhileRunning(_ message: String) {
        hardStopTask?.cancel()
        hardStopTask = nil
        phase = .failed(message)
        stopWatchIfStreaming()
    }

    private func stopWatchIfStreaming() {
        guard watchIsStreaming else { return }
        watchIsStreaming = false
        Task { [weak self, stopOnWatch] in
            let outcome = await stopOnWatch()
            self?.stopUnconfirmed = !outcome.focusSessionIsStopped
        }
    }

    private func scheduleHardStop(from start: Date) {
        hardStopTask?.cancel()
        let cap = max(0, hardCapSeconds)
        // Why the store owns this task and not the screen: the cap is a
        // battery guarantee, and the session outlives the screen — closing
        // the page leaves the Watch streaming.
        hardStopTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(cap * 1_000_000_000))
            guard !Task.isCancelled else { return }
            self?.end(at: start.addingTimeInterval(cap))
        }
    }

    private func reset() {
        decisions.removeAll()
        builder.reset()
        hardStopTask?.cancel()
        hardStopTask = nil
    }
}
