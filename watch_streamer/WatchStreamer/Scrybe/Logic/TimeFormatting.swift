import Foundation

enum TimeFormatting {
    static func clock(seconds: Double) -> String {
        let total = Int(max(0, seconds)) / 60
        return "\(total / 60):\(String(format: "%02d", total % 60))"
    }

    static func human(seconds: Double) -> String {
        let total = Int(max(0, seconds)) / 60
        let h = total / 60
        let m = total % 60
        return h > 0 ? "\(h)h \(m)m" : "\(m)m"
    }
}

/// Formats the server's ISO `date` strings ("2026-06-22") for display, so the
/// UI never surfaces the server's English `weekday` field (`%a` → "Mon") inside
/// the German app. Locale-driven: derives the weekday and a readable date from
/// the ISO date itself.
enum DateFormatting {
    private static let parser: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    // Why: a DateFormatter is expensive to build, and these run inside SwiftUI
    // body recomputation — History renders one per row per pass. Cache by
    // pattern *and* locale so the in-app DE/EN override still switches
    // languages instead of serving a stale formatter.
    private static let cacheLock = NSLock()
    private static var cache: [String: DateFormatter] = [:]

    private static func formatter(_ pattern: String) -> DateFormatter {
        let locale = ScrybeSettings.localeOverride ?? .current
        let key = "\(pattern)|\(locale.identifier)"
        cacheLock.lock()
        defer { cacheLock.unlock() }
        if let cached = cache[key] { return cached }
        let f = DateFormatter()
        // Follow the in-app DE/EN override so weekday/month names match the
        // chosen language (not just the device locale).
        f.locale = locale
        f.timeZone = .current
        f.setLocalizedDateFormatFromTemplate(pattern)
        cache[key] = f
        return f
    }

    private static func date(from iso: String) -> Date? { parser.date(from: iso) }

    /// Localized full weekday, e.g. "Montag". Falls back to the ISO string.
    static func weekday(iso: String) -> String {
        guard let d = date(from: iso) else { return iso }
        return formatter("EEEE").string(from: d)
    }

    /// Localized short weekday for compact labels, e.g. "Mo". Falls back to ""
    /// so a malformed date never prints raw characters under a bar.
    static func shortWeekday(iso: String) -> String {
        guard let d = date(from: iso) else { return "" }
        return formatter("EEEEEE").string(from: d)
    }

    /// Localized day-and-month, e.g. "22. Juni". Falls back to the ISO string.
    static func dayMonth(iso: String) -> String {
        guard let d = date(from: iso) else { return iso }
        return formatter("dMMMM").string(from: d)
    }

    /// Localized day-and-month for a millisecond timestamp, e.g. "22. Juni" —
    /// for data keyed by wall-clock ms rather than an ISO day, such as a
    /// finished `BestiaryEntry`.
    static func dayMonth(ms: Int64) -> String {
        formatter("dMMMM").string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}
