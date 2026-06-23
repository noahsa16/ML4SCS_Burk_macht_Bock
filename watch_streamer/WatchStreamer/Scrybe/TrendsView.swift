import SwiftUI

struct TrendsView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var thisWeek: Double {
        (focus.week?.days ?? []).reduce(0) { $0 + $1.writingSeconds }
    }
    // history days are oldest -> newest; suffix(14).prefix(7) is the prior week.
    private var lastWeek: Double? {
        guard let days = focus.history?.days, days.count >= 14 else { return nil }
        return days.suffix(14).prefix(7).reduce(0) { $0 + $1.writingSeconds }
    }
    private var calendarDays: [FocusDayDTO] {
        Array((focus.history?.days ?? []).suffix(35))
    }
    private var thisWeekText: String { TimeFormatting.human(seconds: thisWeek) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if focus.isOffline {
                    OfflineBanner(lastUpdated: focus.lastUpdated)
                }
                weekHeader
                if let week = focus.week {
                    WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
                }
                streakSection
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { theme.paper.ignoresSafeArea() }
    }

    private var weekHeader: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Diese Woche").font(.headline).foregroundStyle(theme.ink)
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(thisWeekText)
                    .font(.system(.largeTitle, design: .serif).weight(.semibold))
                    .foregroundStyle(theme.ink)
                comparison
            }
        }
    }

    private var streakSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Streak").font(.headline).foregroundStyle(theme.ink)
            StreakCalendar(days: calendarDays, goalSeconds: goalSeconds)
        }
    }

    @ViewBuilder private var comparison: some View {
        if let last = lastWeek {
            let delta = thisWeek - last
            let up = delta >= 0
            let magnitude = TimeFormatting.human(seconds: abs(delta))
            let direction = up ? "mehr" : "weniger"
            let a11y = "\(magnitude) \(direction) als letzte Woche"
            Label(magnitude,
                  systemImage: up ? "arrowtriangle.up.fill" : "arrowtriangle.down.fill")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(up ? theme.success : theme.danger)
                .accessibilityLabel(a11y)
        }
    }
}

#Preview {
    TrendsView().scrybeTheme()
}
