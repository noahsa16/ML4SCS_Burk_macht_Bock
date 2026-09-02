import SwiftUI
import UIKit

/// Trends: one window of days at a time — a week or thirty days — with its
/// total as the headline figure, hatched bars a reader can tap, the streak,
/// the time of day, and a short list of what the numbers add up to. Windows
/// page with the header chevrons or a sideways swipe, like days on Heute.
struct TrendsView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

#if DEBUG
    @State private var span: TrendPaging.Span = DebugFixture.initialSpan ?? .week
#else
    @State private var span: TrendPaging.Span = .week
#endif
    @State private var offset = 0
    /// The tapped bar. `nil` falls back to the window's newest day, so a
    /// fresh page always has one day in the accent.
    @State private var selectedDate: String?
    @State private var turnedBack = true

    private var paging: TrendPaging {
        TrendPaging(span: span, offset: offset, days: focus.history?.days ?? [])
    }
    private var shownDate: String? { selectedDate ?? paging.defaultSelection }
    private var selectedDay: FocusDayDTO? {
        paging.window.first { $0.date == shownDate }
    }
    private var insights: [TrendInsight] {
        TrendInsights.insights(window: paging.window,
                               allDays: focus.history?.days ?? [],
                               goalSeconds: goalSeconds)
    }

    var body: some View {
        // Why the stack lives here: Verlauf lost its own when it left the tab
        // strip, and a day selection has to land somewhere.
        NavigationStack {
            content
                .navigationDestination(for: HistoryDestination.self) { _ in HistoryView() }
                .navigationDestination(for: String.self) { DayDetailView(date: $0) }
        }
    }

    private var content: some View {
        InkRefreshScroll(action: { await focus.refreshForPull() }) {
            VStack(alignment: .leading, spacing: 28) {
                ScrybeHeader(label: "Trends",
                             onPrevious: paging.canGoBack ? { turn(by: 1) } : nil,
                             onNext: paging.canGoForward ? { turn(by: -1) } : nil,
                             previousLabel: span == .week ? "Vorherige Woche" : "Vorheriger Monat",
                             nextLabel: span == .week ? "Nächste Woche" : "Nächster Monat")
                    .padding(.horizontal, -20)
                if focus.watchUnreachable {
                    OfflineBanner(lastUpdated: focus.lastUpdated)
                }
                SerifSegmentedControl(
                    options: [(TrendPaging.Span.week, "Woche"), (.month, "Monat")],
                    selection: $span)
                if !focus.hasAnyHistory {
                    Text("Deine Trends füllen sich mit den ersten Tagen.")
                        .scrybeMarginNote()
                }
                periodSection
                ScrybeRule()
                streakSection
                ScrybeRule()
                timeOfDaySection
                if !insights.isEmpty {
                    ScrybeRule()
                    insightsSection
                }
                ScrybeRule()
                historyRow
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 32)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { theme.paper.ignoresSafeArea() }
        .simultaneousGesture(turnGesture)
        .onChange(of: span) { _ in
            selectedDate = nil
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) { offset = 0 }
        }
    }

    // MARK: - Period

    private var periodSection: some View {
        VStack(alignment: .leading, spacing: 20) {
            ScrybeSectionHeader(periodCaption) {
                if let note = deltaNote {
                    Text(note).scrybeMarginNote()
                }
            }
            DurationFigure(seconds: paging.sum)
            HatchedBarChart(days: paging.window,
                            maxSeconds: paging.maxSeconds,
                            selectedDate: shownDate,
                            barHeight: span == .week ? 150 : 110) { date in
                UISelectionFeedbackGenerator().selectionChanged()
                selectedDate = date
            }
            if let day = selectedDay {
                SelectedDayRow(day: day, windowAverage: windowAverage,
                               goalSeconds: goalSeconds)
            }
        }
        // Why keyed by the offset: a turned window is a different page, and a
        // slide says so where figures morphing in place would not.
        .id("\(span.rawValue)-\(offset)")
        .transition(reduceMotion ? .opacity : .asymmetric(
            insertion: .move(edge: turnedBack ? .leading : .trailing).combined(with: .opacity),
            removal: .move(edge: turnedBack ? .trailing : .leading).combined(with: .opacity)))
    }

    private var periodCaption: LocalizedStringKey {
        switch paging.caption {
        case .thisWeek: return "Diese Woche"
        case .lastWeek: return "Letzte Woche"
        case .last30Days: return "Letzte 30 Tage"
        case .previous30Days: return "Die 30 Tage davor"
        case .range(let start, let end):
            return "\(DateFormatting.dayMonth(iso: start)) – \(DateFormatting.dayMonth(iso: end))"
        }
    }

    /// "+4 Min. vs. Vorwoche" — only when a full comparison window exists.
    private var deltaNote: LocalizedStringKey? {
        guard let previous = paging.previousSum else { return nil }
        let delta = paging.sum - previous
        let magnitude = TimeFormatting.abbreviated(seconds: abs(delta))
        let week = span == .week
        if abs(delta) < 60 {
            return week ? "wie in der Vorwoche" : "wie im Vormonat"
        }
        if delta > 0 {
            return week ? "+\(magnitude) vs. Vorwoche" : "+\(magnitude) vs. Vormonat"
        }
        return week ? "−\(magnitude) vs. Vorwoche" : "−\(magnitude) vs. Vormonat"
    }

    private var windowAverage: Double {
        let active = paging.window.filter { $0.writingSeconds > 0 }
        guard !active.isEmpty else { return 0 }
        return active.reduce(0) { $0 + $1.writingSeconds } / Double(active.count)
    }

    // MARK: - Streak

    private var streakSection: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text("\(focus.streak)").scrybeDisplayFigure(size: 40)
                Text(focus.streak == 1 ? "Tag Streak" : "Tage Streak").scrybeCaption()
                Spacer()
                Text(streakNote).scrybeMarginNote()
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel(Text("Streak \(focus.streak) Tage, längste \(focus.longestStreak)"))
            StreakCalendar(days: focus.lastSevenDays, goalSeconds: goalSeconds)
        }
    }

    private var streakNote: LocalizedStringKey {
        switch focus.streak {
        case 0: return "fang heute an"
        case 1...2: return "dranbleiben"
        case 3...6: return "weiter so!"
        default: return focus.streak >= focus.longestStreak ? "dein bester Lauf" : "eine ganze Woche"
        }
    }

    // MARK: - Time of day

    private var timeOfDaySection: some View {
        VStack(alignment: .leading, spacing: 20) {
            ScrybeSectionHeader("Tageszeit") {
                if let days = focus.timeOfDay?.days {
                    Text("letzte \(days) Tage").scrybeMarginNote(.footnote)
                }
            }
            TimeOfDayChart(buckets: focus.timeOfDay?.buckets ?? [])
            if let hour = TrendInsights.peakHour(buckets: focus.timeOfDay?.buckets ?? []) {
                Text("Dein bestes Schreibfenster liegt zwischen \(hour) und \((hour + 1) % 24) Uhr.")
                    .scrybeMarginNote()
            }
        }
    }

    // MARK: - Insights

    private var insightsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            ScrybeSectionHeader("Einblicke")
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(insights.enumerated()), id: \.offset) { index, insight in
                    HStack(alignment: .firstTextBaseline, spacing: 14) {
                        Text(String(format: "%02d", index + 1))
                            .font(.system(.caption, design: .serif))
                            .foregroundStyle(theme.sepia)
                            .monospacedDigit()
                        Text(text(for: insight))
                            .font(.system(.body, design: .serif))
                            .foregroundStyle(theme.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.vertical, 12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    if index < insights.count - 1 {
                        Rectangle().fill(theme.hairline).frame(height: 1)
                            .padding(.leading, 34)
                    }
                }
            }
        }
    }

    private func text(for insight: TrendInsight) -> LocalizedStringKey {
        switch insight {
        case .activeDays(let active, let of):
            return "An \(active) von \(of) Tagen geschrieben"
        case .goalDays(let met):
            return met == 1 ? "Tagesziel an einem Tag erreicht" : "Tagesziel an \(met) Tagen erreicht"
        case .bestDay(let iso, let seconds):
            let name = span == .week ? DateFormatting.weekday(iso: iso) : DateFormatting.dayMonth(iso: iso)
            return "Bester Tag: \(name) mit \(TimeFormatting.abbreviated(seconds: seconds))"
        case .averagePerActiveDay(let seconds):
            return "Im Schnitt \(TimeFormatting.abbreviated(seconds: seconds)) pro Schreibtag"
        case .weekdayHabit(let weekday):
            return "Am häufigsten schreibst du am \(DateFormatting.weekdayName(weekday))"
        }
    }

    // MARK: - History

    private var historyRow: some View {
        NavigationLink(value: HistoryDestination()) {
            HStack(spacing: 12) {
                Text("Verlauf öffnen")
                    .font(.system(.body, design: .serif))
                    .foregroundStyle(theme.ink)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.footnote)
                    .foregroundStyle(theme.mutedInk)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Turning windows

    /// A sideways swipe turns the window; the scroll view keeps every vertical
    /// drag, so the gesture only acts when it ended clearly horizontal.
    private var turnGesture: some Gesture {
        DragGesture(minimumDistance: 24)
            .onEnded { value in
                let t = value.translation
                guard abs(t.width) > 50, abs(t.width) > abs(t.height) * 1.5 else { return }
                turn(by: t.width > 0 ? 1 : -1)
            }
    }

    /// Earlier windows lie to the left, like pages already written.
    private func turn(by delta: Int) {
        let target = offset + delta
        guard target >= 0, target <= paging.maxOffset else { return }
        turnedBack = delta > 0
        selectedDate = nil
        UISelectionFeedbackGenerator().selectionChanged()
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.3)) {
            offset = target
        }
    }
}

/// The tapped day under the chart: its name and date, its figure, and one
/// remark placing it in the window. Leads to the day's own page.
private struct SelectedDayRow: View {
    let day: FocusDayDTO
    let windowAverage: Double
    let goalSeconds: Double

    @Environment(\.scrybe) private var theme

    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }

    private var remark: LocalizedStringKey? {
        if day.writingSeconds <= 0 { return "nichts geschrieben" }
        if isMet { return "Tagesziel erreicht" }
        guard windowAverage > 0 else { return nil }
        let ratio = day.writingSeconds / windowAverage
        if ratio >= 1.25 { return "über dem Schnitt" }
        if ratio <= 0.75 { return "unter dem Schnitt" }
        return "im Schnitt"
    }

    var body: some View {
        NavigationLink(value: day.date) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(day.isToday ? "Heute" : LocalizedStringKey(DateFormatting.weekday(iso: day.date)))
                        .font(.system(.body, design: .serif))
                        .foregroundStyle(theme.ink)
                    Text(DateFormatting.dayMonth(iso: day.date))
                        .font(.caption)
                        .foregroundStyle(theme.secondaryInk)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 3) {
                    Text(TimeFormatting.abbreviated(seconds: day.writingSeconds))
                        .font(.system(.body, design: .serif))
                        .foregroundStyle(theme.ink)
                        .monospacedDigit()
                    if let remark {
                        Text(remark).scrybeMarginNote(.caption)
                    }
                }
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundStyle(theme.mutedInk)
            }
            .padding(.vertical, 12)
            .padding(.horizontal, 14)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(theme.sepia.opacity(0.35), lineWidth: 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint(Text("Öffnet den Tag."))
    }
}

#Preview {
    TrendsView().scrybeTheme()
}

/// A push target with no payload; Verlauf reads the shared store.
struct HistoryDestination: Hashable {}
