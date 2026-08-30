import SwiftUI

struct HistoryView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    // Days with activity, newest first — derived once in the store when the
    // network state changes rather than filtered and reversed on every body
    // pass (see FocusStore.activeDays).
    private var activeDays: [FocusDayDTO] { focus.activeDays }

    private func stretches(for date: String) -> [FocusStretchDTO]? {
        if date == focus.today?.date { return focus.today?.stretches }
        return focus.dayCache[date]?.stretches
    }
    

    var body: some View {
        NavigationStack {
            // One container for both states, so an empty Verlauf can be pulled
            // to refresh — it is exactly the screen a new user waits on.
            InkRefreshScroll(action: { await focus.refreshForPull() }) {
                VStack(spacing: 0) {
                    if activeDays.isEmpty { emptyState } else { days }
                    BestiaryView()
                }
            }
            .background { theme.paper.ignoresSafeArea() }
            .navigationDestination(for: String.self) { DayDetailView(date: $0) }
        }
    }

    // Why a LazyVStack and not a List: the ink pull-to-refresh has to measure
    // the scroll offset of its own container, which a List does not expose.
    // `pinnedViews` keeps the sticky day headers the List gave us for free.
    private var days: some View {
        LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
            if focus.watchUnreachable {
                OfflineBanner(lastUpdated: focus.lastUpdated)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 12)
            }
            ForEach(activeDays) { day in
                Section {
                    sessionRows(for: day)
                } header: {
                    HistoryDayHeader(day: day, goalSeconds: goalSeconds)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(theme.paperTop)
                }
            }
        }
        .padding(.bottom, 24)
    }

    @ViewBuilder private func sessionRows(for day: FocusDayDTO) -> some View {
        if let sts = stretches(for: day.date) {
            if sts.isEmpty {
                Text("Keine Schreibphasen.")
                    .font(.caption).foregroundStyle(theme.secondaryInk)
                    .historyRow()
            } else {
                ForEach(sts) { s in
                    NavigationLink(value: day.date) { SessionRow(stretch: s) }
                        .buttonStyle(.plain)
                        .historyRow()
                }
            }
        } else if case .failed = focus.dayState[day.date] {
            // Why a retry and not just a message: the load is the only path to
            // this day's detail, and it previously failed silently forever.
            Button { Task { await focus.loadDay(day.date, force: true) } } label: {
                HStack(spacing: 8) {
                    Image(systemName: "arrow.clockwise")
                    Text("Nicht geladen — erneut versuchen")
                }
                .font(.caption)
                .foregroundStyle(theme.danger)
            }
            .historyRow()
        } else {
            Text("Laden …")
                .font(.caption).foregroundStyle(theme.secondaryInk)
                .historyRow()
                .task { await focus.loadDay(day.date) }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "list.bullet.rectangle")
                .font(.largeTitle).foregroundStyle(theme.mutedInk)
            Text("Deine Sessions erscheinen hier, sobald die erste Aufnahme läuft.")
                .font(.subheadline).foregroundStyle(theme.secondaryInk)
                .multilineTextAlignment(.center).padding(.horizontal, 40)
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, minHeight: 440)
        .accessibilityElement(children: .combine)
    }
}

/// The row chrome `List` supplied before the ink pull-to-refresh required a
/// plain scroll container: surface, insets and a leading-inset separator.
private struct HistoryRowStyle: ViewModifier {
    @Environment(\.scrybe) private var theme

    func body(content: Content) -> some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(theme.paperTop)
            .overlay(alignment: .bottom) {
                Rectangle().fill(theme.hairline)
                    .frame(height: 1)
                    .padding(.leading, 16)
            }
    }
}

private extension View {
    func historyRow() -> some View { modifier(HistoryRowStyle()) }
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
                    .foregroundStyle(theme.secondaryInk)
            }
            Spacer()
            Text(TimeFormatting.human(seconds: day.writingSeconds))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(isMet ? theme.successInk : theme.secondaryInk)
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
            Text(duration).font(.callout).foregroundStyle(theme.secondaryInk)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(start), \(duration)")
    }
}

#Preview {
    HistoryView().scrybeTheme()
}
