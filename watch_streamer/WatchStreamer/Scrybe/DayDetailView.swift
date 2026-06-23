import SwiftUI

struct DayDetailView: View {
    let date: String

    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var day: FocusDayDTO? { focus.history?.days.first { $0.date == date } }
    private var isToday: Bool { day?.isToday == true }
    private var stretches: [FocusStretchDTO] { isToday ? (focus.today?.stretches ?? []) : [] }
    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day?.writingSeconds ?? 0, goalSeconds: goalSeconds).isMet
    }
    private var totalText: String { TimeFormatting.human(seconds: day?.writingSeconds ?? 0) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(totalText)
                    .font(.system(.largeTitle, design: .serif).weight(.semibold))
                    .foregroundStyle(theme.ink)
                    .contentTransition(.numericText())

                if isMet {
                    Label("Tagesziel erreicht", systemImage: "checkmark.seal")
                        .font(.subheadline).foregroundStyle(theme.success)
                }

                if !stretches.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Schreibphasen").font(.headline).foregroundStyle(theme.ink)
                        ForEach(stretches) { s in
                            StretchRow(stretch: s)
                            if s.id != stretches.last?.id {
                                Divider().background(theme.hairline)
                            }
                        }
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .scrybeSurface(cornerRadius: 16)
                } else if !isToday {
                    Text("Schreibphasen im Detail sind für den aktuellen Tag verfügbar.")
                        .font(.footnote).foregroundStyle(theme.sepia)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { theme.paper.ignoresSafeArea() }
        .navigationTitle(date)
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct StretchRow: View {
    let stretch: FocusStretchDTO
    @Environment(\.scrybe) private var theme

    private var start: String { Self.clock(stretch.startMs) }
    private var end: String { Self.clock(stretch.endMs) }
    private var duration: String { TimeFormatting.human(seconds: stretch.durationS) }
    private var a11y: String { "\(start) bis \(end), \(duration)" }

    var body: some View {
        HStack {
            Text(start).monospacedDigit()
            Text("–")
            Text(end).monospacedDigit()
            Spacer()
            Text(duration).foregroundStyle(theme.sepia)
        }
        .font(.callout)
        .foregroundStyle(theme.ink)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(a11y)
    }

    private static func clock(_ ms: Int) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}

#Preview {
    NavigationStack {
        DayDetailView(date: "2026-06-22").scrybeTheme()
    }
}
