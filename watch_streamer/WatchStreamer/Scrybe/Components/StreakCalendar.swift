import SwiftUI

/// The last seven days as a row of lettered circles: filled where the daily
/// goal was met, ruled in the accent on today, a hairline otherwise. Reads
/// left to right like a week on a calendar page.
struct StreakCalendar: View {
    let days: [FocusDayDTO]
    let goalSeconds: Double

    var body: some View {
        HStack(spacing: 0) {
            ForEach(days) { day in
                DayMark(day: day, goalSeconds: goalSeconds)
                    .frame(maxWidth: .infinity)
            }
        }
    }
}

private struct DayMark: View {
    let day: FocusDayDTO
    let goalSeconds: Double

    @Environment(\.scrybe) private var theme

    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }
    private var wrote: Bool { day.writingSeconds > 0 }
    private var stateText: LocalizedStringKey {
        isMet ? "Ziel erreicht" : (wrote ? "Geschrieben, Ziel offen" : "Nicht geschrieben")
    }

    var body: some View {
        Text(DateFormatting.narrowWeekday(iso: day.date))
            .font(.system(.footnote, design: .serif).weight(isMet ? .semibold : .regular))
            .foregroundStyle(isMet || day.isToday ? theme.ink : theme.secondaryInk)
            .frame(width: 40, height: 40)
            .background {
                Circle().fill(isMet ? theme.wash(theme.accent) : Color.clear)
            }
            .overlay {
                Circle().stroke(
                    day.isToday ? theme.accent : (isMet ? theme.accent.opacity(0.5) : theme.hairline),
                    lineWidth: day.isToday ? 1.5 : 1)
            }
            // A small hatched tick under a day that was written on but fell
            // short of the goal: effort shown without claiming the goal.
            .overlay(alignment: .bottom) {
                if wrote && !isMet {
                    Capsule().fill(theme.secondaryInk.opacity(0.6))
                        .frame(width: 10, height: 2)
                        .offset(y: 5)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text(day.isToday
                ? "\(DateFormatting.weekday(iso: day.date)), heute"
                : DateFormatting.dayMonth(iso: day.date)))
            .accessibilityValue(Text(stateText))
    }
}

#Preview {
    let days: [FocusDayDTO] = (24...30).map { i in
        let secs: Double = i % 3 == 0 ? 8000 : (i % 2 == 0 ? 600 : 0)
        return FocusDayDTO(date: "2026-08-\(i)", weekday: "x",
                           writingSeconds: secs, isToday: i == 30)
    }
    return StreakCalendar(days: days, goalSeconds: 7200)
        .padding(24)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
