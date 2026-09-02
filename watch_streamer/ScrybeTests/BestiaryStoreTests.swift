import Testing
import Foundation
@testable import WatchStreamer

@Suite("Bestiary store")
@MainActor
struct BestiaryStoreTests {

    // Fixed instants rather than `Date()` so `startedMs`/`completedMs` can be
    // asserted exactly, and so the species each moment hashes to is
    // reproducible run to run.
    private let t0: Int64 = 1_788_000_000_000
    private let t1: Int64 = 1_788_000_600_000   // t0 + 10 min
    private let t2: Int64 = 1_788_003_600_000   // t0 + 1 h

    private func date(_ ms: Int64) -> Date { Date(timeIntervalSince1970: Double(ms) / 1000) }

    private func tempStore() -> (BestiaryStore, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        return (BestiaryStore(fileURL: url), url)
    }

    private func totalAccumulated(_ store: BestiaryStore) -> Double {
        store.completed.reduce(0) { $0 + $1.writingSeconds } + (store.current?.writingSeconds ?? 0)
    }

    // MARK: - Accumulation

    // Two separate calls (two sittings) below the completion target. If the
    // store instead started a fresh creature per call — the bug this model
    // replaces — `current` would read 400, not the summed 900, and this would
    // fail; it cannot pass by only checking `isComplete` or a count.
    @Test("writing seconds accumulate across separate sessions")
    func writingSecondsAccumulateAcrossSessions() throws {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(500, now: date(t0))
        store.addWritingSeconds(400, now: date(t1))
        let current = try #require(store.current)
        #expect(current.writingSeconds == 900)
        #expect(store.completed.isEmpty)
        #expect(!current.isComplete)
    }

    // MARK: - Completion boundary

    @Test("a creature completes at exactly thirty minutes")
    func completesAtExactlyThirtyMinutes() throws {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(Bestiary.secondsPerCreature, now: date(t0))
        #expect(store.current == nil)
        let finished = try #require(store.completed.first)
        #expect(finished.isComplete)
        #expect(finished.writingSeconds == Bestiary.secondsPerCreature)
        #expect(finished.completedMs == t0)
    }

    // The off-by-one edge the truncating stroke math makes easy to miss: one
    // second short of the target must still read unfinished, not complete.
    @Test("one second short of the target is still unfinished")
    func justUnderTargetStaysUnfinished() throws {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(Bestiary.secondsPerCreature - 1, now: date(t0))
        #expect(store.completed.isEmpty)
        let current = try #require(store.current)
        #expect(!current.isComplete)
    }

    // MARK: - Surplus carryover

    // A single sitting long enough to both finish the current creature and
    // start the next. Checks the archived creature is capped at the target
    // (never overdrawn) and the new one opens with exactly the remainder —
    // not the full session length, which would silently invent writing time.
    //
    // Both entries share the same `now` (the instant one finished is the
    // instant the other began), so the interesting assertions are the
    // identity ones: a store that seeded id/species from `startedMs` instead
    // of `ordinal` would archive one creature and reopen an entry that is,
    // by id and by species, the *same* creature — the bug this test exists
    // to catch. `startedMs` itself legitimately matches `t0` on both sides
    // (that's the correct caption, not the bug), so it alone can't tell
    // these apart.
    @Test("surplus from one long session carries into a genuinely new creature")
    func surplusCarriesWithinOneCall() throws {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(Bestiary.secondsPerCreature + 200, now: date(t0))
        let finished = try #require(store.completed.first)
        #expect(finished.writingSeconds == Bestiary.secondsPerCreature)
        let next = try #require(store.current)
        #expect(next.writingSeconds == 200)
        #expect(next.startedMs == t0)
        // `id` is defined as `ordinal` (see `BestiaryEntry`), so this is the
        // same fact `ForEach(store.all)` in `BestiaryView` actually depends
        // on — checked via `ordinal` since that's the field the store owns.
        #expect(next.ordinal != finished.ordinal)
        #expect(next.speciesId == Bestiary.species(seed: next.ordinal))
    }

    // Same overshoot, but split across two sittings the way it actually
    // happens: most of a creature finished earlier, a short session later
    // tips it over. Exercises the boundary through `current` state carried
    // between two separate calls, not just arithmetic inside one.
    @Test("surplus carries into the next creature across two sessions")
    func surplusCarriesAcrossTwoCalls() throws {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(Bestiary.secondsPerCreature - 100, now: date(t0))
        store.addWritingSeconds(300, now: date(t1))
        let finished = try #require(store.completed.first)
        #expect(finished.writingSeconds == Bestiary.secondsPerCreature)
        #expect(finished.completedMs == t1)
        let next = try #require(store.current)
        #expect(next.writingSeconds == 200)
        #expect(next.startedMs == t1)
        #expect(next.ordinal != finished.ordinal)
        #expect(next.speciesId == Bestiary.species(seed: next.ordinal))
    }

    // The exact shape the review reported: a credit spanning more than one
    // boundary re-enters the rollover loop several times with `current ==
    // nil` and the same `now` every time. Direct regression test for the
    // critical finding — asserts the thing that actually broke (identity
    // uniqueness across all three entries), not just the visible totals.
    @Test("a credit spanning multiple creature boundaries never reuses an identity")
    func multipleBoundariesInOneCallNeverCollide() throws {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(Bestiary.secondsPerCreature * 2 + 300, now: date(t0))

        #expect(store.completed.count == 2)
        let all = store.completed + (store.current.map { [$0] } ?? [])
        #expect(all.count == 3)
        // `id` is defined as `ordinal`, so a duplicate here is exactly the
        // `ForEach(store.all)` collision the review reported.
        #expect(Set(all.map(\.id)).count == 3)
        for entry in all {
            #expect(entry.speciesId == Bestiary.species(seed: entry.ordinal))
        }
        #expect(store.current?.writingSeconds == 300)
    }

    // MARK: - Species stability

    // `t2` is picked so its hash genuinely differs from `t0`'s — computed live
    // against the real `Bestiary.species` function, not assumed — so a store
    // that (incorrectly) re-derives species from the latest session start
    // would be caught here rather than passing by a 1-in-8 coincidence.
    @Test("the species and start of a resumed creature never reroll")
    func speciesAndStartAreStableAcrossAResume() throws {
        let firstSpecies = Bestiary.species(seed: 0)
        var laterMs = t2
        while Bestiary.species(seed: laterMs) == firstSpecies { laterMs += 1_000 }
        let laterDate = date(laterMs)

        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.addWritingSeconds(100, now: date(t0))
        let first = try #require(store.current)
        // `ordinal` is 0 for the first creature any fresh store ever begins,
        // so this is what the store itself will have used to seed it —
        // checked directly rather than assumed.
        #expect(first.ordinal == 0)
        #expect(first.speciesId == firstSpecies)

        store.addWritingSeconds(100, now: laterDate)
        let resumed = try #require(store.current)
        #expect(resumed.ordinal == first.ordinal)
        #expect(resumed.startedMs == first.startedMs)
        #expect(resumed.speciesId == firstSpecies)
        // Also pins `strokesTotal`, which only exists because species can't be
        // re-looked-up from Shared code — a resume that re-derived it (from
        // whatever species the buggy path landed on) would drift here even if
        // `speciesId` above were somehow still asserted against a stale copy.
        #expect(resumed.strokesTotal == first.strokesTotal)
        #expect(resumed.writingSeconds == 200)
    }

    // MARK: - Conservation

    // Mirrors `Bestiary.strokesDrawn`'s own fragmentation invariant, but at
    // the store — through real file-backed instances, not the pure function —
    // and with a sum large enough to cross more than one creature boundary.
    // Bursts are summed at runtime (not folded into a literal) across two
    // independently constructed stores, so this compares two different code
    // paths reaching the same total rather than one call checked against
    // itself.
    @Test("splitting the same total across many sessions changes when a creature completes, never how much is kept")
    func fragmentationConservesTheTotal() {
        let bursts: [Double] = [212, 763, 500, 1_300, 900, 825]  // sums to 4_500
        let (fragmented, urlA) = tempStore()
        defer { try? FileManager.default.removeItem(at: urlA) }
        var t = t0
        for burst in bursts {
            fragmented.addWritingSeconds(burst, now: date(t))
            t += 3_600_000
        }

        let (whole, urlB) = tempStore()
        defer { try? FileManager.default.removeItem(at: urlB) }
        whole.addWritingSeconds(bursts.reduce(0, +), now: date(t0))

        #expect(totalAccumulated(fragmented) == totalAccumulated(whole))
        #expect(totalAccumulated(fragmented) == bursts.reduce(0, +))
        #expect(fragmented.completed.count == whole.completed.count)
        #expect(fragmented.completed.allSatisfy { $0.writingSeconds == Bestiary.secondsPerCreature })
    }

    // MARK: - Persistence

    // Reopens the SAME file with a second, independent store instance — a
    // store that only cached in memory (or read from the wrong file) would
    // still show data from the first instance's own properties, so this must
    // read a fresh instance's state, not the one that wrote it.
    @Test("entries survive a fresh store instance reading the same file")
    func entriesPersistAcrossInstances() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        BestiaryStore(fileURL: url).addWritingSeconds(
            Bestiary.secondsPerCreature + 300, now: date(t0))

        let reopened = BestiaryStore(fileURL: url)
        #expect(reopened.completed.count == 1)
        #expect(reopened.completed.first?.writingSeconds == Bestiary.secondsPerCreature)
        let current = try #require(reopened.current)
        #expect(current.writingSeconds == 300)
    }

    // A file that exists but can't be decoded (corrupt, or — on device —
    // still behind `completeUntilFirstUserAuthentication` before first
    // unlock) must never be treated as "nothing here yet, safe to start
    // writing over". A collection can't be rebuilt from anything else, so a
    // write that would normally persist has to leave the original bytes
    // alone rather than replace them with the empty state this instance
    // started from.
    @Test("a present but undecodable file is never written over")
    func undecodableFileIsNeverOverwritten() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let corrupt = Data("not json".utf8)
        try corrupt.write(to: url)

        let store = BestiaryStore(fileURL: url)
        #expect(store.completed.isEmpty)
        #expect(store.current == nil)

        store.addWritingSeconds(500, now: date(t0))
        let onDisk = try Data(contentsOf: url)
        #expect(onDisk == corrupt)
    }

    // The suspension above must not be permanent once the user has
    // deliberately wiped the collection — at that point there is no
    // surviving data left for a write to clobber, so persistence has to
    // resume. Verified by reopening a third instance rather than trusting
    // the live one's in-memory state, which would hold even if the write
    // never reached disk.
    @Test("deleting all data re-enables persistence after an unreadable load")
    func deleteAllReenablesPersistenceAfterUnreadableLoad() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        try Data("not json".utf8).write(to: url)

        let store = BestiaryStore(fileURL: url)
        store.deleteAll()
        store.addWritingSeconds(500, now: date(t0))

        let reopened = BestiaryStore(fileURL: url)
        let current = try #require(reopened.current)
        #expect(current.writingSeconds == 500)
    }

    // The suspension exists for a file that cannot be read; it must not be
    // reachable by adding a field to `BestiaryEntry`. A non-optional field
    // would make every file written before it undecodable, and the only exit
    // from the suspension is `deleteAll()` — which destroys the collection
    // the suspension was protecting. So a payload missing a field has to
    // decode into entries that are still drawable and still counted.
    @Test("a payload missing a field still yields usable entries")
    func missingFieldStillDecodes() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        // `ordinal` and `strokesTotal` absent — the identity field the review
        // flagged, plus the one whose default alone would leave an entry that
        // draws nothing.
        try Data("""
        {"completed":[{"speciesId":3,"startedMs":\(t0),"writingSeconds":1800,\
        "completedMs":\(t1)}],\
        "current":{"speciesId":5,"startedMs":\(t2),"writingSeconds":600}}
        """.utf8).write(to: url)

        let store = BestiaryStore(fileURL: url)
        let finished = try #require(store.completed.first)
        let inProgress = try #require(store.current)
        #expect(finished.isComplete)
        #expect(inProgress.writingSeconds == 600)
        // Distinct identities, so neither reads as the other repeated.
        #expect(finished.ordinal != inProgress.ordinal)
        // Drawable: `visible` drops an entry with no strokes, which is how a
        // "decoded fine" claim would still lose the collection on screen.
        #expect(inProgress.strokesTotal == Marginalia.strokeCount(forSpecies: 5))
        #expect(store.visible.count == 2)

        // And the store did not suspend itself: a later credit reaches disk.
        store.addWritingSeconds(300, now: date(t2))
        let reopened = BestiaryStore(fileURL: url)
        #expect(reopened.current?.writingSeconds == 900)
    }

    // MARK: - Erasure

    @Test("deleting all data clears both the in-progress and finished creatures, on disk too")
    func deleteAllErasesEverything() {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let store = BestiaryStore(fileURL: url)
        store.addWritingSeconds(Bestiary.secondsPerCreature + 300, now: date(t0))
        store.deleteAll()

        #expect(store.completed.isEmpty)
        #expect(store.current == nil)
        // Re-reads the file rather than trusting the live instance's own
        // properties, which would hold even if `deleteAll` never touched disk.
        let reopened = BestiaryStore(fileURL: url)
        #expect(reopened.completed.isEmpty)
        #expect(reopened.current == nil)
    }
}
