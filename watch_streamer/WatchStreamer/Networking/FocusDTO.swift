import Foundation

struct FocusStretchDTO: Decodable, Identifiable, Sendable {
    let startMs: Int
    let endMs: Int
    let durationS: Double
    // Downsampled mean-proba across the stretch (sparkline). Optional so an
    // older server without the field can't break decoding of the Heute screen.
    let intensity: [Double]?
    var id: Int { startMs }

    /// Always-present accessor for the UI (empty when the server omitted it).
    var intensitySamples: [Double] { intensity ?? [] }

    enum CodingKeys: String, CodingKey {
        case startMs = "start_ms"
        case endMs = "end_ms"
        case durationS = "duration_s"
        case intensity
    }
}

struct FocusTodayDTO: Decodable, Sendable {
    let date: String
    let totalWritingSeconds: Double
    let stretches: [FocusStretchDTO]
    let tickCount: Int
    let dayStartMs: Int
    let dayEndMs: Int
    let nowMs: Int

    enum CodingKeys: String, CodingKey {
        case date, stretches
        case totalWritingSeconds = "total_writing_seconds"
        case tickCount = "tick_count"
        case dayStartMs = "day_start_ms"
        case dayEndMs = "day_end_ms"
        case nowMs = "now_ms"
    }
}

struct FocusDayDTO: Decodable, Identifiable, Sendable {
    let date: String
    let weekday: String
    let writingSeconds: Double
    let isToday: Bool
    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date, weekday
        case writingSeconds = "writing_seconds"
        case isToday = "is_today"
    }
}

struct FocusRangeDTO: Decodable, Sendable {
    let days: [FocusDayDTO]
    let today: String
    let maxSeconds: Double

    enum CodingKeys: String, CodingKey {
        case days, today
        case maxSeconds = "max_seconds"
    }
}

struct FocusHourBucketDTO: Decodable, Identifiable, Sendable {
    let hour: Int
    let seconds: Double
    var id: Int { hour }
}

struct FocusTimeOfDayDTO: Decodable, Sendable {
    let buckets: [FocusHourBucketDTO]
    let days: Int
    let maxSeconds: Double

    enum CodingKeys: String, CodingKey {
        case buckets, days
        case maxSeconds = "max_seconds"
    }
}
