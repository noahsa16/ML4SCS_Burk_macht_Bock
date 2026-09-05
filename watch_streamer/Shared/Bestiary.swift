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
    ///
    /// Drawn from a shuffled deck rather than hashed independently: eight
    /// consecutive ordinals form a block that holds each species exactly once,
    /// so a collector meets all eight before any of them repeats. Hashing each
    /// ordinal on its own looks uniform in the limit and is visibly lumpy at
    /// the size a collection actually reaches — the previous version handed
    /// out one species ten times and another not at all across the first
    /// twenty-four creatures.
    public static func species(seed: Int64) -> Int {
        let count = Int64(speciesCount)
        // Floored division, so negative seeds stay inside their own block
        // instead of folding onto the block above.
        let block = seed >= 0 ? seed / count : (seed - count + 1) / count
        let index = Int(seed - block * count)
        return deck(block: block)[index]
    }

    /// The species order for one block, with its first entry pushed aside when
    /// it would repeat the last of the block before, so a block boundary
    /// cannot show the same creature twice either.
    private static func deck(block: Int64) -> [Int] {
        var order = shuffled(block: block)
        if order[0] == shuffled(block: block &- 1)[speciesCount - 1] {
            order.swapAt(0, 1)
        }
        return order
    }

    /// Every species once, in an order that depends only on the block.
    private static func shuffled(block: Int64) -> [Int] {
        var order = Array(0..<speciesCount)
        var state = UInt64(bitPattern: block)
        for i in stride(from: speciesCount - 1, to: 0, by: -1) {
            state = mix(state)
            order.swapAt(i, Int(state % UInt64(i + 1)))
        }
        return order
    }

    private static func mix(_ seed: UInt64) -> UInt64 {
        var x = seed &+ 0x9E37_79B9_7F4A_7C15
        x = (x ^ (x >> 30)) &* 0xBF58_476D_1CE4_E5B9
        x = (x ^ (x >> 27)) &* 0x94D0_49BB_1331_11EB
        return x ^ (x >> 31)
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
