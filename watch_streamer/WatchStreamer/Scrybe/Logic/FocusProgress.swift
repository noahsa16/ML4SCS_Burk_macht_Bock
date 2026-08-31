import Foundation

/// How much of the creature in progress is still undrawn.
///
/// One function, three callers: the ready screen, the running screen and the
/// finished screen must not disagree about the same number. The input is
/// always `BestiaryStore.creatureInProgress().writingSeconds` — the store
/// defines that as the creature the next credited second grows, so the value
/// is read after any species change rather than before it.
enum FocusProgress {

    static func remainingSeconds(writingSeconds: Double) -> Double {
        max(0, Bestiary.secondsPerCreature - writingSeconds)
    }

    /// Whether the chosen session would finish this creature and begin another.
    /// A goalless session says nothing: it has no length to compare.
    static func exceedsCreature(remainingSeconds: Double,
                                sessionSeconds: Double?) -> Bool {
        guard let sessionSeconds else { return false }
        return sessionSeconds > remainingSeconds
    }
}
