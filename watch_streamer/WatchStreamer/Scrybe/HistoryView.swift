import SwiftUI

struct HistoryView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var days: [FocusDayDTO] {
        Array((focus.history?.days ?? []).reversed())
    }

    var body: some View {
        NavigationStack {
            List {
                if focus.isOffline {
                    OfflineBanner(lastUpdated: focus.lastUpdated)
                        .listRowBackground(Color.clear)
                }
                ForEach(days) { day in
                    NavigationLink(value: day.date) {
                        HistoryRow(day: day, goalSeconds: goalSeconds)
                    }
                    .listRowBackground(theme.paperTop)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background { theme.paper.ignoresSafeArea() }
            .navigationDestination(for: String.self) { date in
                DayDetailView(date: date)
            }
        }
    }
}

private struct HistoryRow: View {
    let day: FocusDayDTO
    let goalSeconds: Double
    @Environment(\.scrybe) private var theme

    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }
    private var durationColor: Color { isMet ? theme.success : theme.ink }
    private var durationText: String { TimeFormatting.human(seconds: day.writingSeconds) }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(DateFormatting.dayMonth(iso: day.date))
                    .font(.subheadline).foregroundStyle(theme.ink)
                Text(DateFormatting.weekday(iso: day.date))
                    .font(.caption).foregroundStyle(theme.sepia)
            }
            Spacer()
            Text(durationText)
                .font(.body.weight(.medium))
                .foregroundStyle(durationColor)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    HistoryView().scrybeTheme()
}
