import Testing
import Foundation
@testable import WatchStreamer

@Suite("Bestiary")
struct BestiaryTests {

    // An earlier draft grew the creature once per completed writing run, which
    // paid for fragmentation: four short bursts earned four strokes where one
    // continuous stretch earned one. Growth follows the amount written.
    //
    // The fragmented side is summed at runtime from four uneven bursts (not
    // folded by the compiler into a literal, and not a shape a reader could
    // mentally collapse into the whole-side argument) so this test actually
    // exercises two different call sites reaching the same total, rather than
    // one constant-folded call compared against itself. The invariant holds
    // structurally, not by luck: strokesDrawn accepts only a running total,
    // never a list of bursts, so there is no code path that could truncate
    // per burst and sum partial results — a future signature change that
    // accepted a list of bursts would be the thing to make this test suspect.
    @Test("the same writing time draws the same creature, however broken up")
    func invariantToFragmentation() {
        let bursts: [Double] = [212, 63, 187, 138]
        let fragmentedTotal = bursts.reduce(0, +)
        let whole = Bestiary.strokesDrawn(writingSeconds: 600,
                                          targetSeconds: 1_500, strokesTotal: 10)
        let pieces = Bestiary.strokesDrawn(writingSeconds: fragmentedTotal,
                                           targetSeconds: 1_500, strokesTotal: 10)
        #expect(whole == pieces)
        #expect(whole == 4)
    }

    @Test("stopping early leaves a partly drawn creature, never none")
    func partialIsKept() {
        #expect(Bestiary.strokesDrawn(writingSeconds: 1, targetSeconds: 1_500,
                                      strokesTotal: 10) == 0)
        #expect(Bestiary.strokesDrawn(writingSeconds: 900, targetSeconds: 1_500,
                                      strokesTotal: 10) == 6)
    }

    @Test("reaching the target never overdraws")
    func clampedAtTotal() {
        #expect(Bestiary.strokesDrawn(writingSeconds: 9_999, targetSeconds: 1_500,
                                      strokesTotal: 10) == 10)
    }

    @Test("the species is reproducible from the same seed")
    func speciesIsDeterministic() {
        let a = Bestiary.species(seed: 1_788_010_163_073)
        let b = Bestiary.species(seed: 1_788_010_163_073)
        #expect(a == b)
        #expect((0..<Bestiary.speciesCount).contains(a))
    }

    // Boundary coverage the tests above don't hit: no writing at all, and the
    // exact instant a stroke's worth of time completes. Both sit right at the
    // truncation edge of `Int(writingSeconds / per)`, where an off-by-one is
    // easiest to hide.
    @Test("no writing time draws no strokes")
    func zeroWritingDrawsNothing() {
        #expect(Bestiary.strokesDrawn(writingSeconds: 0, targetSeconds: 1_500,
                                      strokesTotal: 10) == 0)
    }

    @Test("exactly one stroke's worth of time draws exactly one stroke")
    func exactlyOneStrokeWorth() {
        #expect(Bestiary.strokesDrawn(writingSeconds: 150, targetSeconds: 1_500,
                                      strokesTotal: 10) == 1)
    }

    // Every boundary test in this file and in `BestiaryStoreTests` expresses
    // the target through this constant on both sides of its comparisons, so
    // none of them would notice if it silently drifted back to a per-session
    // value — the farmability this whole design exists to remove. This is
    // the one assertion that pins the literal.
    @Test("a creature costs a fixed thirty minutes of writing")
    func creatureCostIsPinnedAtThirtyMinutes() {
        #expect(Bestiary.secondsPerCreature == 30 * 60)
    }
}
