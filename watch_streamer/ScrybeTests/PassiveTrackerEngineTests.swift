import Testing
import Foundation
@testable import WatchStreamer

// MARK: - Fakes

private final class FakeSource: PassiveSampleSource, @unchecked Sendable {
    var samples: [PassiveSample] = []
    private(set) var requestedSpans: [(from: Date, to: Date)] = []

    func fetch(from: Date, to: Date) -> [PassiveSample] {
        requestedSpans.append((from, to))
        return samples
    }
}

private struct FixedClassifier: PassiveClassifier {
    let value: Float
    func logit(window: [Float]) throws -> Float { value }
}

private struct ThrowingClassifier: PassiveClassifier {
    struct Boom: Error {}
    func logit(window: [Float]) throws -> Float { throw Boom() }
}

@Suite("PassiveTrackerEngine")
struct PassiveTrackerEngineTests {

    private func makeDefaults() -> UserDefaults {
        let suite = "passive-test-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: suite)!
        d.removePersistentDomain(forName: suite)
        return d
    }

    private func makeStore() -> (PassiveDecisionStore, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("engine-\(UUID().uuidString).jsonl")
        return (PassiveDecisionStore(fileURL: url), url)
    }

    /// `seqLen` samples at 50 Hz ending just before `endingAt`.
    private func samples(count: Int, endingAt end: Date) -> [PassiveSample] {
        let base = end.timeIntervalSinceReferenceDate - Double(count) / 50.0
        return (0..<count).map { i in
            PassiveSample(timestamp: base + Double(i) / 50.0,
                          x: 0.1, y: 0.2, z: 0.98)
        }
    }

    @Test("a disabled engine does nothing")
    func disabledIsNoOp() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let source = FakeSource()
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: makeDefaults())
        let r = engine.runRetrievalCycle()
        #expect(r.decisionsRecorded == 0)
        #expect(source.requestedSpans.isEmpty)
        #expect(!engine.isEnabled)
    }

    @Test("enabling persists and survives a new engine on the same defaults")
    func enabledPersists() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let defaults = makeDefaults()
        let first = PassiveTrackerEngine(source: FakeSource(), store: store,
                                         makeClassifier: { FixedClassifier(value: 1) },
                                         defaults: defaults)
        first.enable()
        let second = PassiveTrackerEngine(source: FakeSource(), store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: defaults)
        #expect(second.isEnabled)
    }

    @Test("known samples produce the expected decision count")
    func producesDecisions() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        // 375 samples at stride 125 completes two windows.
        source.samples = samples(count: 375, endingAt: now.addingTimeInterval(-400))
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 2.0) },
                                          defaults: makeDefaults())
        engine.enable()
        let r = engine.runRetrievalCycle(now: now)
        #expect(r.decisionsRecorded == 2)
        #expect(store.allDecisions().count == 2)
        let allWriting = store.allDecisions().allSatisfy { $0.writing }
        #expect(allWriting)
    }

    @Test("a negative logit is recorded as not writing")
    func negativeLogitIsIdle() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        source.samples = samples(count: 250, endingAt: now.addingTimeInterval(-400))
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: -2.0) },
                                          defaults: makeDefaults())
        engine.enable()
        _ = engine.runRetrievalCycle(now: now)
        let noneWriting = store.allDecisions().allSatisfy { !$0.writing }
        #expect(noneWriting)
        #expect(store.writingSeconds(onDayContaining: now) == 0)
    }

    // The cursor is the guarantee against re-reading — and against re-counting
    // the same writing time twice.
    @Test("the cursor advances and the next fetch starts where the last ended")
    func cursorAdvances() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        source.samples = samples(count: 250, endingAt: now.addingTimeInterval(-400))
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: makeDefaults())
        engine.enable()
        _ = engine.runRetrievalCycle(now: now)
        let firstEnd = try #require(source.requestedSpans.last).to

        source.samples = []
        _ = engine.runRetrievalCycle(now: now.addingTimeInterval(600))
        let secondStart = try #require(source.requestedSpans.last).from
        #expect(abs(secondStart.timeIntervalSince(firstEnd)) < 1e-6)
    }

    @Test("a fetch never spans more than the recorder's 12-hour limit")
    func fetchSpanIsCapped() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let source = FakeSource()
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: makeDefaults())
        engine.enable()
        // Pretend the watch was unread for three days.
        engine.cursor = Date().addingTimeInterval(-3 * 24 * 3600)
        _ = engine.runRetrievalCycle()
        let span = try #require(source.requestedSpans.last)
        #expect(span.to.timeIntervalSince(span.from) <= PassiveTrackerEngine.defaultMaxFetchSpanSeconds + 1)
    }

    @Test("the read never reaches into the recorder's headroom window")
    func respectsHeadroom() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: makeDefaults())
        engine.enable()
        _ = engine.runRetrievalCycle(now: now)
        let span = try #require(source.requestedSpans.last)
        #expect(span.to <= now.addingTimeInterval(-PassiveTrackerEngine.defaultHeadroomSeconds) + 1)
    }

    // A model that cannot load must not silently swallow the samples: they are
    // still on the recorder and a later cycle should get them.
    @Test("a model failure leaves the cursor untouched")
    func modelFailureKeepsCursor() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        source.samples = samples(count: 250, endingAt: now.addingTimeInterval(-400))
        struct LoadError: Error {}
        let engine = PassiveTrackerEngine(
            source: source, store: store,
            makeClassifier: { throw LoadError() },
            defaults: makeDefaults())
        engine.enable()
        let before = engine.cursor
        let r = engine.runRetrievalCycle(now: now)
        #expect(r.cursorAdvancedTo == nil)
        #expect(engine.cursor == before)
        if case .failed = engine.state {} else {
            Issue.record("expected a failed state, got \(engine.state)")
        }
    }

    @Test("inference failure on every window is reported, not silently empty")
    func inferenceFailureReported() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        source.samples = samples(count: 250, endingAt: now.addingTimeInterval(-400))
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { ThrowingClassifier() },
                                          defaults: makeDefaults())
        engine.enable()
        _ = engine.runRetrievalCycle(now: now)
        if case .failed = engine.state {} else {
            Issue.record("expected a failed state, got \(engine.state)")
        }
    }

    @Test("an empty span advances the cursor so a gap cannot stall it forever")
    func emptySpanAdvances() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let source = FakeSource()
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: makeDefaults())
        engine.enable()
        let r = engine.runRetrievalCycle()
        #expect(r.decisionsRecorded == 0)
        #expect(r.cursorAdvancedTo != nil)
        #expect(engine.cursor != nil)
    }

    @Test("pendingDecisions returns only newer entries, oldest first")
    func pendingIsOrderedAndFiltered() throws {
        let (store, url) = makeStore()
        defer { try? FileManager.default.removeItem(at: url) }
        let now = Date()
        let source = FakeSource()
        source.samples = samples(count: 375, endingAt: now.addingTimeInterval(-400))
        let engine = PassiveTrackerEngine(source: source, store: store,
                                          makeClassifier: { FixedClassifier(value: 1) },
                                          defaults: makeDefaults())
        engine.enable()
        _ = engine.runRetrievalCycle(now: now)
        let all = engine.pendingDecisions(since: 0)
        #expect(all.count == 2)
        #expect(all[0].startMs <= all[1].startMs)
        #expect(engine.pendingDecisions(since: all[0].startMs).count == 1)
    }

    @Test("reference-date timestamps convert to Unix milliseconds")
    func epochConversion() throws {
        // 2001-01-01T00:00:00Z is reference date 0 and Unix 978 307 200 s.
        #expect(PassiveTrackerEngine.epochMs(fromReferenceDate: 0) == 978_307_200_000)
    }
}
