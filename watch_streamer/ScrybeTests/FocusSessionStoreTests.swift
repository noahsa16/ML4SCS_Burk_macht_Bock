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

    /// `count` samples at 50 Hz, six channels, starting at t = 0.
    private func samples(_ count: Int) -> [PassiveSample] {
        (0..<count).map { i in
            PassiveSample(timestamp: Double(i) / 50.0, x: 0.1, y: 0.2, z: 0.98)
        }
    }

    @Test("one decision per stride once the first window is full")
    func decisionsFollowStride() {
        let store = FocusSessionStore(classifier: FixedClassifier(value: 1))
        store.beginForTesting(targetSeconds: 1_500)
        store.consume(samples(250))
        #expect(store.decisions.count == 1)
        store.consume(samples(125))
        #expect(store.decisions.count == 2)
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
}
