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

    /// `count` samples at 50 Hz beginning at `start`. The offset matters: two
    /// batches must form one monotonic stream, or the builder correctly reads
    /// the second as a gap and resets — which is the behaviour under test
    /// elsewhere, not something to work around here.
    private func samples(_ count: Int, from start: TimeInterval = 0) -> [PassiveSample] {
        (0..<count).map { i in
            PassiveSample(timestamp: start + Double(i) / 50.0,
                          x: 0.1, y: 0.2, z: 0.98,
                          rx: 0.01, ry: 0.02, rz: 0.03)
        }
    }

    @Test("one decision per stride once the first window is full")
    func decisionsFollowStride() {
        let store = FocusSessionStore(classifier: FixedClassifier(value: 1))
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
        let store = FocusSessionStore(classifier: FixedClassifier(value: 1))
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

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1))
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
        let store = FocusSessionStore(makeClassifier: { throw Boom() })
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
        let counter = Counter()
        let store = FocusSessionStore(makeClassifier: {
            counter.calls += 1
            throw Boom()
        })
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

        #expect(store.carriedSeconds == 600)
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
    // stride: 7.5 s. Only those seconds may be credited — `carriedSeconds`
    // came out of the creature, and adding it back would count it twice.
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
}
