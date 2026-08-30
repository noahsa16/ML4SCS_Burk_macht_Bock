import Foundation

/// One collected creature.
///
/// A creature belongs to accumulated writing time, not to a session, so this
/// tracks the creature's own lifetime rather than any one sitting:
/// `startedMs` is when its first second of writing was credited, and
/// `writingSeconds` keeps growing across however many sessions it takes to
/// finish it. `strokesTotal` is stored rather than re-derived from
/// `speciesId` because this type lives in code shared with the watch target,
/// which cannot see `Marginalia` (app-target only, imports SwiftUI).
public nonisolated struct BestiaryEntry: Codable, Identifiable, Equatable, Sendable {
    public let speciesId: Int
    public let startedMs: Int64
    public let strokesTotal: Int
    public let writingSeconds: Double
    /// Wall-clock ms this creature reached `Bestiary.secondsPerCreature`, or
    /// `nil` while it is still being drawn. The persisted fact `isComplete`
    /// is derived from, rather than `writingSeconds` crossing a threshold
    /// again — the store sets both at the same instant, but only one of them
    /// needs to be the source of truth.
    public let completedMs: Int64?

    public init(speciesId: Int, startedMs: Int64, strokesTotal: Int,
                writingSeconds: Double, completedMs: Int64? = nil) {
        self.speciesId = speciesId
        self.startedMs = startedMs
        self.strokesTotal = strokesTotal
        self.writingSeconds = writingSeconds
        self.completedMs = completedMs
    }

    public var id: Int64 { startedMs }
    public var isComplete: Bool { completedMs != nil }

    /// Strokes earned so far by `writingSeconds`, against the fixed
    /// per-creature target every consumer draws against.
    public var strokesDrawn: Int {
        Bestiary.strokesDrawn(writingSeconds: writingSeconds,
                              targetSeconds: Bestiary.secondsPerCreature,
                              strokesTotal: strokesTotal)
    }
}

public nonisolated enum Bestiary {
    public static let speciesCount = 8

    /// Writing time one creature costs, whatever the session's own target is.
    ///
    /// Tying this to the session target instead would let a five-minute goal
    /// earn the same finished creature as a forty-five-minute one. A collection
    /// that can be earned in five minutes counts sessions, not writing — and
    /// sessions can be sliced as small as one likes. At a fixed rate the target
    /// sets the length of the sitting; it never sets the price of the animal.
    public static let secondsPerCreature: Double = 30 * 60

    /// Seeded from the session's start so abandoning and restarting cannot
    /// reroll for a rarer creature.
    public static func species(forSessionStartMs ms: Int64) -> Int {
        var x = UInt64(bitPattern: Int64(ms))
        x ^= x >> 33; x = x &* 0xff51afd7ed558ccd
        x ^= x >> 33; x = x &* 0xc4ceb9fe1a85ec53
        x ^= x >> 33
        return Int(x % UInt64(speciesCount))
    }

    /// Strokes earned by writing time. Pauses hold this still; they never
    /// reduce it, and there is no failure state — a short session simply
    /// leaves a partly drawn creature.
    public static func strokesDrawn(writingSeconds: Double,
                                    targetSeconds: Double,
                                    strokesTotal: Int) -> Int {
        guard targetSeconds > 0, strokesTotal > 0 else { return 0 }
        let per = targetSeconds / Double(strokesTotal)
        return min(strokesTotal, max(0, Int(writingSeconds / per)))
    }
}
