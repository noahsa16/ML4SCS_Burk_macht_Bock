import Foundation

/// The creature in progress, as the phone tells it to the Watch.
///
/// The collection lives on the phone (`BestiaryStore`); the Watch only shows
/// how far the current creature has been drawn. Like the daily goal, the
/// snapshot rides on every command and poll reply, so the Watch never needs
/// to ask and a fresh install catches up on the first poll. `nil` fields on
/// the wire mean "no creature yet" — the phone sends no keys at all then, and
/// the Watch keeps drawing nothing rather than a stale animal.
public nonisolated struct WatchCreatureSnapshot: Codable, Equatable, Sendable {
    public let speciesId: Int
    public let strokesTotal: Int
    public let writingSeconds: Double

    public init(speciesId: Int, strokesTotal: Int, writingSeconds: Double) {
        self.speciesId = speciesId
        self.strokesTotal = strokesTotal
        self.writingSeconds = writingSeconds
    }

    public init(entry: BestiaryEntry) {
        self.init(speciesId: entry.speciesId,
                  strokesTotal: entry.strokesTotal,
                  writingSeconds: entry.writingSeconds)
    }

    /// Strokes the Watch may draw — the same arithmetic the phone's gallery
    /// uses, so both screens show the same animal at the same stage.
    public var strokesDrawn: Int {
        Bestiary.strokesDrawn(writingSeconds: writingSeconds,
                              targetSeconds: Bestiary.secondsPerCreature,
                              strokesTotal: strokesTotal)
    }

    public var fraction: Double {
        min(1, max(0, writingSeconds / Bestiary.secondsPerCreature))
    }

    /// The wire fields, merged into a command or poll payload.
    public var payloadFields: [String: Any] {
        [WatchPayloadKey.creatureSpecies: speciesId,
         WatchPayloadKey.creatureStrokesTotal: strokesTotal,
         WatchPayloadKey.creatureWritingSeconds: writingSeconds]
    }

    /// Reads a snapshot back out of a payload. All three fields must be
    /// present and sane; a partial payload is not a creature.
    public static func from(payload: [String: Any]) -> WatchCreatureSnapshot? {
        guard let species = WatchPayloadValue.int(payload[WatchPayloadKey.creatureSpecies]),
              let total = WatchPayloadValue.int(payload[WatchPayloadKey.creatureStrokesTotal]),
              let seconds = WatchPayloadValue.double(payload[WatchPayloadKey.creatureWritingSeconds]),
              species >= 0, total > 0, seconds >= 0 else { return nil }
        return WatchCreatureSnapshot(speciesId: species, strokesTotal: total,
                                     writingSeconds: seconds)
    }

    public static let defaultsKey = "scrybe.watchCreature"

    public static func load(from defaults: UserDefaults) -> WatchCreatureSnapshot? {
        guard let data = defaults.data(forKey: defaultsKey) else { return nil }
        return try? JSONDecoder().decode(WatchCreatureSnapshot.self, from: data)
    }

    public func store(in defaults: UserDefaults) {
        guard let data = try? JSONEncoder().encode(self) else { return }
        defaults.set(data, forKey: Self.defaultsKey)
    }
}
