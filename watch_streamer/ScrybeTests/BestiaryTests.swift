import Testing
import Foundation
@testable import WatchStreamer

@Suite("Bestiary")
struct BestiaryTests {

    // An earlier draft grew the creature once per completed writing run, which
    // paid for fragmentation: four short bursts earned four strokes where one
    // continuous stretch earned one. Growth follows the amount written.
    @Test("the same writing time draws the same creature, however broken up")
    func invariantToFragmentation() {
        let whole = Bestiary.strokesDrawn(writingSeconds: 600,
                                          targetSeconds: 1_500, strokesTotal: 10)
        let pieces = Bestiary.strokesDrawn(writingSeconds: 150 * 4,
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

    @Test("the species is reproducible from the session start")
    func speciesIsDeterministic() {
        let a = Bestiary.species(forSessionStartMs: 1_788_010_163_073)
        let b = Bestiary.species(forSessionStartMs: 1_788_010_163_073)
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
}
