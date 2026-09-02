import Testing
import Foundation
@testable import WatchStreamer

@Suite("Passive focus aggregation")
struct PassiveFocusAggregatorTests {

    private let stride: Int64 = 2_500
    private let span: Int64 = 5_000

    /// A window starting at `index` strides after `base`.
    private func decision(_ index: Int64, writing: Bool, base: Int64 = 0,
                          logit: Float = 2) -> PassiveDecision {
        let start = base + index * stride
        return PassiveDecision(startMs: start, endMs: start + span,
                               logit: writing ? logit : -logit,
                               writing: writing, creditSeconds: Double(stride) / 1000)
    }

    private func midnight(_ offsetDays: Int = 0, calendar: Calendar = .current) -> Int64 {
        let day = calendar.date(byAdding: .day, value: offsetDays,
                                to: calendar.startOfDay(for: Date()))!
        return Int64(day.timeIntervalSince1970 * 1000)
    }

    // MARK: - Stretches

    @Test("no decisions produce no stretches")
    func empty() {
        #expect(PassiveFocusAggregator.stretches(from: []).isEmpty)
    }

    @Test("back-to-back windows form one stretch credited by stride")
    func contiguousRun() {
        let d = (0..<4).map { decision(Int64($0), writing: true) }
        let s = PassiveFocusAggregator.stretches(from: d)
        #expect(s.count == 1)
        // Why stride and not end-start: the windows overlap, so wall-clock
        // extent (12.5 s) would credit 2.5 s of writing that never happened.
        #expect(s[0].durationS == 10.0)
        #expect(s[0].startMs == 0)
        #expect(s[0].endMs == 12_500)
    }

    @Test("a short hole does not split a stretch")
    func shortHoleForgiven() {
        let d = [decision(0, writing: true), decision(1, writing: true),
                 decision(4, writing: true), decision(5, writing: true)]
        #expect(PassiveFocusAggregator.stretches(from: d).count == 1)
    }

    @Test("a long hole splits the stretch")
    func longHoleSplits() {
        let d = [decision(0, writing: true), decision(1, writing: true),
                 decision(20, writing: true), decision(21, writing: true)]
        let s = PassiveFocusAggregator.stretches(from: d)
        #expect(s.count == 2)
        #expect(s[0].durationS == 5.0)
        #expect(s[1].durationS == 5.0)
    }

    @Test("a long idle run ends the stretch")
    func idleEndsStretch() {
        var d = (0..<2).map { decision(Int64($0), writing: true) }
        d += (2..<10).map { decision(Int64($0), writing: false) }
        d += (10..<12).map { decision(Int64($0), writing: true) }
        #expect(PassiveFocusAggregator.stretches(from: d).count == 2)
    }

    @Test("idle windows contribute no writing credit")
    func idleIsNotCredited() {
        let d = [decision(0, writing: true), decision(1, writing: false),
                 decision(2, writing: true)]
        let s = PassiveFocusAggregator.stretches(from: d)
        #expect(s.count == 1)
        #expect(s[0].durationS == 5.0)
    }

    @Test("out-of-order decisions are sorted before grouping")
    func unsortedInput() {
        let d = [decision(3, writing: true), decision(0, writing: true),
                 decision(2, writing: true), decision(1, writing: true)]
        let s = PassiveFocusAggregator.stretches(from: d)
        #expect(s.count == 1)
        #expect(s[0].startMs == 0)
    }

    // MARK: - Intensity

    @Test("intensity stays a probability and follows the logit sign")
    func intensityIsProbability() throws {
        let d = (0..<8).map { decision(Int64($0), writing: true, logit: 3) }
        let s = try #require(PassiveFocusAggregator.stretches(from: d).first)
        let values = PassiveFocusAggregator.intensity(for: s, in: d)
        #expect(!values.isEmpty)
        let inRange = values.allSatisfy { $0 >= 0 && $0 <= 1 }
        #expect(inRange)
        let confident = values.allSatisfy { $0 > 0.9 }
        #expect(confident)
    }

    @Test("a zero logit is an even probability")
    func zeroLogit() {
        #expect(abs(PassiveFocusAggregator.probability(ofLogit: 0) - 0.5) < 1e-9)
    }

    // MARK: - Day and range

    @Test("a day payload counts only that day")
    func dayFilters() {
        let today = (0..<4).map { decision(Int64($0), writing: true, base: midnight() + 36_000_000) }
        let yesterday = (0..<8).map {
            decision(Int64($0), writing: true, base: midnight(-1) + 36_000_000)
        }
        let payload = PassiveFocusAggregator.day(Date(), from: today + yesterday)
        #expect(payload.totalWritingSeconds == 10.0)
        #expect(payload.tickCount == 4)
        #expect(payload.stretches.count == 1)
        #expect(payload.stretches[0].intensitySamples.isEmpty == false)
    }

    @Test("an empty day is well formed rather than missing")
    func emptyDay() {
        let payload = PassiveFocusAggregator.day(Date(), from: [])
        #expect(payload.totalWritingSeconds == 0)
        #expect(payload.stretches.isEmpty)
        #expect(payload.dayEndMs > payload.dayStartMs)
    }

    @Test("a range has one entry per day with today last")
    func rangeShape() throws {
        let d = (0..<4).map { decision(Int64($0), writing: true, base: midnight() + 36_000_000) }
        let range = PassiveFocusAggregator.range(days: 7, from: d)
        #expect(range.days.count == 7)
        let last = try #require(range.days.last)
        #expect(last.isToday)
        #expect(last.writingSeconds == 10.0)
        #expect(range.maxSeconds == 10.0)
        let onlyOneToday = range.days.filter(\.isToday).count
        #expect(onlyOneToday == 1)
    }

    @Test("days with no data report zero rather than being dropped")
    func rangeKeepsEmptyDays() {
        let range = PassiveFocusAggregator.range(days: 30, from: [])
        #expect(range.days.count == 30)
        #expect(range.maxSeconds == 0)
        let allZero = range.days.allSatisfy { $0.writingSeconds == 0 }
        #expect(allZero)
    }

    // MARK: - Time of day

    @Test("time of day buckets by local hour and ignores idle")
    func timeOfDayBuckets() throws {
        let tenAM = midnight() + 10 * 3_600_000
        let writing = (0..<4).map { decision(Int64($0), writing: true, base: tenAM) }
        let idle = (0..<4).map { decision(Int64($0), writing: false, base: tenAM) }
        let tod = PassiveFocusAggregator.timeOfDay(days: 7, from: writing + idle)
        #expect(tod.buckets.count == 24)
        let ten = try #require(tod.buckets.first { $0.hour == 10 })
        #expect(ten.seconds == 10.0)
        #expect(tod.maxSeconds == 10.0)
        let elsewhere = tod.buckets.filter { $0.hour != 10 }.allSatisfy { $0.seconds == 0 }
        #expect(elsewhere)
    }

    @Test("decisions older than the window are excluded")
    func timeOfDayWindow() {
        let old = (0..<8).map {
            decision(Int64($0), writing: true, base: midnight(-30) + 36_000_000)
        }
        let tod = PassiveFocusAggregator.timeOfDay(days: 7, from: old)
        #expect(tod.maxSeconds == 0)
    }
}
