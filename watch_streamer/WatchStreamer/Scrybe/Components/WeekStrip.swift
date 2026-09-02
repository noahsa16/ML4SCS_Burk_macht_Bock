import SwiftUI

struct WeekStrip: View {
    let days: [FocusDayDTO]
    let maxSeconds: Double
    var maxBarHeight: CGFloat = 70
    /// The bar drawn in accent. Defaults to today; Heute passes the day it is
    /// paged to, so the strip and the ring above it agree on which day this is.
    var highlightedDate: String? = nil

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ForEach(days) { day in
                DayBar(day: day, maxSeconds: maxSeconds, maxBarHeight: maxBarHeight,
                       highlighted: highlightedDate.map { $0 == day.date } ?? day.isToday)
            }
        }
        .frame(height: maxBarHeight + 24, alignment: .bottom)
    }
}

/// The strip on a card, titled and summed: "Letzte 7 Tage · 18 Min. gesamt".
struct WeekCard: View {
    let days: [FocusDayDTO]
    let maxSeconds: Double
    var highlightedDate: String? = nil
    @Environment(\.scrybe) private var theme

    private var totalSeconds: Double { days.reduce(0) { $0 + $1.writingSeconds } }
    private var totalText: String { TimeFormatting.abbreviated(seconds: totalSeconds) }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .firstTextBaseline) {
                Text("Letzte 7 Tage")
                    .scrybeCaption()
                Spacer()
                Text("\(totalText) gesamt")
                    .font(.subheadline)
                    .foregroundStyle(theme.secondaryInk)
            }
            .accessibilityElement(children: .combine)
            WeekStrip(days: days, maxSeconds: maxSeconds, highlightedDate: highlightedDate)
        }
        .padding(20)
        .frame(maxWidth: .infinity)
        .scrybeSurface(cornerRadius: 20)
    }
}

private struct DayBar: View {
    let day: FocusDayDTO
    let maxSeconds: Double
    let maxBarHeight: CGFloat
    let highlighted: Bool

    @Environment(\.scrybe) private var theme

    private var barHeight: CGFloat {
        guard maxSeconds > 0 else { return 4 }
        return max(4, CGFloat(day.writingSeconds / maxSeconds) * maxBarHeight)
    }

    private var labelColor: Color { highlighted ? theme.ink : theme.secondaryInk }
    private var weekday: String { DateFormatting.weekday(iso: day.date) }
    private var shortWeekday: String { DateFormatting.shortWeekday(iso: day.date) }
    private var voiceLabel: String { day.isToday ? "\(weekday), heute" : weekday }

    var body: some View {
        VStack(spacing: 8) {
            HatchedBar(height: barHeight, highlighted: highlighted,
                       isEmpty: day.writingSeconds <= 0, cornerRadius: 5)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 6)
            Text(shortWeekday)
                .font(.caption2.weight(highlighted ? .semibold : .regular))
                .textCase(.uppercase)
                .tracking(1)
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
    WeekCard(days: days, maxSeconds: 7200)
        .padding(20)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
