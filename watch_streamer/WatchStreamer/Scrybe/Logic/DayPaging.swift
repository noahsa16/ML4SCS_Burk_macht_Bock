import Foundation

/// Which day the Heute page shows, counted back from today.
///
/// The page pages through the 90-day history the store already keeps, so this
/// only has to turn an offset into a caption and a seven-day window. Pure, so
/// the wording rules are testable without a view.
struct DayPaging {
    /// 0 is today; larger values step back one day each.
    let offset: Int
    /// Days oldest-first, today last — `FocusRangeDTO.days`.
    let days: [FocusDayDTO]

    /// How far back paging goes: to the first day with writing on record.
    /// Ninety blank days behind a week-old install would be a long swipe
    /// through nothing.
    var maxOffset: Int {
        guard let first = days.firstIndex(where: { $0.writingSeconds > 0 }) else { return 0 }
        return days.count - 1 - first
    }
    var isToday: Bool { offset == 0 }
    var canGoBack: Bool { offset < maxOffset }
    var canGoForward: Bool { offset > 0 }

    private var index: Int? {
        let i = days.count - 1 - offset
        return days.indices.contains(i) ? i : nil
    }

    var day: FocusDayDTO? { index.map { days[$0] } }

    /// The seven days ending on the shown one, shorter only at the start of
    /// the history. The shown day is what the strip highlights.
    var window: [FocusDayDTO] {
        guard let end = index else { return [] }
        return Array(days[max(0, end - 6)...end])
    }

    var windowMax: Double { window.map(\.writingSeconds).max() ?? 0 }

    /// "Heute", "Gestern", then the weekday while it is unambiguous, then the
    /// date. Callers localize the first two; the rest is already localized.
    enum Caption: Equatable {
        case today
        case yesterday
        case weekday(String)
        case date(String)
    }

    var caption: Caption {
        switch offset {
        case 0: return .today
        case 1: return .yesterday
        case 2...6:
            return .weekday(day.map { DateFormatting.weekday(iso: $0.date) } ?? "")
        default:
            return .date(day.map { DateFormatting.dayMonth(iso: $0.date) } ?? "")
        }
    }
}
