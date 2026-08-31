import SwiftUI

struct TrendsView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme
    @State private var range: TrendRange = .week

    enum TrendRange: String, CaseIterable, Identifiable {
        case week = "Woche", month = "Monat"
        var id: String { rawValue }
    }

    // All derived once in FocusStore when the history changes, rather than
    // recomputed on every body pass of a view that observes a 5-second poll.
    private var hasAnyData: Bool { focus.hasAnyHistory }
    private var monthDays: [FocusDayDTO] { focus.monthDays }
    private var monthMax: Double { focus.monthMax }
    private var thisWeek: Double { focus.thisWeekSum }
    private var lastWeek: Double? { focus.previousWeekSum }
    private var thisMonth: Double { focus.monthSum }
    private var lastMonth: Double? { focus.previousMonthSum }

    private var summarySum: Double { range == .week ? thisWeek : thisMonth }
    private var summaryPrev: Double? { range == .week ? lastWeek : lastMonth }
    private var summaryTitle: String { range == .week ? "Diese Woche" : "Letzte 30 Tage" }

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
            ScrybeGlassGroup(spacing: 24) {
                VStack(alignment: .leading, spacing: 24) {
                    if focus.watchUnreachable {
                        OfflineBanner(lastUpdated: focus.lastUpdated)
                    }
                    SerifSegmentedControl(
                        options: TrendRange.allCases.map { ($0, $0.rawValue) },
                        selection: $range)
                    if !hasAnyData {
                        Text("Deine Trends füllen sich mit den ersten Tagen.")
                            .font(.subheadline)
                            .foregroundStyle(theme.secondaryInk)
                    }
                    summaryCard
                    streakCard
                    timeOfDayCard
                    historyRow
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { theme.paper.ignoresSafeArea() }
    }

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(summaryTitle).font(.headline).foregroundStyle(theme.ink)
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(TimeFormatting.human(seconds: summarySum))
                        .font(.system(.largeTitle, design: .serif).weight(.semibold))
                        .foregroundStyle(theme.ink)
                        .contentTransition(.numericText())
                    comparison
                }
            }
            if range == .week, let week = focus.week {
                WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
            } else {
                RangeBarChart(days: monthDays, maxSeconds: monthMax)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .scrybeSurface(cornerRadius: 16)
    }

    private var streakCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                ScrybeGlyphShape(glyph: .streak)
                    .stroke(style: StrokeStyle(lineWidth: 1.4, lineCap: .round))
                    .frame(width: 16, height: 16)
                    .foregroundStyle(theme.sepia)
                Text("\(focus.streak)")
                    .font(.system(.largeTitle, design: .serif).weight(.semibold))
                    .foregroundStyle(theme.ink)
                    .contentTransition(.numericText())
                Text("Tage").font(.subheadline).foregroundStyle(theme.secondaryInk)
                Spacer()
                if focus.longestStreak > 0 {
                    Text("Längste: \(focus.longestStreak)")
                        .font(.caption).foregroundStyle(theme.secondaryInk)
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Streak \(focus.streak) Tage, längste \(focus.longestStreak)")
            StreakCalendar(days: focus.lastSevenDays, goalSeconds: goalSeconds)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .scrybeSurface(cornerRadius: 16)
    }

    private var historyRow: some View {
        NavigationLink(value: HistoryDestination()) {
            HStack(spacing: 12) {
                Text("Verlauf öffnen").font(.headline).foregroundStyle(theme.ink)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.footnote)
                    .foregroundStyle(theme.mutedInk)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
        .scrybeSurface(cornerRadius: 16)
    }

    private var timeOfDayCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Tageszeit").font(.headline).foregroundStyle(theme.ink)
            TimeOfDayChart(buckets: focus.timeOfDay?.buckets ?? [])
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .scrybeSurface(cornerRadius: 16)
    }

    @ViewBuilder private var comparison: some View {
        if let last = summaryPrev {
            let delta = summarySum - last
            let up = delta >= 0
            let magnitude = TimeFormatting.human(seconds: abs(delta))
            let direction = up ? "mehr" : "weniger"
            Label(magnitude,
                  systemImage: up ? "arrowtriangle.up.fill" : "arrowtriangle.down.fill")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(up ? theme.successInk : theme.danger)
                .accessibilityLabel("\(magnitude) \(direction) als zuvor")
        }
    }
}

#Preview {
    TrendsView().scrybeTheme()
}

/// A push target with no payload; Verlauf reads the shared store.
struct HistoryDestination: Hashable {}
