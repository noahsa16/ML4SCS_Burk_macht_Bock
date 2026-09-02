import Testing
import SwiftUI
@testable import WatchStreamer

@Suite("Creature naming")
struct CreatureNamingTests {

    @Test func everySpeciesHasAName() {
        for id in Marginalia.names.indices {
            #expect(!Marginalia.name(forSpecies: id).isEmpty)
        }
    }

    /// Why an empty string and not a crash: a species id from a stored entry
    /// written by a future build must not take the screen down.
    @Test func anUnknownSpeciesNamesNothing() {
        #expect(Marginalia.name(forSpecies: -1).isEmpty)
        #expect(Marginalia.name(forSpecies: Marginalia.names.count).isEmpty)
    }

    /// Compile-level: if this line builds, the canvas is reachable outside
    /// `BestiaryView`, which is the visibility defect being fixed.
    @Test @MainActor func canvasIsUsableOutsideTheGallery() {
        _ = CreatureCanvas(speciesId: 0, strokesDrawn: 3)
    }
}
