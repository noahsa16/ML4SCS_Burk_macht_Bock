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
}
