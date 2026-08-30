import Testing
import SwiftUI
@testable import WatchStreamer

@Suite("Marginalia")
struct MarginaliaTests {

    // The upper bound is deliberately loose. Creatures are traced at the
    // fidelity of their source, so a densely drawn one carries two hundred
    // strokes where a plain one carries eighty — and at a fixed rate that only
    // means it grows more finely, never that it costs more writing. The lower
    // bound is the real check: a creature of one or two strokes is a conversion
    // that went wrong.
    @Test("every species has an ordered set of strokes in a plausible range")
    func strokeCounts() {
        for id in 0..<Bestiary.speciesCount {
            let strokes = Marginalia.strokes(forSpecies: id)
            #expect((6...400).contains(strokes.count),
                    "species \(id) has \(strokes.count) strokes")
            #expect(Marginalia.strokeCount(forSpecies: id) == strokes.count)
        }
    }

    // The renderer and the app both map the 100x100 box onto their own frame.
    // A stroke outside it is drawn clipped in one and not the other, so the
    // creature a session shows would differ from the one that was approved.
    @Test("every stroke stays inside the 100x100 box")
    func strokesAreInBounds() {
        for id in 0..<Bestiary.speciesCount {
            for (index, stroke) in Marginalia.strokes(forSpecies: id).enumerated() {
                let b = stroke.boundingRect
                #expect(b.minX >= -0.5 && b.minY >= -0.5,
                        "species \(id) stroke \(index) starts at \(b.origin)")
                #expect(b.maxX <= 100.5 && b.maxY <= 100.5,
                        "species \(id) stroke \(index) ends at \(b.maxX), \(b.maxY)")
            }
        }
    }

    @Test("each species is named")
    func namesMatchCount() {
        #expect(Marginalia.names.count == Bestiary.speciesCount)
        // Computed outside the macro: `contains(where:)` reads as throwing
        // inside #expect's expansion.
        let anyBlank = Marginalia.names.contains { $0.isEmpty }
        #expect(anyBlank == false)
    }

    // An unknown id must not crash a running session; it draws nothing.
    @Test("an id outside the roster yields no strokes")
    func unknownSpeciesIsEmpty() {
        #expect(Marginalia.strokes(forSpecies: Bestiary.speciesCount).isEmpty)
        #expect(Marginalia.strokes(forSpecies: -1).isEmpty)
    }
}
