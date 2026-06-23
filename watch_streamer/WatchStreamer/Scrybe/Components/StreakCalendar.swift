import SwiftUI

struct StreakCalendar: View {
    let days: [FocusDayDTO]
    let goalSeconds: Double

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 8), count: 7)

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            ForEach(days) { day in
                DayDot(day: day, goalSeconds: goalSeconds)
            }
        }
    }
}

private struct DayDot: View {
    let day: FocusDayDTO
    let goalSeconds: Double

    @Environment(\.scrybe) private var theme

    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }
    private var fill: Color { isMet ? theme.success : theme.mutedInk }
    private var ringWidth: CGFloat { day.isToday ? 2 : 0 }
    private var stateText: String { isMet ? "Ziel erreicht" : "Ziel nicht erreicht" }

    var body: some View {
        Circle()
            .fill(fill)
            .frame(height: 16)
            .overlay(Circle().stroke(theme.accent, lineWidth: ringWidth))
            .accessibilityLabel(day.date)
            .accessibilityValue(stateText)
    }
}

#Preview {
    let days: [FocusDayDTO] = (1...28).map { i in
        let secs: Double = i % 4 == 0 ? 1000 : 8000
        let day = String(format: "%02d", i)
        return FocusDayDTO(date: "2026-06-\(day)", weekday: "x",
                           writingSeconds: secs, isToday: i == 28)
    }
    StreakCalendar(days: days, goalSeconds: 7200)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
