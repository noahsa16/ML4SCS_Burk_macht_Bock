import Testing
import Foundation
@testable import WatchStreamer

@Suite("WatchCreatureSnapshot")
struct WatchCreatureSnapshotTests {

    @Test("round-trips through the payload the phone sends the Watch")
    func payloadRoundTrip() {
        let snapshot = WatchCreatureSnapshot(speciesId: 3, strokesTotal: 40, writingSeconds: 900)
        var payload: [String: Any] = [WatchPayloadKey.command: "stop"]
        payload.merge(snapshot.payloadFields) { _, new in new }
        #expect(WatchCreatureSnapshot.from(payload: payload) == snapshot)
    }

    // An older phone build sends no creature keys at all; a payload with only
    // some of them is malformed. Neither may be mistaken for a creature.
    @Test("a payload without all three fields is not a creature")
    func partialPayloadIsNil() {
        #expect(WatchCreatureSnapshot.from(payload: [WatchPayloadKey.command: "stop"]) == nil)
        #expect(WatchCreatureSnapshot.from(payload: [
            WatchPayloadKey.creatureSpecies: 1,
            WatchPayloadKey.creatureStrokesTotal: 20
        ]) == nil)
        #expect(WatchCreatureSnapshot.from(payload: [
            WatchPayloadKey.creatureSpecies: 1,
            WatchPayloadKey.creatureStrokesTotal: 0,
            WatchPayloadKey.creatureWritingSeconds: 10
        ]) == nil)
    }

    @Test("strokes drawn match the phone's own arithmetic")
    func strokesMatchBestiary() {
        let entry = BestiaryEntry(ordinal: 7, speciesId: 2, startedMs: 0,
                                  strokesTotal: 60, writingSeconds: 600)
        let snapshot = WatchCreatureSnapshot(entry: entry)
        #expect(snapshot.strokesDrawn == entry.strokesDrawn)
        #expect(snapshot.strokesDrawn == 20)
    }

    @Test("persists through UserDefaults")
    func defaultsRoundTrip() {
        let suite = "creature-test-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        #expect(WatchCreatureSnapshot.load(from: defaults) == nil)
        let snapshot = WatchCreatureSnapshot(speciesId: 5, strokesTotal: 12, writingSeconds: 450)
        snapshot.store(in: defaults)
        #expect(WatchCreatureSnapshot.load(from: defaults) == snapshot)
    }
}
