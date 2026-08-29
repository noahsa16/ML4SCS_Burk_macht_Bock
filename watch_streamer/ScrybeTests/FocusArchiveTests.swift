import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus day archive")
struct FocusArchiveTests {

    private let stride: Int64 = 2_500

    private func tempURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("archive-\(UUID().uuidString).json")
    }

    /// `count` back-to-back writing windows starting at 10:00 on the given day.
    private func day(_ offsetDays: Int, count: Int,
                     hour: Int = 10, calendar: Calendar = .current) -> [PassiveDecision] {
        let start = calendar.date(byAdding: .day, value: offsetDays,
                                  to: calendar.startOfDay(for: Date()))!
        let base = Int64(start.timeIntervalSince1970 * 1000) + Int64(hour) * 3_600_000
        return (0..<count).map { i in
            let s = base + Int64(i) * stride
            return PassiveDecision(startMs: s, endMs: s + 5_000, logit: 2,
                                   writing: true, creditSeconds: 2.5)
        }
    }

    @Test("a day inside the raw retention is not sealed")
    func recentDayIsNotSealed() {
        let archive = FocusArchive(fileURL: tempURL())
        let sealed = archive.rollUp(day(0, count: 4) + day(-1, count: 4))
        #expect(sealed.isEmpty)
        #expect(archive.all().isEmpty)
    }

    @Test("a day past the raw retention is sealed with its totals")
    func oldDayIsSealed() throws {
        let archive = FocusArchive(fileURL: tempURL())
        let sealed = archive.rollUp(day(-10, count: 4))
        #expect(sealed.count == 1)
        let summary = try #require(archive.all().first)
        #expect(summary.writingSeconds == 10.0)
        #expect(summary.stretches.count == 1)
        #expect(summary.windowCount == 4)
        #expect(summary.hourly.count == 24)
        #expect(summary.hourly[10] == 10.0)
    }

    // Why: the same windows can be handed over twice — transferUserInfo is
    // durable and re-delivery is expected. A summary that accumulated would
    // silently double a day.
    @Test("rolling up the same windows twice does not double the total")
    func rollUpIsIdempotent() throws {
        let archive = FocusArchive(fileURL: tempURL())
        let windows = day(-10, count: 4)
        archive.rollUp(windows)
        archive.rollUp(windows)
        let summary = try #require(archive.all().first)
        #expect(summary.writingSeconds == 10.0)
        #expect(archive.all().count == 1)
    }

    @Test("only the old part of a mixed batch is sealed")
    func mixedBatchSealsOnlyOldDays() {
        let archive = FocusArchive(fileURL: tempURL())
        let sealed = archive.rollUp(day(0, count: 4) + day(-10, count: 4) + day(-11, count: 4))
        #expect(sealed.count == 2)
    }

    @Test("a sealed day is readable by its date")
    func lookupByDate() throws {
        let archive = FocusArchive(fileURL: tempURL())
        let sealed = archive.rollUp(day(-10, count: 8))
        let date = try #require(sealed.first)
        let summary = try #require(archive.summary(for: date))
        #expect(summary.date == date)
        #expect(summary.writingSeconds == 20.0)
    }

    @Test("the archive survives a fresh instance")
    func persistsAcrossInstances() throws {
        let url = tempURL()
        FocusArchive(fileURL: url).rollUp(day(-10, count: 4))
        let reopened = FocusArchive(fileURL: url)
        let summary = try #require(reopened.all().first)
        #expect(summary.writingSeconds == 10.0)
    }

    @Test("pruning drops summaries past the retention and keeps the rest")
    func pruneDropsOldSummaries() {
        let archive = FocusArchive(fileURL: tempURL())
        archive.rollUp(day(-10, count: 4) + day(-100, count: 4))
        #expect(archive.all().count == 2)
        archive.prune(olderThan: 90)
        #expect(archive.all().count == 1)
    }

    @Test("an empty roll-up seals nothing and writes nothing")
    func emptyRollUp() {
        let archive = FocusArchive(fileURL: tempURL())
        #expect(archive.rollUp([]).isEmpty)
        #expect(archive.all().isEmpty)
    }

    @Test("idle windows are archived as zero writing time")
    func idleOnlyDay() throws {
        let archive = FocusArchive(fileURL: tempURL())
        let idle = day(-10, count: 4).map {
            PassiveDecision(startMs: $0.startMs, endMs: $0.endMs, logit: -2,
                            writing: false, creditSeconds: 2.5)
        }
        archive.rollUp(idle)
        let summary = try #require(archive.all().first)
        #expect(summary.writingSeconds == 0)
        #expect(summary.stretches.isEmpty)
    }
}
