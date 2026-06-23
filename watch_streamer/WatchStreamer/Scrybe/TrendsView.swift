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

    private var allDays: [FocusDayDTO] { focus.history?.days ?? [] }
    private var hasAnyData: Bool { allDays.contains { $0.writingSeconds > 0 } }

    private var monthDays: [FocusDayDTO] { Array(allDays.suffix(30)) }
    private var monthMax: Double { monthDays.map(\.writingSeconds).max() ?? 0 }

    private var thisWeek: Double { (focus.week?.days ?? []).reduce(0) { $0 + $1.writingSeconds } }
    private var lastWeek: Double? {
        guard allDays.count >= 14 else { return nil }
        return allDays.suffix(14).prefix(7).reduce(0) { $0 + $1.writingSeconds }
    }
    private var thisMonth: Double { monthDays.reduce(0) { $0 + $1.writingSeconds } }
    private var lastMonth: Double? {
        guard allDays.count >= 60 else { return nil }
        return allDays.suffix(60).prefix(30).reduce(0) { $0 + $1.writingSeconds }
    }

    private var summarySum: Double { range == .week ? thisWeek : thisMonth }
    private var summaryPrev: Double? { range == .week ? lastWeek : lastMonth }
    private var summaryTitle: String { range == .week ? "Diese Woche" : "Letzte 30 Tage" }

    var body: some View {
        ScrollView {
            ScrybeGlassGroup(spacing: 24) {
                VStack(alignment: .leading, spacing: 24) {
                    if focus.isOffline {
                        OfflineBanner(lastUpdated: focus.lastUpdated)
                    }
                    Picker("Zeitraum", selection: $range) {
                        ForEach(TrendRange.allCases) { Text(LocalizedStringKey($0.rawValue)).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    if !hasAnyData {
                        Text("Deine Trends füllen sich mit den ersten Tagen.")
                            .font(.subheadline)
                            .foregroundStyle(theme.sepia)
                    }
                    summaryCard
                    streakCard
                    timeOfDayCard
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
                Image(systemName: "flame.fill").foregroundStyle(theme.sepia)
                Text("\(focus.streak)")
                    .font(.system(.largeTitle, design: .serif).weight(.semibold))
                    .foregroundStyle(theme.ink)
                    .contentTransition(.numericText())
                Text("Tage").font(.subheadline).foregroundStyle(theme.sepia)
                Spacer()
                if focus.longestStreak > 0 {
                    Text("Längste: \(focus.longestStreak)")
                        .font(.caption).foregroundStyle(theme.sepia)
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Streak \(focus.streak) Tage, längste \(focus.longestStreak)")
            StreakCalendar(days: Array(allDays.suffix(7)), goalSeconds: goalSeconds)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
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
                .foregroundStyle(up ? theme.success : theme.danger)
                .accessibilityLabel("\(magnitude) \(direction) als zuvor")
        }
    }
}

#Preview {
    TrendsView().scrybeTheme()
}
