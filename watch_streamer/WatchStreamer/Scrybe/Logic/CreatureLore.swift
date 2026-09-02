import Foundation

/// The line under a creature's name — "Erster Atem am Morgen" — one per
/// species. The names themselves are English proper nouns and live in the
/// generated `Marginalia.names`; the epithets are copy, so they are localized
/// here and kept out of the generated file, which a redraw overwrites.
enum CreatureLore {

    static func epithet(forSpecies id: Int) -> String {
        switch id {
        case 0: return String(localized: "Erster Atem am Morgen")
        case 1: return String(localized: "Trägt sein Haus und alle Zeit der Welt")
        case 2: return String(localized: "Steht, wo andere fallen")
        case 3: return String(localized: "Liest zwischen den Zeilen")
        case 4: return String(localized: "Frisst sich durch Kapitel")
        case 5: return String(localized: "Bellt nur bei Vollmond")
        case 6: return String(localized: "Schwimmt gegen den Tintenstrom")
        case 7: return String(localized: "Zwei Meinungen, ein Flug")
        default: return ""
        }
    }
}
