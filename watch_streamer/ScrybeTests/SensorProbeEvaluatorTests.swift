import Testing
import Foundation
@testable import WatchStreamer

@Suite("SensorProbeEvaluator")
struct SensorProbeEvaluatorTests {

    /// 1 Stunde bei sauberen 50 Hz: 180_000 Samples, alle Intervalle 20 ms.
    private func healthy(durationSeconds: Double = 3600) -> SensorProbeStats {
        let n = Int(durationSeconds * 50)
        return SensorProbeStats(
            sampleCount: n,
            firstTimestamp: 0,
            lastTimestamp: durationSeconds,
            requestedSeconds: durationSeconds,
            intervalBucketsMs: [0: 0, 20: n - 1, 40: 0, 100: 0, 1000: 0],
            maxGapSeconds: 0.02,
            nonMonotonicCount: 0,
            fetchReturnedNil: false
        )
    }

    @Test("saubere Aufzeichnung besteht alle Kriterien")
    func healthyPasses() {
        let v = SensorProbeEvaluator.evaluate(healthy())
        #expect(v.passed == true)
        #expect(v.failures.isEmpty)
    }

    @Test("nil-Rueckgabe ist der dokumentierte Ausfallmodus")
    func nilFetchFails() {
        var s = healthy()
        s.fetchReturnedNil = true
        let v = SensorProbeEvaluator.evaluate(s)
        #expect(v.passed == false)
        #expect(v.failures.contains(.fetchReturnedNil))
    }

    @Test("nicht-monotone Zeitstempel schlagen fehl")
    func nonMonotonicFails() {
        var s = healthy()
        s.nonMonotonicCount = 1
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.nonMonotonic))
    }

    @Test("Rate unterhalb 45 Hz schlaegt fehl")
    func lowRateFails() {
        var s = healthy()
        s.sampleCount = Int(3600 * 40)   // 40 Hz
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.effectiveRate))
    }

    @Test("Rate oberhalb 55 Hz schlaegt fehl")
    func highRateFails() {
        var s = healthy()
        s.sampleCount = Int(3600 * 60)
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.effectiveRate))
    }

    @Test("mehr als ein Prozent lange Intervalle schlaegt fehl")
    func intervalTailFails() {
        var s = healthy()
        let n = s.sampleCount - 1
        s.intervalBucketsMs = [0: 0, 20: n - n / 50, 40: n / 50, 100: 0, 1000: 0]  // 2 %
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.intervalTail))
    }

    @Test("Coverage unter 98 Prozent schlaegt fehl")
    func coverageFails() {
        var s = healthy()
        s.sampleCount = Int(3600 * 50 * 0.9)
        let v = SensorProbeEvaluator.evaluate(s)
        #expect(v.failures.contains(.coverage))
    }

    @Test("Coverage wird gegen die angeforderte Dauer gerechnet, nicht gegen die gelieferte Spanne")
    func coverageUsesRequestedDuration() {
        // Why: eine Aufzeichnung, die nach 10 min abbricht, hat ueber ihre
        // eigene Spanne perfekte Coverage — der Ausfall zeigt sich nur gegen
        // die angeforderten 3600 s.
        var s = healthy(durationSeconds: 600)
        s.requestedSeconds = 3600
        #expect(SensorProbeEvaluator.evaluate(s).failures.contains(.coverage))
    }

    @Test("Verdikt zaehlt mehrere Fehlschlaege gleichzeitig")
    func multipleFailures() {
        var s = healthy()
        s.nonMonotonicCount = 3
        s.sampleCount = Int(3600 * 20)
        let v = SensorProbeEvaluator.evaluate(s)
        #expect(v.failures.count >= 2)
        #expect(v.passed == false)
    }
}
