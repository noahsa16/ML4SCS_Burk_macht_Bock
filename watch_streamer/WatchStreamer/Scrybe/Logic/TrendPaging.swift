import Foundation

/// Which stretch of the history the Trends page shows: a seven- or thirty-day
/// window, counted back from today in whole windows.
///
/// Pure, so the window arithmetic, the comparison window and the caption
/// rules are testable without a view. Mirrors `DayPaging`, which does the
/// same for single days on Heute.
nonisolated struct TrendPaging {
    enum Span: Int, Equatable {
        case week = 7
        case month = 30
    }

    let span: Span
    /// 0 is the window ending today; each step back is one full window.
    let offset: Int
    /// Days oldest-first, today last — `FocusRangeDTO.days`.
    let days: [FocusDayDTO]

    var length: Int { span.rawValue }
    var isCurrent: Bool { offset == 0 }

    private var endIndex: Int? {
        let i = days.count - 1 - offset * length
        return i >= 0 ? i : nil
    }

    /// The days shown, shorter only at the start of the history.
    var window: [FocusDayDTO] {
        guard let end = endIndex else { return [] }
        return Array(days[max(0, end - length + 1)...end])
    }

    /// The same-length window just before, or `nil` when the history does
    /// not hold all of it — a partial comparison would read as a drop.
    var previousWindow: [FocusDayDTO]? {
        guard let end = endIndex else { return nil }
        let start = end - length + 1
        guard start - length >= 0 else { return nil }
        return Array(days[(start - length)..<start])
    }

    var sum: Double { window.reduce(0) { $0 + $1.writingSeconds } }
    var previousSum: Double? { previousWindow?.reduce(0) { $0 + $1.writingSeconds } }
    var maxSeconds: Double { window.map(\.writingSeconds).max() ?? 0 }

    /// How far back paging goes: to the window holding the first day with
    /// writing. Blank windows behind that are a swipe through nothing.
    var maxOffset: Int {
        guard let first = days.firstIndex(where: { $0.writingSeconds > 0 }) else { return 0 }
        return (days.count - 1 - first) / length
    }
    var canGoBack: Bool { offset < maxOffset }
    var canGoForward: Bool { offset > 0 }

    /// The period's name for the section caption.
    enum Caption: Equatable {
        case thisWeek
        case lastWeek
        case last30Days
        case previous30Days
        /// Older windows are named by their first and last day.
        case range(startISO: String, endISO: String)
    }

    var caption: Caption {
        switch (span, offset) {
        case (.week, 0): return .thisWeek
        case (.week, 1): return .lastWeek
        case (.month, 0): return .last30Days
        case (.month, 1): return .previous30Days
        default:
            let w = window
            return .range(startISO: w.first?.date ?? "", endISO: w.last?.date ?? "")
        }
    }

    /// The day the chart highlights when nothing was tapped: the newest one.
    var defaultSelection: String? { window.last?.date }
}
