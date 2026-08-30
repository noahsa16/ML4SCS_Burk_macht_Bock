import Testing
import Foundation
@testable import WatchStreamer

@Suite("Local focus store")
@MainActor
struct FocusStoreLocalTests {

    private func tempStore() -> (FocusStore, PassiveDecisionStore, FocusArchive) {
        let dir = FileManager.default.temporaryDirectory
        let id = UUID().uuidString
        let raw = PassiveDecisionStore(
            fileURL: dir.appendingPathComponent("decisions-\(id).jsonl"))
        let archive = FocusArchive(fileURL: dir.appendingPathComponent("archive-\(id).json"))
        // Why an isolated suite: `.standard` is process-wide, and the harvest
        // baseline is a plain UserDefaults key — sharing it across test
        // structs would leak one test's claimed minutes into the next.
        let suite = "focus-store-test-\(id)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return (FocusStore(decisions: raw, archive: archive, defaults: defaults),
                raw, archive)
    }

    private func windows(_ offsetDays: Int, count: Int, writing: Bool = true,
                         hour: Int = 10) -> [PassiveDecision] {
        let cal = Calendar.current
        let start = cal.date(byAdding: .day, value: offsetDays,
                             to: cal.startOfDay(for: Date()))!
        let base = Int64(start.timeIntervalSince1970 * 1000) + Int64(hour) * 3_600_000
        return (0..<count).map { i in
            let s = base + Int64(i) * 2_500
            return PassiveDecision(startMs: s, endMs: s + 5_000,
                                   logit: writing ? 2 : -2, writing: writing,
                                   creditSeconds: 2.5)
        }
    }

    @Test("today's total comes from ingested windows")
    func ingestFeedsToday() async {
        let (store, _, _) = tempStore()
        await store.ingest(windows(0, count: 8))
        await store.refresh()
        #expect(store.todayWritingSeconds == 20.0)
        #expect(store.today?.stretches.count == 1)
    }

    // Why: idle windows are ~95 % of a tracked day and no screen reads them —
    // a gap between writing windows already ends a stretch. Keeping them would
    // cost roughly twenty times the storage for nothing.
    @Test("idle windows are not stored")
    func idleIsDropped() async {
        let (store, raw, _) = tempStore()
        await store.ingest(windows(0, count: 8, writing: false))
        await store.refresh()
        #expect(raw.allDecisions().isEmpty)
        #expect(store.todayWritingSeconds == 0)
    }

    @Test("a mixed batch keeps only the writing windows")
    func mixedBatch() async {
        let (store, raw, _) = tempStore()
        await store.ingest(windows(0, count: 4) + windows(0, count: 4, writing: false, hour: 14))
        await store.refresh()
        #expect(raw.allDecisions().count == 4)
        #expect(store.todayWritingSeconds == 10.0)
    }

    // The point of the whole design: an old day keeps its number after its raw
    // windows are gone.
    @Test("an old day survives as a summary once its windows are pruned")
    func oldDayIsSealedAndPruned() async throws {
        let (store, raw, archive) = tempStore()
        await store.ingest(windows(-10, count: 8))
        await store.refresh()

        #expect(raw.allDecisions().isEmpty, "raw windows should be gone")
        #expect(archive.all().count == 1, "the day should be archived")

        let days = try #require(store.history?.days)
        let sealed = try #require(days.first { $0.writingSeconds > 0 })
        #expect(sealed.writingSeconds == 20.0)
    }

    @Test("a sealed day still lists its stretches in the detail view")
    func sealedDayKeepsStretches() async throws {
        let (store, _, archive) = tempStore()
        await store.ingest(windows(-10, count: 8))
        await store.refresh()
        let date = try #require(archive.all().first?.date)
        await store.loadDay(date)
        let payload = try #require(store.dayCache[date])
        #expect(payload.stretches.count == 1)
        #expect(payload.totalWritingSeconds == 20.0)
    }

    @Test("recent days keep their raw windows so late deliveries still land")
    func recentDaysAreNotSealed() async {
        let (store, raw, archive) = tempStore()
        await store.ingest(windows(0, count: 4) + windows(-1, count: 4))
        await store.refresh()
        #expect(raw.allDecisions().count == 8)
        #expect(archive.all().isEmpty)
    }

    @Test("a late delivery for a kept day is added, not lost")
    func lateDeliveryForKeptDay() async {
        let (store, _, _) = tempStore()
        await store.ingest(windows(-1, count: 4))
        await store.refresh()
        await store.ingest(windows(-1, count: 4, hour: 15))
        await store.refresh()
        let yesterday = store.history?.days.dropLast().last
        #expect(yesterday?.writingSeconds == 20.0)
    }

    @Test("the time-of-day chart looks back only seven days")
    func timeOfDayWindowIsSevenDays() async throws {
        let (store, _, _) = tempStore()
        await store.ingest(windows(0, count: 4, hour: 9))
        await store.ingest(windows(-10, count: 4, hour: 9))
        await store.refresh()
        let buckets = try #require(store.timeOfDay?.buckets)
        let nine = try #require(buckets.first { $0.hour == 9 })
        #expect(nine.seconds == 10.0)
    }

    // A day five days back is past the raw retention but inside the chart's
    // window, so it can only be counted from the archive. This is the case
    // that proves sealed days still feed the chart.
    @Test("an archived day inside the window still feeds the time-of-day chart")
    func timeOfDayReadsTheArchive() async throws {
        let (store, raw, archive) = tempStore()
        await store.ingest(windows(-5, count: 4, hour: 9))
        await store.refresh()
        #expect(raw.allDecisions().isEmpty)
        #expect(archive.all().count == 1)
        let buckets = try #require(store.timeOfDay?.buckets)
        let nine = try #require(buckets.first { $0.hour == 9 })
        #expect(nine.seconds == 10.0)
    }

    @Test("the last writing time is the end of the newest writing window")
    func lastWritingAt() async throws {
        let (store, _, _) = tempStore()
        let w = windows(0, count: 4)
        await store.ingest(w)
        await store.refresh()
        let last = try #require(store.lastWritingAt)
        let expected = Double(w.map(\.endMs).max()!) / 1000
        #expect(abs(last.timeIntervalSince1970 - expected) < 0.001)
    }

    // The daily ring and the header Watch glyph both ask this one question.
    // They used to answer it from different sources — the ring from stored
    // decisions, the glyph from the server's live broadcast — so a phone with
    // no server showed a breathing ring beside a glyph claiming nothing.
    @Test("recent-writing is one answer for the ring and the header glyph")
    func recentWritingIsShared() async {
        let (store, _, _) = tempStore()
        let now = Date()
        let endMs = Int64(now.timeIntervalSince1970 * 1000) - 60_000
        await store.ingest([PassiveDecision(startMs: endMs - 5_000, endMs: endMs,
                                            logit: 2, writing: true,
                                            creditSeconds: 2.5)])
        await store.refresh()
        #expect(store.isRecentlyWriting(now: now))

        let stale = now.addingTimeInterval(FocusStore.recentWritingWindow + 60)
        #expect(!store.isRecentlyWriting(now: stale))
    }

    @Test("an empty store never claims recent writing")
    func recentWritingNeedsData() {
        let (store, _, _) = tempStore()
        #expect(!store.isRecentlyWriting())
    }

    @Test("deleting local data clears both stores, every screen, and the harvest baseline")
    func deleteClearsEverything() async {
        let (store, raw, archive) = tempStore()
        await store.ingest(windows(0, count: 4) + windows(-10, count: 4))
        await store.refresh()
        store.markHarvested()
        store.deleteAllLocalData()
        #expect(raw.allDecisions().isEmpty)
        #expect(archive.all().isEmpty)
        #expect(store.today == nil)
        #expect(store.history == nil)
        #expect(store.lastWritingAt == nil)

        // The old baseline must not survive "alle Einstellungen löschen":
        // fresh data afterwards should report its full total, not total minus
        // a claim from before the delete.
        await store.ingest(windows(0, count: 4))
        await store.refresh()
        #expect(store.harvestDelta() == 10.0)
    }

    @Test("product demo grows the UI without touching real decisions")
    func demoIsEphemeral() async {
        let (store, raw, _) = tempStore()
        let start = Date()
        store.startDemo(startingSeconds: 1_800, secondsPerTick: 10)

        #expect(store.demoModeEnabled)
        #expect(abs(store.todayWritingSeconds - 1_800) < 0.01)
        #expect(raw.allDecisions().isEmpty)

        store.advanceDemo(at: start.addingTimeInterval(1))
        #expect(abs(store.todayWritingSeconds - 1_810) < 0.01)
        #expect(store.demoIsWriting)
        #expect(raw.allDecisions().isEmpty)

        await store.stopDemo()
        #expect(store.demoModeEnabled == false)
        #expect(store.todayWritingSeconds == 0)
        #expect(raw.allDecisions().isEmpty)
    }

    @Test("product demo visibly alternates writing and pauses")
    func demoAlternatesState() async {
        let (store, _, _) = tempStore()
        let start = Date()
        store.startDemo(startingSeconds: 0, secondsPerTick: 1)
        for tick in 1...8 {
            store.advanceDemo(at: start.addingTimeInterval(Double(tick)))
        }
        #expect(store.demoIsWriting)
        store.advanceDemo(at: start.addingTimeInterval(9))
        #expect(store.demoIsWriting == false)
        await store.stopDemo()
    }

    // The number shown on a pull is what arrived since the user last looked,
    // so two pulls in a row must not claim the same minutes twice.
    @Test("a second pull claims no minutes")
    func harvestIsNotDoubleCounted() async {
        let (store, _, _) = tempStore()
        await store.ingest(windows(0, count: 8))
        await store.refresh()
        let first = store.harvestDelta()
        #expect(first == 20.0)
        store.markHarvested()
        #expect(store.harvestDelta() == 0)
    }

    @Test("the first ever pull does not claim the whole history")
    func firstRunClaimsNothing() async {
        let (store, _, _) = tempStore()
        await store.ingest(windows(-3, count: 8) + windows(0, count: 8))
        await store.refresh()
        store.primeHarvestBaseline()
        #expect(store.harvestDelta() == 0)
    }

    // Old behaviour: the baseline was a bare seconds value that outlived the
    // day it was claimed on, so a claim tagged to an earlier day still got
    // subtracted from today's total instead of being discarded. Seeded
    // entirely through the public API (`markHarvested(now:)`, itself taking
    // an explicit `now` for exactly this) rather than the store's private
    // UserDefaults keys, so the test survives a key rename instead of
    // silently exercising nothing once one changes.
    @Test("a stale claim from a previous day does not swallow today's harvest")
    func harvestResetsAcrossDays() async {
        let (store, _, _) = tempStore()
        let now = Date()
        let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: now)!

        await store.ingest(windows(0, count: 4))
        await store.refresh()
        store.markHarvested(now: yesterday)

        await store.ingest(windows(0, count: 4, hour: 14))
        await store.refresh()

        #expect(store.harvestDelta(now: now) == 20.0)
    }

    // The pull announces whole minutes, so it may only claim whole minutes.
    // Claiming the entire total instead would swallow the seconds still short
    // of the next minute, and someone writing in bursts under a minute would
    // be told "nothing new" on every pull, forever.
    @Test("a claim of whole minutes leaves the remainder for the next pull")
    func wholeMinuteClaimCarriesTheRemainder() async {
        let (store, _, _) = tempStore()
        let now = Date()
        await store.ingest(windows(0, count: 44))        // 110 s
        await store.refresh()
        #expect(store.harvestDelta(now: now) == 110.0)

        store.claimWholeMinutes(1, now: now)
        #expect(store.harvestDelta(now: now) == 50.0)

        // And a harvest that has not reached a full minute claims nothing at
        // all, rather than resetting the baseline to the current total.
        store.claimWholeMinutes(0, now: now)
        #expect(store.harvestDelta(now: now) == 50.0)
    }

    // The claim is tagged to the day it happened on, like `markHarvested`:
    // an untagged baseline would be subtracted from tomorrow's smaller total
    // and hide the whole of the next day's first harvest.
    @Test("a whole-minute claim does not outlive its day")
    func wholeMinuteClaimIsDayScoped() async {
        let (store, _, _) = tempStore()
        let now = Date()
        let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: now)!

        await store.ingest(windows(0, count: 44))        // 110 s
        await store.refresh()
        store.claimWholeMinutes(1, now: yesterday)

        #expect(store.harvestDelta(now: now) == 110.0)
    }
}
