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
        return (FocusStore(decisions: raw, archive: archive), raw, archive)
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

    @Test("deleting local data clears both stores and every screen")
    func deleteClearsEverything() async {
        let (store, raw, archive) = tempStore()
        await store.ingest(windows(0, count: 4) + windows(-10, count: 4))
        await store.refresh()
        store.deleteAllLocalData()
        #expect(raw.allDecisions().isEmpty)
        #expect(archive.all().isEmpty)
        #expect(store.today == nil)
        #expect(store.history == nil)
        #expect(store.lastWritingAt == nil)
    }
}
