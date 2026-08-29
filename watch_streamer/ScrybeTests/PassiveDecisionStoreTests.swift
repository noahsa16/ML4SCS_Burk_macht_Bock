import Testing
import Foundation
@testable import WatchStreamer

@Suite("PassiveDecisionStore")
struct PassiveDecisionStoreTests {

    private func makeStore() -> (PassiveDecisionStore, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("passive-\(UUID().uuidString).jsonl")
        return (PassiveDecisionStore(fileURL: url), url)
    }

    private func decision(at date: Date, writing: Bool,
                          credit: Double = 2.5) -> PassiveDecision {
        let ms = Int64(date.timeIntervalSince1970 * 1000)
        return PassiveDecision(startMs: ms, endMs: ms + 5000,
                               logit: writing ? 1.5 : -1.5,
                               writing: writing, creditSeconds: credit)
    }

    @Test("records round-trip through the file")
    func roundTrip() {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        #expect(store.record([decision(at: now, writing: true),
                              decision(at: now, writing: false)]))
        #expect(store.allDecisions().count == 2)
    }

    @Test("appending twice keeps both batches")
    func appends() {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        _ = store.record([decision(at: now, writing: true)])
        _ = store.record([decision(at: now, writing: true)])
        #expect(store.allDecisions().count == 2)
    }

    // The overlap trap: two windows covering 5 s each but striding 2.5 s
    // represent 5 s of wall clock, not 10.
    @Test("writing seconds sum credit, not window span")
    func creditNotSpan() {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        _ = store.record([decision(at: now, writing: true),
                          decision(at: now.addingTimeInterval(2.5), writing: true)])
        #expect(store.writingSeconds(onDayContaining: now) == 5.0)
    }

    @Test("idle decisions contribute no writing time")
    func idleNotCounted() {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        _ = store.record([decision(at: now, writing: false),
                          decision(at: now, writing: true)])
        #expect(store.writingSeconds(onDayContaining: now) == 2.5)
    }

    @Test("day scoping uses local-time boundaries")
    func dayScoping() {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let yesterday = now.addingTimeInterval(-60 * 60 * 24)
        _ = store.record([decision(at: now, writing: true),
                          decision(at: yesterday, writing: true)])
        #expect(store.writingSeconds(onDayContaining: now) == 2.5)
        #expect(store.writingSeconds(onDayContaining: yesterday) == 2.5)
    }

    @Test("a corrupt line is skipped, not fatal")
    func corruptLineSkipped() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        _ = store.record([decision(at: Date(), writing: true)])
        let handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        try handle.write(contentsOf: Data("{not json}\n".utf8))
        try handle.close()
        #expect(store.allDecisions().count == 1)
    }

    @Test("pruning removes only days past the cutoff")
    func pruning() {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let old = now.addingTimeInterval(-60 * 60 * 24 * 40)
        _ = store.record([decision(at: now, writing: true),
                          decision(at: old, writing: true)])
        #expect(store.pruneOlderThan(days: 30, now: now))
        let left = store.allDecisions()
        #expect(left.count == 1)
        #expect(left[0].startMs > Int64(old.timeIntervalSince1970 * 1000))
    }

    @Test("an absent file reads as empty rather than throwing")
    func missingFile() {
        let (store, _) = makeStore()
        #expect(store.allDecisions().isEmpty)
        #expect(store.writingSeconds(onDayContaining: Date()) == 0)
    }
}
