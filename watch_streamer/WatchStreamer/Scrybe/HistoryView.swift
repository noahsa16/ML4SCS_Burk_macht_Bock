import SwiftUI

struct HistoryView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    // Days with activity, newest first — one section per day.
    private var activeDays: [FocusDayDTO] {
        Array((focus.history?.days ?? []).filter { $0.writingSeconds > 0 }.reversed())
    }

    private func stretches(for date: String) -> [FocusStretchDTO]? {
        if date == focus.today?.date { return focus.today?.stretches }
        return focus.dayCache[date]?.stretches
    }

    var body: some View {
        NavigationStack {
            Group {
                if activeDays.isEmpty {
                    emptyState
                } else {
                    list
                }
            }
            .background { theme.paper.ignoresSafeArea() }
            .navigationDestination(for: String.self) { DayDetailView(date: $0) }
        }
    }

    private var list: some View {
        List {
            if focus.isOffline {
                OfflineBanner(lastUpdated: focus.lastUpdated)
                    .listRowBackground(Color.clear)
            }
            ForEach(activeDays) { day in
                Section {
                    sessionRows(for: day)
                } header: {
                    HistoryDayHeader(day: day, goalSeconds: goalSeconds)
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
    }

    @ViewBuilder private func sessionRows(for day: FocusDayDTO) -> some View {
        if let sts = stretches(for: day.date) {
            if sts.isEmpty {
                Text("Keine Schreibphasen.")
                    .font(.caption).foregroundStyle(theme.sepia)
                    .listRowBackground(theme.paperTop)
            } else {
                ForEach(sts) { s in
                    NavigationLink(value: day.date) { SessionRow(stretch: s) }
                        .listRowBackground(theme.paperTop)
                }
            }
        } else {
            Text("Laden …")
                .font(.caption).foregroundStyle(theme.sepia)
                .listRowBackground(theme.paperTop)
                .task { await focus.loadDay(day.date) }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "list.bullet.rectangle")
                .font(.largeTitle).foregroundStyle(theme.mutedInk)
            Text("Deine Sessions erscheinen hier, sobald die erste Aufnahme läuft.")
                .font(.subheadline).foregroundStyle(theme.sepia)
                .multilineTextAlignment(.center).padding(.horizontal, 40)
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}

private struct HistoryDayHeader: View {
    let day: FocusDayDTO
    let goalSeconds: Double
    @Environment(\.scrybe) private var theme

    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }

    var body: some View {
        HStack(spacing: 8) {
            Text(DateFormatting.dayMonth(iso: day.date))
                .font(.subheadline.weight(.semibold)).foregroundStyle(theme.ink)
            if day.isToday {
                Text("HEUTE").font(.caption2.weight(.medium)).tracking(1)
                    .foregroundStyle(theme.sepia)
            }
            Spacer()
            Text(TimeFormatting.human(seconds: day.writingSeconds))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(isMet ? theme.success : theme.sepia)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

private struct SessionRow: View {
    let stretch: FocusStretchDTO
    @Environment(\.scrybe) private var theme

    private var start: String { StretchClock.hhmm(stretch.startMs) }
    private var duration: String { TimeFormatting.human(seconds: stretch.durationS) }

    var body: some View {
        HStack(spacing: 8) {
            Text(start).monospacedDigit().font(.callout).foregroundStyle(theme.ink)
            Spacer()
            MiniSparkline(samples: stretch.intensitySamples)
            Text(duration).font(.callout).foregroundStyle(theme.sepia)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(start), \(duration)")
    }
}

#Preview {
    HistoryView().scrybeTheme()
}
