import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus session store")
@MainActor
struct FocusSessionStoreTests {

    private struct FixedClassifier: PassiveClassifier {
        let value: Float
        func logit(window: [Float]) throws -> Float { value }
    }

    /// Counts `focus_stop` requests. A session that stops the Watch it never
    /// started would end a study recording, so the count is asserted in both
    /// directions.
    private final class StopRecorder: @unchecked Sendable {
        var calls = 0
        var outcome: FocusStopOutcome = .stopped
    }

    /// A collection on its own file. Every test that credits writing time
    /// needs one — `FocusSessionStore` falls back to `BestiaryStore.shared`,
    /// which is the app's real bestiary.
    private func tempBestiary() -> (BestiaryStore, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("focus-bestiary-\(UUID().uuidString).json")
        return (BestiaryStore(fileURL: url), url)
    }

    /// Lets the fire-and-forget stop task run before an assertion reads its
    /// effect. Ending a session deliberately does not wait for the Watch.
    private func settle() async {
        try? await Task.sleep(nanoseconds: 150_000_000)
    }

    /// `count` samples at `hz` beginning at `start`. The offset matters: two
    /// batches must form one monotonic stream, or the builder correctly reads
    /// the second as a gap and resets — which is the behaviour under test
    /// elsewhere, not something to work around here.
    private func samples(_ count: Int, from start: TimeInterval = 0,
                         hz: Double = 50) -> [PassiveSample] {
        (0..<count).map { i in
            PassiveSample(timestamp: start + Double(i) / hz,
                          x: 0.1, y: 0.2, z: 0.98,
                          rx: 0.01, ry: 0.02, rz: 0.03)
        }
    }

    @Test("one decision per stride once the first window is full")
    func decisionsFollowStride() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary)
        store.beginForTesting(targetSeconds: 1_500)
        store.consume(samples(250))              // 0 … 4.98 s
        #expect(store.decisions.count == 1)
        store.consume(samples(125, from: 5.0))   // continues the same stream
        #expect(store.decisions.count == 2)
    }

    // A stalled stream must not be concatenated across the hole: the model would
    // receive five seconds of signal spanning data that never existed.
    @Test("a gap in the stream resets the window rather than spanning it")
    func gapResetsTheWindow() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary)
        store.beginForTesting(targetSeconds: 1_500)
        store.consume(samples(200))                 // not yet a full window
        store.consume(samples(200, from: 60.0))     // one minute later
        #expect(store.decisions.count == 0)
    }

    // The viewfinder principle (Spec §2): live windows must never reach the
    // daily accounting. Asserted against the REAL default store file — an
    // assertion on some unrelated temp store would hold even if the session
    // wrote to the actual one, which is the failure worth catching.
    @Test("a session leaves the passive decision store untouched")
    func nothingIsPersisted() throws {
        let url = PassiveDecisionStore.defaultFileURL()
        let before = (try? Data(contentsOf: url))?.count ?? -1
        let (bestiary, bestiaryURL) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: bestiaryURL) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary)
        store.beginForTesting(targetSeconds: 1_500)
        store.consume(samples(500))

        #expect(!store.decisions.isEmpty)
        let after = (try? Data(contentsOf: url))?.count ?? -1
        #expect(after == before)
    }

    private struct Boom: Error {}

    // Pins the load path, not just a throwing `logit`: no `classifier` is
    // injected here, so `consume` must attempt `makeClassifier()` for real
    // and surface *that* failure. A test that only threw from `logit` would
    // leave the silent-no-op-on-load-failure defect uncovered.
    @Test("a classifier load failure surfaces as a phase, not a silent no-op")
    func classifierLoadFailureIsObservable() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(makeClassifier: { throw Boom() },
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.beginForTesting(targetSeconds: 1_500)

        store.consume(samples(250))
        guard case .failed(let message) = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }
        #expect(message.contains("Boom"))
        #expect(store.decisions.isEmpty)
    }

    // The second half of the same defect: a load failure must not be
    // retried per batch (a bundle lookup plus a manifest parse each time).
    // One attempt only, tracked via a call counter on `makeClassifier`.
    @Test("a load failure is attempted once, not retried per batch")
    func classifierLoadIsAttemptedOnce() {
        final class Counter: @unchecked Sendable {
            var calls = 0
        }
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let counter = Counter()
        let store = FocusSessionStore(makeClassifier: {
            counter.calls += 1
            throw Boom()
        }, bestiary: bestiary, stopOnWatch: { .stopped })
        store.beginForTesting(targetSeconds: 1_500)

        store.consume(samples(250))
        store.consume(samples(250, from: 5.0))
        store.consume(samples(250, from: 10.0))

        #expect(counter.calls == 1)
        guard case .failed = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }
    }

    // MARK: - Carrying the creature over

    // A creature belongs to accumulated writing, not to a session. Seeding the
    // session from `BestiaryStore` is what makes a half-drawn animal continue;
    // without it the margin restarts at zero strokes every sitting, which the
    // stroke assertion below is there to catch.
    @Test("a session resumes the creature already in progress")
    func resumesTheCreatureInProgress() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        bestiary.addWritingSeconds(600, now: Date(timeIntervalSince1970: 1_788_000_000))
        let creature = try #require(bestiary.current)

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1), bestiary: bestiary)
        store.begin(targetSeconds: 900)

        #expect(store.currentSpecies == creature.speciesId)
        #expect(store.strokesTotal == creature.strokesTotal)
        #expect(creature.strokesDrawn > 0)
        #expect(store.strokesDrawn == creature.strokesDrawn)
    }

    // The other half of the seeding: with nothing in progress the margin must
    // still show the creature the credit will begin, not one seeded from the
    // session's own start. Asserted by comparing what was drawn against what
    // `addWritingSeconds` actually created.
    @Test("with no creature in progress the session draws the one the credit begins")
    func drawsTheCreatureTheCreditWillBegin() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        let drawnSpecies = store.currentSpecies
        let drawnStrokes = store.strokesTotal
        store.consume(samples(500))
        store.end()

        let created = try #require(bestiary.current)
        #expect(created.speciesId == drawnSpecies)
        #expect(created.strokesTotal == drawnStrokes)
    }

    // MARK: - Crediting

    // 500 samples at stride 125 are exactly three windows, each worth the
    // stride: 7.5 s. Exactly that may reach the creature — the 600 s it
    // already carries came out of it, and crediting the session twice (once
    // per window, once again at `end()`) would read as 615.
    @Test("ending credits this session's writing time, not the carried seconds")
    func endCreditsOnlyItsOwnWriting() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        bestiary.addWritingSeconds(600, now: Date(timeIntervalSince1970: 1_788_000_000))

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        #expect(store.writingSeconds == 7.5)
        store.end()

        let creature = try #require(bestiary.current)
        #expect(creature.writingSeconds == 607.5)
    }

    @Test("an idle session credits nothing")
    func idleSessionCreditsNothing() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: -1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        store.end()

        #expect(store.writingSeconds == 0)
        #expect(bestiary.current == nil)
        #expect(bestiary.completed.isEmpty)
    }

    // The screen is built to be closed while the session runs, so a long one
    // spends most of its life backgrounded and a share of those are killed by
    // iOS. Crediting only at `end()` meant such a sitting left the creature
    // nothing at all — and never sent a `focus_stop` either.
    @Test("writing time reaches the creature without the session ending")
    func creditLandsBeforeTheSessionEnds() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))

        #expect(store.isActive)
        #expect(try #require(bestiary.current).writingSeconds == 7.5)
    }

    // Spec §8: "Ist es fertig, wird es abgelegt und das nächste beginnt —
    // überschüssige Schreibzeit derselben Sitzung zählt bereits für dieses."
    // A creature snapshotted at `begin()` clamped at its last stroke instead
    // and held there for the rest of the sitting.
    @Test("a session crossing a creature boundary draws the next creature")
    func creatureBoundaryMidSessionAdvances() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        // Five seconds short of a finished creature, so the session's 7.5 s
        // both completes it and carries 2.5 s into the next.
        bestiary.addWritingSeconds(Bestiary.secondsPerCreature - 5,
                                   now: Date(timeIntervalSince1970: 1_788_000_000))
        let before = try #require(bestiary.current)

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))

        let finished = try #require(bestiary.completed.first)
        let next = try #require(bestiary.current)
        #expect(finished.ordinal == before.ordinal)
        #expect(next.ordinal == before.ordinal + 1)
        #expect(next.writingSeconds == 2.5)

        // The margin followed the collection: it draws the new creature, and
        // a frozen one would still be showing the finished animal's full
        // stroke count.
        #expect(store.currentSpecies == next.speciesId)
        #expect(store.strokesTotal == next.strokesTotal)
        #expect(store.strokesDrawn == next.strokesDrawn)
        #expect(store.strokesDrawn < finished.strokesTotal)

        // And the finished page names the creature the session completed.
        store.end()
        #expect(store.phase == .finished(finished))
    }

    // Credit is written as windows arrive, so a batch delivered twice must not
    // pay twice. What holds this here is the builder's own invariant — it
    // drops the re-delivered samples as non-monotonic — not the store's
    // ledger; the ledger's own case is the test below.
    @Test("a re-delivered batch is credited once")
    func redeliveredBatchIsCreditedOnce() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        store.consume(samples(500))

        #expect(store.decisions.count == 3)
        #expect(try #require(bestiary.current).writingSeconds == 7.5)
    }

    // The ledger keys on the window's start *millisecond*, so two windows
    // beginning inside one millisecond are one payment. The shipped builder
    // spaces its windows 2.5 s apart and can never produce that, which is why
    // the case needs a builder whose stride is finer than the key: the guard
    // sits with the payment and has to hold on its own terms, not on the
    // spacing of today's window shape.
    @Test("two windows sharing a start millisecond are credited once")
    func sameStartMillisecondIsCreditedOnce() throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let fine = PassiveWindowBuilder(seqLen: 2, strideSamples: 1,
                                        nominalHz: 4_000, channels: 6)
        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped },
                                      windowBuilder: fine)
        store.begin(targetSeconds: 900)
        // Three samples 0.25 ms apart complete two windows, starting at
        // 0.00 ms and 0.25 ms — the same key.
        store.consume(samples(3, hz: 4_000))

        #expect(store.decisions.count == 1)
        #expect(store.writingSeconds == fine.secondsPerWindow)
        #expect(try #require(bestiary.current).writingSeconds == fine.secondsPerWindow)
    }

    // MARK: - The stream's real rate

    // `secondsPerWindow` is derived from the builder's nominal 50 Hz, not
    // measured. A study recording's 100 Hz reaching a running session would
    // be paid 2.5 s for 1.25 s of writing and hand the model half a window.
    @Test("a stream at the wrong rate credits nothing")
    func wrongRateCreditsNothing() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500, hz: 100))

        #expect(store.decisions.isEmpty)
        #expect(store.writingSeconds == 0)
        #expect(bestiary.current == nil)
    }

    // MARK: - Preemption by a study recording

    // The Watch ends a focus session on its own when a study recording
    // starts, and says nothing. Left running, the session would go on
    // classifying a stream it no longer owns — and would later send
    // `focus_stop` into the proband recording.
    @Test("a study recording ends the session without stopping the Watch")
    func preemptionEndsTheSessionAndSendsNoStop() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        store.watchPreemptedByRecording()
        await settle()

        guard case .finished = store.phase else {
            Issue.record("expected .finished phase, got \(store.phase)")
            return
        }
        #expect(stops.calls == 0)
        // The writing time the session did earn stays earned.
        #expect(try #require(bestiary.current).writingSeconds == 7.5)
    }

    // The same preemption, one phase earlier. `focus_start` has an
    // eight-second round trip; a study recording forwarded inside it is
    // answered by the Watch alone, and the reply that arrives afterwards
    // would otherwise open a session on the recording's stream.
    @Test("a recording during a start in flight refuses the start that follows")
    func preemptionDuringStartingRefusesTheLateReply() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.markStarting()
        store.watchPreemptedByRecording()

        guard case .failed(let message) = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }
        #expect(message == FocusStartRefusal.recordingInProgress.message)

        // The Watch's `.started` reply, arriving after the preemption.
        store.begin(targetSeconds: 900)
        #expect(store.phase == .failed(message))
        #expect(!store.isActive)

        // Samples still on their way from the recording's stream reach a
        // session that no longer exists, and are not credited to it.
        store.consume(samples(500))
        #expect(store.decisions.isEmpty)
        #expect(bestiary.current == nil)

        await settle()
        #expect(stops.calls == 0)
    }

    // The same preemption again, with the one step that defeated the phase
    // guard above: the failure screen has a "Zurück" button, and pressing it
    // calls `returnToIdle()`, which restores `.idle` — a phase `begin` admits.
    // The Watch's reply is still in flight at that point, so the guard needs a
    // fact that outlives the phase.
    @Test("leaving the failure screen does not let the late reply open a session")
    func preemptionSurvivesReturnToIdle() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.markStarting()
        store.watchPreemptedByRecording()
        store.returnToIdle()
        #expect(store.phase == .idle)

        // The Watch's `.started` reply, up to eight seconds after the ask.
        store.begin(targetSeconds: 900)
        #expect(!store.isActive)
        #expect(store.phase == .failed(FocusStartRefusal.recordingInProgress.message))

        // The proband's writing must not reach this phone owner's creature.
        store.consume(samples(500))
        #expect(store.decisions.isEmpty)
        #expect(bestiary.current == nil)

        await settle()
        #expect(stops.calls == 0)
    }

    // The guard above must not become a latch. Once the recording is over the
    // user starts another session, and that fresh ask is what clears it.
    @Test("a fresh ask clears the preemption and starts normally")
    func aFreshAskClearsThePreemption() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.markStarting()
        store.watchPreemptedByRecording()
        store.returnToIdle()

        store.markStarting()
        store.begin(targetSeconds: 900)
        #expect(store.isActive)

        store.consume(samples(250))
        #expect(store.decisions.count == 1)
    }

    // MARK: - The sixty-minute cap

    // The cap is a battery guarantee: the Watch streams raw sensors for the
    // whole session. A scheduled task alone cannot carry it, because a
    // suspended app runs no timers — so arriving samples re-check the wall
    // clock, and a session past its cap ends instead of classifying them.
    @Test("the cap ends a session whose deadline passed while the app was asleep")
    func capEndsSessionOnLateSamples() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { .stopped })
        let start = Date().addingTimeInterval(-(FocusSessionStore.hardCapSeconds + 1))
        store.begin(targetSeconds: 900, at: start)
        store.consume(samples(500))

        guard case .finished = store.phase else {
            Issue.record("expected .finished phase, got \(store.phase)")
            return
        }
        #expect(store.decisions.isEmpty)
    }

    // And the cap holds with no screen and no samples at all: a session left
    // running on a phone in a pocket stops itself and asks the Watch to stop.
    @Test("the cap stops the session and the Watch without any screen")
    func capStopsTheWatchOnItsOwn() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      hardCapSeconds: 0.05,
                                      stopOnWatch: { stops.calls += 1; return stops.outcome })
        store.begin(targetSeconds: 900)
        await settle()
        await settle()

        guard case .finished = store.phase else {
            Issue.record("expected .finished phase, got \(store.phase)")
            return
        }
        #expect(stops.calls == 1)
    }

    /// Why an injected cap: the shipped value is two hours. Testing the
    /// behaviour against the constant would cost that long per run, so the
    /// test proves the mechanism and the device check proves the number.
    // Why: the margin follows `capStopsTheWatchOnItsOwn` (cap 0.05s, two
    // settle() = 0.3s wait, 6x) rather than the brief's tighter 2x — the
    // mechanism under test is itself a Task.sleep plus a MainActor hop, and
    // shrinking this back invites flakiness.
    @Test func sessionEndsAtTheInjectedCap() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(bestiary: bestiary, hardCapSeconds: 0.05)

        store.beginForTesting(targetSeconds: 3600)
        #expect(store.isActive)

        await settle()
        await settle()
        #expect(!store.isActive)
    }

    // MARK: - Stopping the Watch

    // `focus_stop` ends the Watch's capture outright. A start the Watch
    // refused never began one, so sending it would stop a study recording
    // that was never this session's to stop.
    @Test("a refused start never asks the Watch to stop")
    func refusedStartDoesNotStopTheWatch() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.markStarting()
        store.failToStart("refused")
        await settle()

        #expect(stops.calls == 0)
        guard case .failed = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }
    }

    // The model can only fail once the session is already running, so the
    // Watch is streaming and has to be stopped — otherwise a failure the user
    // can see leaves sensors running they cannot.
    @Test("a model failure mid-session stops the Watch")
    func modelFailureStopsTheWatch() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(makeClassifier: { throw Boom() },
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(250))
        await settle()

        guard case .failed = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }
        #expect(stops.calls == 1)
    }

    // An unanswered stop means the Watch may still be streaming. The phase
    // must move anyway — waiting on it is the hang this screen exists not to
    // repeat — so the doubt is reported instead of held.
    @Test("an unconfirmed stop is reported, not waited on")
    func unconfirmedStopIsReported() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()
        stops.outcome = .noAnswer

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return stops.outcome })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        store.end()

        // The phase is already final before the Watch has answered anything.
        guard case .finished = store.phase else {
            Issue.record("expected .finished phase, got \(store.phase)")
            return
        }
        #expect(!store.stopUnconfirmed)
        await settle()
        #expect(store.stopUnconfirmed)
    }

    @Test("returning to idle clears the finished page but never a live session")
    func returnToIdleOnlyLeavesFinishedStates() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        store.returnToIdle()
        #expect(store.isActive)
        #expect(!store.decisions.isEmpty)

        store.end()
        store.returnToIdle()
        #expect(store.phase == .idle)
        #expect(store.decisions.isEmpty)
        await settle()
        #expect(stops.calls == 1)
    }

    // The Watch ends capture on its own when the workout session cannot run.
    // Until it said so, the page simply stopped growing and the `focus_stop`
    // that followed came back `no focus session` — which reads as a clean
    // stop. The session must land on the failure screen instead, and the
    // writing it did earn stays earned.
    @Test("a workout failure on the Watch fails the running session")
    func workoutFailureFailsTheRunningSession() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.begin(targetSeconds: 900)
        store.consume(samples(500))
        store.watchWorkoutFailed()

        guard case .failed(let message) = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }
        #expect(!message.isEmpty)
        #expect(!store.isActive)
        #expect(try #require(bestiary.current).writingSeconds == 7.5)

        // No focus_stop: the Watch has already stopped, and the notice is what
        // said so.
        await settle()
        #expect(stops.calls == 0)
    }

    // The workout prompt is answered on the Watch, so a denial commonly lands
    // inside the eight seconds a focus_start may take. The reply that follows
    // must not open a session on a stream that already died.
    @Test("a workout failure during a start in flight refuses the late reply")
    func workoutFailureDuringStartingRefusesTheLateReply() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.markStarting()
        store.watchWorkoutFailed()

        guard case .failed(let message) = store.phase else {
            Issue.record("expected .failed phase, got \(store.phase)")
            return
        }

        store.begin(targetSeconds: 900)
        #expect(store.phase == .failed(message))
        #expect(!store.isActive)
        await settle()
        #expect(stops.calls == 0)
    }

    // The notice repeats on every poll for as long as the Watch's flag stands.
    // A session the user has already left behind must not be dragged back to
    // the failure screen by it.
    @Test("a repeated notice leaves an idle picker alone")
    func workoutFailureLeavesIdleAlone() async {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let stops = StopRecorder()

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1),
                                      bestiary: bestiary,
                                      stopOnWatch: { stops.calls += 1; return .stopped })
        store.markStarting()
        store.watchWorkoutFailed()
        store.returnToIdle()
        #expect(store.phase == .idle)

        store.watchWorkoutFailed()
        #expect(store.phase == .idle)
        await settle()
        #expect(stops.calls == 0)
    }

    // MARK: - Naming the ending

    @Test func endingReportsWhoEndedIt() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(bestiary: bestiary, hardCapSeconds: FocusSessionStore.hardCapSeconds)

        store.beginForTesting(targetSeconds: 1500)
        store.end()
        #expect(store.finishReason == .user)
    }

    /// Why this one matters most: a study recording taking the Watch is the
    /// one ending the user did not cause and cannot see coming.
    @Test func preemptionIsNamedAsPreemption() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(bestiary: bestiary, hardCapSeconds: FocusSessionStore.hardCapSeconds)

        store.beginForTesting(targetSeconds: 1500)
        store.watchPreemptedByRecording()
        #expect(store.finishReason == .studyPreemption)
    }

    @Test func workoutFailureIsNamedAsWatchFailure() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(bestiary: bestiary, hardCapSeconds: FocusSessionStore.hardCapSeconds)

        store.beginForTesting(targetSeconds: 1500)
        store.watchWorkoutFailed()
        #expect(store.finishReason == .watchFailure)
    }
}
