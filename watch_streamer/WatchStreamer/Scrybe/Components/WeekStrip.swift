import SwiftUI

struct WeekStrip: View {
    let days: [FocusDayDTO]
    let maxSeconds: Double
    var maxBarHeight: CGFloat = 70

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ForEach(days) { day in
                DayBar(day: day, maxSeconds: maxSeconds, maxBarHeight: maxBarHeight)
            }
        }
        .frame(height: maxBarHeight + 24, alignment: .bottom)
    }
}

private struct DayBar: View {
    let day: FocusDayDTO
    let maxSeconds: Double
    let maxBarHeight: CGFloat

    @Environment(\.scrybe) private var theme

    private var barHeight: CGFloat {
        guard maxSeconds > 0 else { return 4 }
        return max(4, CGFloat(day.writingSeconds / maxSeconds) * maxBarHeight)
    }

    private var barFill: Color { day.isToday ? theme.accent : theme.mutedInk }
    private var labelColor: Color { day.isToday ? theme.ink : theme.sepia.opacity(0.7) }
    private var voiceLabel: String { day.isToday ? "\(day.weekday), heute" : day.weekday }

    var body: some View {
        VStack(spacing: 8) {
            Capsule()
                .fill(barFill)
                .frame(width: 10, height: barHeight)
            Text(String(day.weekday.prefix(2)))
                .font(.caption2)
                .foregroundStyle(labelColor)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(voiceLabel)
        .accessibilityValue(TimeFormatting.human(seconds: day.writingSeconds))
    }
}

#Preview {
    let weekdays = ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]
    let seconds: [Double] = [3600, 5400, 1200, 7200, 0, 4800, 6420]
    let days = (0..<7).map { i in
        FocusDayDTO(date: "2026-06-\(16 + i)",
                    weekday: weekdays[i],
                    writingSeconds: seconds[i],
                    isToday: i == 6)
    }
    WeekStrip(days: days, maxSeconds: 7200)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
