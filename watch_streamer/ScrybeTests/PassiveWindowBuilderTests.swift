import Testing
import Foundation
@testable import WatchStreamer

@Suite("PassiveWindowBuilder")
struct PassiveWindowBuilderTests {

    /// Evenly spaced samples at 50 Hz, values encoding their index so channel
    /// order is checkable.
    private func samples(count: Int, from start: TimeInterval = 0,
                         hz: Double = 50) -> [PassiveSample] {
        (0..<count).map { i in
            PassiveSample(timestamp: start + Double(i) / hz,
                          x: Float(i), y: Float(i) + 0.1, z: Float(i) + 0.2)
        }
    }

    @Test("exactly seqLen samples yields one window")
    func oneWindow() {
        var b = PassiveWindowBuilder()
        let out = b.append(samples(count: 250))
        #expect(out.count == 1)
        #expect(out[0].values.count == 750)
    }

    @Test("fewer than seqLen samples yields nothing")
    func partialWindow() {
        var b = PassiveWindowBuilder()
        #expect(b.append(samples(count: 249)).isEmpty)
    }

    @Test("stride produces a second window after 125 more samples")
    func overlappingWindows() {
        var b = PassiveWindowBuilder()
        let out = b.append(samples(count: 375))
        #expect(out.count == 2)
        // Second window starts one stride later.
        #expect(abs(out[1].startTimestamp - 125.0 / 50.0) < 1e-9)
    }

    // The layout is fixed by the exported artifact; getting it wrong yields
    // confident nonsense rather than an error, so it is asserted directly.
    @Test("values are row-major x, y, z")
    func channelOrder() {
        var b = PassiveWindowBuilder()
        let out = b.append(samples(count: 250))
        let v = out[0].values
        #expect(v[0] == 0.0)          // sample 0, x
        #expect(v[1] == 0.1)          // sample 0, y
        #expect(v[2] == 0.2)          // sample 0, z
        #expect(v[3] == 1.0)          // sample 1, x
        #expect(v[747] == 249.0)      // sample 249, x
    }

    @Test("a recorder gap discards the partial window instead of straddling it")
    func gapResetsBuffer() {
        var b = PassiveWindowBuilder()
        #expect(b.append(samples(count: 200)).isEmpty)
        // Jump two seconds — far beyond maxGapSeconds.
        let afterGap = samples(count: 200, from: 6.0)
        #expect(b.append(afterGap).isEmpty, "must not complete a straddling window")
        // 50 more samples on the far side of the gap now complete a clean one.
        let more = samples(count: 50, from: 6.0 + 200.0 / 50.0)
        #expect(b.append(more).count == 1)
    }

    @Test("a gap inside tolerance does not reset")
    func smallGapTolerated() {
        var b = PassiveWindowBuilder()
        _ = b.append(samples(count: 200))
        // 60 ms hole: under the 100 ms default.
        var next = samples(count: 50, from: 200.0 / 50.0 + 0.06)
        next.insert(contentsOf: [], at: 0)
        #expect(b.append(next).count == 1)
    }

    @Test("non-monotonic samples are dropped")
    func nonMonotonicDropped() {
        var b = PassiveWindowBuilder()
        var s = samples(count: 250)
        // Insert a sample that goes backwards in time. The sentinel is
        // negative so it cannot collide with the index-derived values above.
        let sentinel: Float = -777
        s.insert(PassiveSample(timestamp: 0.5, x: sentinel, y: sentinel, z: sentinel),
                 at: 100)
        let out = b.append(s)
        #expect(out.count == 1)
        #expect(!out[0].values.contains(sentinel))
    }

    @Test("reset clears buffered samples")
    func resetClears() {
        var b = PassiveWindowBuilder()
        _ = b.append(samples(count: 200))
        b.reset()
        #expect(b.append(samples(count: 249, from: 100)).isEmpty)
    }

    // Overlapping windows must not each claim their full span, or a day of
    // writing would be reported as two.
    @Test("a window is credited its stride, not its span")
    func creditIsStride() {
        let b = PassiveWindowBuilder()
        #expect(b.secondsPerWindow == 2.5)
        #expect(Double(b.seqLen) / b.nominalHz == 5.0)
    }

    // The model's channel order is fixed by the exported artifact; getting it
    // wrong produces confident nonsense rather than an error.
    @Test("six-channel windows are row-major ax, ay, az, rx, ry, rz")
    func sixChannelLayout() {
        var b = PassiveWindowBuilder(seqLen: 2, strideSamples: 2,
                                     nominalHz: 50, channels: 6)
        let s = (0..<2).map { i in
            PassiveSample(timestamp: Double(i) / 50.0,
                          x: 1, y: 2, z: 3, rx: 4, ry: 5, rz: 6)
        }
        let windows = b.append(s)
        #expect(windows.count == 1)
        #expect(windows[0].values == [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6])
    }
}
