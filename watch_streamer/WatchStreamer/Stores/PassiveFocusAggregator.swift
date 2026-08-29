import Foundation

/// Builds the Heute / Trends / Verlauf payloads from on-device passive
/// decisions, replacing the server's `/focus/*` endpoints.
///
/// A port of `src/server/routes/focus.py`, with one deliberate difference the
/// server could not make: the server aggregates 1 Hz ticks, where a stretch's
/// length is simply `end - start`. Passive windows **overlap** — a 5 s window
/// every 2.5 s — so wall-clock extent double-counts. Writing time is therefore
/// summed from `creditSeconds` (the stride), and only the timeline extent uses
/// start/end. See `PassiveWindowBuilder` for where that stride comes from.
enum PassiveFocusAggregator {
    /// Silence that does not break a writing stretch. Matches the server's
    /// 2.5 s, which is `max_gap_ms` from the training-time label closing.
    static let stretchGapMs: Int64 = 2_500
    /// Sparkline resolution, matching the server's `_INTENSITY_BINS`.
    static let intensityBins = 24

    // MARK: - Stretches

    /// Runs of writing decisions, gaps up to `stretchGapMs` forgiven.
    ///
    /// The gap is measured from the previous window's end to the next one's
    /// start, so back-to-back overlapping windows read as negative gap and
    /// never split a stretch; roughly three consecutive missing windows do.
    static func stretches(from decisions: [PassiveDecision]) -> [FocusStretchDTO] {
        let sorted = decisions.sorted { $0.startMs < $1.startMs }
        var out: [FocusStretchDTO] = []
        var startMs: Int64?
        var endMs: Int64 = 0
        var credit: Double = 0

        func close() {
            guard let s = startMs else { return }
            out.append(FocusStretchDTO(startMs: Int(s), endMs: Int(endMs),
                                       durationS: (credit * 10).rounded() / 10,
                                       intensity: nil))
            startMs = nil
            credit = 0
        }

        for d in sorted {
            let broke = startMs != nil && d.startMs - endMs > stretchGapMs
            if d.writing {
                if broke { close() }
                if startMs == nil { startMs = d.startMs; credit = 0 }
                endMs = max(endMs, d.endMs)
                credit += d.creditSeconds
            } else if broke {
                close()
            }
        }
        close()
        return out
    }

    /// Downsampled writing probability across a stretch. Empty bins forward-fill
    /// so a brief hole reads as a plateau rather than a dip to zero.
    static func intensity(for stretch: FocusStretchDTO,
                          in decisions: [PassiveDecision]) -> [Double] {
        let start = Int64(stretch.startMs), end = Int64(stretch.endMs)
        let window = decisions.filter { $0.startMs >= start && $0.startMs <= end }
        guard !window.isEmpty else { return [] }

        let bins = max(1, min(intensityBins, window.count))
        let span = Double(max(1, end - start))
        var sums = [Double](repeating: 0, count: bins)
        var counts = [Int](repeating: 0, count: bins)
        for d in window {
            let b = min(bins - 1, Int(Double(d.startMs - start) / span * Double(bins)))
            sums[b] += probability(ofLogit: d.logit)
            counts[b] += 1
        }
        var out: [Double] = []
        var last: Double = 0
        for i in 0..<bins {
            if counts[i] > 0 { last = sums[i] / Double(counts[i]) }
            out.append((last * 1000).rounded() / 1000)
        }
        return out
    }

    /// The model emits a logit; the sparkline wants a probability.
    static func probability(ofLogit logit: Float) -> Double {
        1 / (1 + exp(-Double(logit)))
    }

    // MARK: - Day payloads

    static func day(_ date: Date, from decisions: [PassiveDecision],
                    calendar: Calendar = .current, now: Date = Date()) -> FocusTodayDTO {
        let start = calendar.startOfDay(for: date)
        let end = calendar.date(byAdding: .day, value: 1, to: start) ?? start
        let startMs = Int64(start.timeIntervalSince1970 * 1000)
        let endMs = Int64(end.timeIntervalSince1970 * 1000)
        let inDay = decisions.filter { $0.startMs >= startMs && $0.startMs < endMs }

        let bare = stretches(from: inDay)
        let filled = bare.map {
            FocusStretchDTO(startMs: $0.startMs, endMs: $0.endMs, durationS: $0.durationS,
                            intensity: intensity(for: $0, in: inDay))
        }
        let total = filled.reduce(0) { $0 + $1.durationS }
        return FocusTodayDTO(date: isoDate(start, calendar: calendar),
                             totalWritingSeconds: (total * 10).rounded() / 10,
                             stretches: filled,
                             tickCount: inDay.count,
                             dayStartMs: Int(startMs),
                             dayEndMs: Int(endMs),
                             nowMs: Int(now.timeIntervalSince1970 * 1000))
    }

    /// Writing seconds per local day, oldest first, `days` entries, today last.
    static func range(days: Int, from decisions: [PassiveDecision],
                      calendar: Calendar = .current, now: Date = Date()) -> FocusRangeDTO {
        let todayStart = calendar.startOfDay(for: now)
        var out: [FocusDayDTO] = []
        var maxSeconds: Double = 0
        for offset in stride(from: days - 1, through: 0, by: -1) {
            guard let dayStart = calendar.date(byAdding: .day, value: -offset, to: todayStart)
            else { continue }
            let payload = day(dayStart, from: decisions, calendar: calendar, now: now)
            maxSeconds = max(maxSeconds, payload.totalWritingSeconds)
            out.append(FocusDayDTO(date: payload.date,
                                   weekday: weekday(dayStart, calendar: calendar),
                                   writingSeconds: payload.totalWritingSeconds,
                                   isToday: dayStart == todayStart))
        }
        return FocusRangeDTO(days: out,
                             today: isoDate(todayStart, calendar: calendar),
                             maxSeconds: maxSeconds)
    }

    /// Writing seconds per hour of day, summed over the last `days` days.
    static func timeOfDay(days: Int, from decisions: [PassiveDecision],
                          calendar: Calendar = .current,
                          now: Date = Date()) -> FocusTimeOfDayDTO {
        let todayStart = calendar.startOfDay(for: now)
        guard let from = calendar.date(byAdding: .day, value: -(days - 1), to: todayStart)
        else { return FocusTimeOfDayDTO(buckets: [], days: days, maxSeconds: 0) }
        let fromMs = Int64(from.timeIntervalSince1970 * 1000)

        var seconds = [Double](repeating: 0, count: 24)
        for d in decisions where d.writing && d.startMs >= fromMs {
            let date = Date(timeIntervalSince1970: Double(d.startMs) / 1000)
            let hour = calendar.component(.hour, from: date)
            seconds[hour] += d.creditSeconds
        }
        let buckets = (0..<24).map {
            FocusHourBucketDTO(hour: $0, seconds: (seconds[$0] * 10).rounded() / 10)
        }
        return FocusTimeOfDayDTO(buckets: buckets, days: days,
                                 maxSeconds: buckets.map(\.seconds).max() ?? 0)
    }

    // MARK: - Formatting

    static func isoDate(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    private static func weekday(_ date: Date, calendar: Calendar) -> String {
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = Locale.current
        f.setLocalizedDateFormatFromTemplate("EEE")
        return f.string(from: date)
    }
}
