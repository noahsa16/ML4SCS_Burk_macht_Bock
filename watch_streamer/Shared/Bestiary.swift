import Foundation

/// One collected creature.
public nonisolated struct BestiaryEntry: Codable, Equatable, Sendable {
    public let speciesId: Int
    public let dateMs: Int64
    public let strokesDrawn: Int
    public let strokesTotal: Int
    public let writingSeconds: Double

    public init(speciesId: Int, dateMs: Int64, strokesDrawn: Int,
                strokesTotal: Int, writingSeconds: Double) {
        self.speciesId = speciesId
        self.dateMs = dateMs
        self.strokesDrawn = strokesDrawn
        self.strokesTotal = strokesTotal
        self.writingSeconds = writingSeconds
    }

    public var isComplete: Bool { strokesDrawn >= strokesTotal }
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
