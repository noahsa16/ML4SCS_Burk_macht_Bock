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

    /// Why the ending is a value and not a sentence: the screen branches on
    /// it, and a test can assert it. A message string can only be compared to
    /// itself.
    enum FinishReason: Equatable {
        case user
        case hardCap
        case studyPreemption
        case watchFailure
        case stopUnconfirmed
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var finishReason: FinishReason?
    @Published private(set) var decisions: [PassiveDecision] = []
    /// Set when a session ended but the Watch never confirmed the stop. The
    /// screen says so rather than implying a clean close, because an
    /// unconfirmed stop means the sensor stream may still be running.
    ///
    /// Derived rather than stored: `finishReason == .stopUnconfirmed` is the
    /// same fact, and a second stored property kept in sync only by the
    /// discipline of one call site is a duplicate waiting to drift.
    var stopUnconfirmed: Bool { finishReason == .stopUnconfirmed }

    private var builder: PassiveWindowBuilder
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
    // Why not derived from `phase`: a recording that preempts a start still in
    // flight moves the phase to `.failed`, and the user can leave that screen
    // — `returnToIdle` puts the phase back to `.idle`, which `begin` accepts.
    // The reply the Watch owes us is still coming, so the fact that has to
    // outlive the phase is "a recording took the Watch after we asked", and it
    // is cleared only by the next ask.
    private var startPreemptedByRecording = false
    // Why a stored message and not a bool: a missing or malformed bundle
    // resource will not fix itself while the process is alive, so one failed
    // attempt is final for the store's lifetime — not just for this session —
    // and every later `consume` (this session's or a later one) needs the
    // same reason to hand the phase without paying for a doomed retry.
    private var loadFailureMessage: String?
    /// Window start times already paid into the collection this session.
    ///
    /// Credit is written as windows arrive, so the ledger against re-delivery
    /// has to sit with the credit. `PassiveWindowBuilder` drops non-monotonic
    /// samples and so would not re-emit a window today; that is its
    /// invariant, not this one's. The key is a millisecond, so two windows
    /// that begin inside the same one are also one payment.
    private var creditedWindowStarts: Set<Int64> = []
    /// The lowest `ordinal` a creature completed by this session can carry.
    /// Read at `begin()` so the finished page can tell a creature this
    /// session finished from one that was already in the collection.
    private var firstOrdinalThisSession: Int64 = 0

    init(classifier: PassiveClassifier? = nil,
         makeClassifier: @escaping () throws -> PassiveClassifier = {
             try ScrybeModel(resourceName: "ScrybeActive", channels: 6, seqLen: 250)
         },
         bestiary: BestiaryStore? = nil,
         hardCapSeconds: TimeInterval = FocusSessionStore.hardCapSeconds,
         stopOnWatch: @escaping @MainActor () async -> FocusStopOutcome = {
             await ServerCommandListener.shared.stopFocusSession()
         },
         windowBuilder: PassiveWindowBuilder = PassiveWindowBuilder(
             seqLen: 250, strideSamples: 125, nominalHz: 50, channels: 6)) {
        self.injected = classifier
        self.makeClassifier = makeClassifier
        self.injectedBestiary = bestiary
        self.hardCapSeconds = hardCapSeconds
        self.stopOnWatch = stopOnWatch
        self.builder = windowBuilder
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

    /// The creature the margin draws: whichever one `BestiaryStore` has in
    /// progress right now, read on every access rather than snapshotted when
    /// the session began.
    ///
    /// A half-drawn animal continues rather than restarting, and starting
    /// again cannot reroll for a different one — but the creature can also
    /// *finish* mid-sitting, and then the next one has to start growing.
    /// A snapshot clamped at its last stroke instead and held there: a
    /// 45-minute session from an empty collection spent its final 15 minutes
    /// with a motionless margin, and with the carry-over the design assumes,
    /// 20 minutes carried plus a 25-minute target froze after ten.
    private var displayedCreature: BestiaryEntry { bestiary.creatureInProgress() }

    var currentSpecies: Int { displayedCreature.speciesId }
    var strokesTotal: Int { displayedCreature.strokesTotal }

    /// Grows with credited writing time, never with the number of bursts —
    /// see `Bestiary.strokesDrawn`. Pauses hold it still and never reduce it,
    /// and stopping early simply leaves the creature partly drawn.
    ///
    /// Measured against `Bestiary.secondsPerCreature`, not against the
    /// session's own target: the target sets how long this sitting runs, never
    /// what the animal costs.
    var strokesDrawn: Int { displayedCreature.strokesDrawn }

    // MARK: - Phases

    /// Enters `starting` while the Watch is asked. Bounded by
    /// `ServerCommandListener.startFocusSession`'s own deadline, so this phase
    /// cannot outlive that timeout.
    func markStarting() {
        guard case .idle = phase else { return }
        startPreemptedByRecording = false
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
    ///
    /// Refuses from any phase but `idle` and `starting`: the Watch's answer
    /// arrives up to eight seconds after the ask, and a study recording that
    /// preempted the session inside that window has already moved the phase to
    /// `failed`. Without the guard, the late `started` reply would open a
    /// session on a stream the recording owns.
    ///
    /// The phase alone does not carry that, because the user can leave the
    /// failure screen: `returnToIdle` restores `.idle`, which this guard
    /// admits. `startPreemptedByRecording` survives that move, so a reply
    /// overtaken by a recording is refused however the screen moved on — with
    /// one gap it does not close. Asking again clears the flag
    /// (`markStarting`), and if the first ask's reply is still in flight when
    /// that happens, it now passes both guards. The window is the first ask's
    /// own eight seconds and the second ask re-establishes the truth when it
    /// answers, so what gets through is the already-accepted class of a stale
    /// reply, not a new one. No `focus_stop` follows either way — the Watch is
    /// recording, and stopping it is exactly what must not happen.
    func begin(targetSeconds: Double, at date: Date = Date()) {
        guard phase == .idle || phase == .starting else { return }
        guard !startPreemptedByRecording else {
            failToStart(FocusStartRefusal.recordingInProgress.message)
            return
        }
        reset()
        finishReason = nil
        firstOrdinalThisSession = bestiary.creatureInProgress(now: date).ordinal
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

    /// Ends the session: freezes the page and asks the Watch to stop.
    ///
    /// Credits nothing — every window paid into the collection as it arrived
    /// (see `consume`), so a lump sum here would count the session twice.
    ///
    /// The phase moves immediately and does not wait for the Watch. A stop the
    /// Watch never confirms is reported through `stopUnconfirmed` rather than
    /// holding the screen in a state it might never leave.
    func end(at date: Date = Date()) {
        end(at: date, reason: .user)
    }

    /// Why a private overload rather than a parameter on the public `end()`:
    /// the hard cap ends a running session the same way the user does, and
    /// the only difference the screen needs is which of the two it was.
    private func end(at date: Date, reason: FinishReason) {
        guard case .running(let startedAt, _) = phase else { return }
        hardStopTask?.cancel()
        hardStopTask = nil
        lastSessionStart = startedAt
        lastSessionEnd = date
        finishReason = reason
        phase = .finished(creatureToShow())
        stopWatchIfStreaming()
    }

    /// A study recording has taken the Watch.
    ///
    /// The research path outranks this feature and the Watch preempts without
    /// asking, so the session closes here rather than running on against a
    /// stream that is no longer its own. No `focus_stop` goes out: the Watch
    /// is at this moment being told to record, and stopping it is exactly
    /// what must not happen. The writing time is already in the collection.
    ///
    /// `starting` counts as well as `running`. A recording forwarded inside
    /// the eight seconds a `focus_start` may take preempts a session this
    /// side has not heard back about yet, and the session that reply would
    /// open would never have owned the stream.
    func watchPreemptedByRecording() {
        startPreemptedByRecording = true
        switch phase {
        case .running:
            watchIsStreaming = false
            end(at: Date(), reason: .studyPreemption)
        case .starting:
            failToStart(FocusStartRefusal.recordingInProgress.message)
        case .idle, .failed, .finished:
            break
        }
    }

    /// The Watch ended the session because its workout session could not run.
    ///
    /// The ending is right — without the workout the stream dies the moment
    /// the wrist lowers — but the Watch performs it alone, and until this
    /// arrived the phone kept a session it believed live: the page stopped
    /// growing with nothing said, and the `focus_stop` that followed was
    /// answered `no focus session`, which reads as a clean stop.
    ///
    /// No `focus_stop` goes out. The Watch has already stopped, and the
    /// notice is what says so; asking it again would only cost a round trip
    /// to be told the same thing.
    ///
    /// `starting` counts as well as `running`: the workout prompt is answered
    /// on the Watch, so a denial commonly lands inside the eight seconds a
    /// `focus_start` may take. The reply that follows finds `.failed` and is
    /// refused by `begin()` — except after a `returnToIdle` inside that same
    /// window, which is the late-reply gap already documented there.
    func watchWorkoutFailed() {
        switch phase {
        case .running:
            watchIsStreaming = false
            finishReason = .watchFailure
            failWhileRunning(Self.workoutFailureMessage)
        case .starting:
            failToStart(Self.workoutFailureMessage)
        case .idle, .failed, .finished:
            break
        }
    }

    /// Names both causes `workout_failed` covers — permission denied, and
    /// HealthKit unavailable — and says the measuring stopped, which is the
    /// half the user watched happen without being told.
    private static var workoutFailureMessage: String {
        String(localized: "Die Uhr hat die Messung beendet, weil die Workout-Sitzung nicht läuft. Prüfe die Workout-Freigabe in den Health-Einstellungen.")
    }

    /// Leaves `failed` or `finished` for the picker again. A live session is
    /// never discarded this way — it has to be ended.
    func returnToIdle() {
        guard !isActive else { return }
        reset()
        finishReason = nil
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
            end(at: startedAt.addingTimeInterval(hardCapSeconds), reason: .hardCap)
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
                let message = String(localized: "Das Modell konnte nicht geladen werden.") + " \(error)"
                loadFailureMessage = message
                failWhileRunning(message)
                return
            }
        }
        guard let classifier else { return }
        for window in builder.append(samples) {
            let startMs = Int64(window.startTimestamp * 1000)
            guard creditedWindowStarts.insert(startMs).inserted else { continue }
            guard let logit = try? classifier.logit(window: window.values) else { continue }
            let decision = PassiveDecision(
                startMs: startMs,
                endMs: Int64(window.endTimestamp * 1000),
                logit: logit,
                writing: logit >= 0,
                creditSeconds: builder.secondsPerWindow)
            decisions.append(decision)
            // Why credited here rather than in one sum at `end()`: the
            // creature has to keep growing past a completion boundary instead
            // of clamping at the last stroke, and this screen is meant to be
            // closed while the session runs — so a session iOS terminates,
            // which never reaches `end()`, still leaves its writing behind.
            guard decision.writing else { continue }
            bestiary.addWritingSeconds(decision.creditSeconds)
        }
    }

    // MARK: - Ending

    /// The creature the finished page shows: the one this session completed
    /// if it completed any, otherwise the one it left partly drawn.
    private func creatureToShow() -> BestiaryEntry {
        if let finished = bestiary.completed.first,
           finished.ordinal >= firstOrdinalThisSession {
            return finished
        }
        return bestiary.creatureInProgress()
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
            let confirmed = outcome.focusSessionIsStopped
            // Why this overrides whatever reason the ending already carried:
            // "you ended it" or "the cap ended it" is moot once it is unclear
            // the sensors actually stopped — that doubt is the one the screen
            // needs to lead with.
            if !confirmed {
                self?.finishReason = .stopUnconfirmed
            }
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
            self?.end(at: start.addingTimeInterval(cap), reason: .hardCap)
        }
    }

    private func reset() {
        decisions.removeAll()
        creditedWindowStarts.removeAll()
        builder.reset()
        hardStopTask?.cancel()
        hardStopTask = nil
    }
}
