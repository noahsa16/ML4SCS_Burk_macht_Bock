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

    private static func formatter(_ pattern: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = .current
        f.timeZone = .current
        f.setLocalizedDateFormatFromTemplate(pattern)
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
}
