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
///
/// `ordinal` — not `startedMs` — is the stable identity and the species
/// seed. A credit that both finishes one creature and opens the next hands
/// both entries the *same* `now`, so `startedMs` alone cannot tell them
/// apart: seeding species from it, or using it as `Identifiable`'s `id`,
/// would mint two entries that are the same creature twice (identical id,
/// identical species) whenever a single session's credit spans a creature
/// boundary — which a session long enough to both finish and restart a
/// creature does routinely. `ordinal` increments once per creature ever
/// begun, so it never collides even when two creatures share a `startedMs`.
public nonisolated struct BestiaryEntry: Codable, Identifiable, Equatable, Sendable {
    public let ordinal: Int64
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

    public init(ordinal: Int64, speciesId: Int, startedMs: Int64, strokesTotal: Int,
                writingSeconds: Double, completedMs: Int64? = nil) {
        self.ordinal = ordinal
        self.speciesId = speciesId
        self.startedMs = startedMs
        self.strokesTotal = strokesTotal
        self.writingSeconds = writingSeconds
        self.completedMs = completedMs
    }

    private enum CodingKeys: String, CodingKey {
        case ordinal, speciesId, startedMs, strokesTotal, writingSeconds, completedMs
    }

    /// Decoded field by field so a shape change degrades one value instead of
    /// the whole collection.
    ///
    /// **Every field added here must keep using `decodeIfPresent` with a
    /// default.** A single non-optional field would make every stored
    /// `bestiary.json` written before it undecodable, and `BestiaryStore`
    /// answers an undecodable file by suspending persistence for the rest of
    /// the process — leaving the collection unrecoverable and `deleteAll()`,
    /// which destroys it, the only way out. Unknown keys are ignored by
    /// `JSONDecoder` already, so this covers the other direction too.
    ///
    /// `ordinal` falls back to `startedMs`, the identity it replaced, rather
    /// than to a constant: it is the species seed and `Identifiable`'s `id`,
    /// so several entries sharing one default would read as the same creature
    /// repeated.
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        startedMs = try c.decodeIfPresent(Int64.self, forKey: .startedMs) ?? 0
        ordinal = try c.decodeIfPresent(Int64.self, forKey: .ordinal) ?? startedMs
        speciesId = try c.decodeIfPresent(Int.self, forKey: .speciesId)
            ?? Bestiary.species(seed: ordinal)
        strokesTotal = try c.decodeIfPresent(Int.self, forKey: .strokesTotal) ?? 0
        writingSeconds = try c.decodeIfPresent(Double.self, forKey: .writingSeconds) ?? 0
        completedMs = try c.decodeIfPresent(Int64.self, forKey: .completedMs)
    }

    public var id: Int64 { ordinal }
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

    /// Deterministic species for a seed value. A stable seed (a creature's
    /// `ordinal`, not a timestamp — see `BestiaryEntry`'s header) means
    /// abandoning and restarting cannot reroll for a rarer creature, and two
    /// creatures never land on the same identity by construction.
    public static func species(seed: Int64) -> Int {
        var x = UInt64(bitPattern: seed)
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
