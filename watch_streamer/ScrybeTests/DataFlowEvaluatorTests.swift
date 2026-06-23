import Testing
import Foundation
@testable import WatchStreamer

@Suite("DataFlowEvaluator")
struct DataFlowEvaluatorTests {
    @Test("first observation is baseline, not flow")
    func baselineSkip() {
        var e = DataFlowEvaluator()
        #expect(e.update(count: 1000, now: Date()) == false)
    }

    @Test("counter increase within window is flowing")
    func flows() {
        var e = DataFlowEvaluator()
        let t0 = Date()
        _ = e.update(count: 1000, now: t0)
        #expect(e.update(count: 1010, now: t0.addingTimeInterval(1)) == true)
    }

    @Test("stale: no increase past window is not flowing")
    func stale() {
        var e = DataFlowEvaluator()
        let t0 = Date()
        _ = e.update(count: 1000, now: t0)
        _ = e.update(count: 1010, now: t0.addingTimeInterval(1))
        #expect(e.update(count: 1010, now: t0.addingTimeInterval(7)) == false)
    }
}
