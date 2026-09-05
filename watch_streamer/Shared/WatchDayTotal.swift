import Foundation

/// Today's writing time as the phone knows it, mirrored to the Watch.
///
/// The Watch counts only what its own recorder has been read for, and the
/// recorder is readable minutes after the fact. A focus session is classified
/// on the phone in real time, so right after one the phone's total is ahead
/// of the Watch's. Like the daily goal, the total rides on every command and
/// poll reply, and the Watch shows whichever of the two figures is larger —
/// the phone's total already contains everything the Watch handed over, so
/// the larger one is never a double count, only the fresher one.
///
/// The day is carried alongside the seconds. A total without its day would
/// survive midnight in `UserDefaults` and be shown against the wrong day.
public nonisolated struct WatchDayTotal: Codable, Equatable, Sendable {
    /// Local calendar day as `yyyy-MM-dd`.
    public let day: String
    public let writingSeconds: Double

    public init(day: String, writingSeconds: Double) {
        self.day = day
        self.writingSeconds = writingSeconds
    }

    public static func isoDay(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    /// The seconds to show for `now`'s day: the mirrored total only while it
    /// still describes today, otherwise nothing.
    public func writingSeconds(on now: Date, calendar: Calendar = .current) -> Double? {
        day == Self.isoDay(now, calendar: calendar) ? writingSeconds : nil
    }

    public var payloadFields: [String: Any] {
        [WatchPayloadKey.todayDay: day,
         WatchPayloadKey.todayWritingSeconds: writingSeconds]
    }

    /// Both fields must be present and sane; a partial payload is no total.
    public static func from(payload: [String: Any]) -> WatchDayTotal? {
        guard let day = payload[WatchPayloadKey.todayDay] as? String, day.count == 10,
              let seconds = WatchPayloadValue.double(payload[WatchPayloadKey.todayWritingSeconds]),
              seconds >= 0 else { return nil }
        return WatchDayTotal(day: day, writingSeconds: seconds)
    }

    public static let defaultsKey = "scrybe.watchDayTotal"

    public static func load(from defaults: UserDefaults) -> WatchDayTotal? {
        guard let data = defaults.data(forKey: defaultsKey) else { return nil }
        return try? JSONDecoder().decode(WatchDayTotal.self, from: data)
    }

    public func store(in defaults: UserDefaults) {
        guard let data = try? JSONEncoder().encode(self) else { return }
        defaults.set(data, forKey: Self.defaultsKey)
    }
}
