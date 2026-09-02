import SwiftUI

/// Days as hatched bars on a baseline, one selectable. Seven days get their
/// weekday under each bar; thirty get a day number every seventh bar so the
/// axis stays legible without a label per bar. A hairline scale on the
/// leading edge names the top and the middle of the bars' range.
struct HatchedBarChart: View {
    let days: [FocusDayDTO]
    let maxSeconds: Double
    /// The bar drawn in the accent. `nil` highlights none.
    var selectedDate: String?
    var barHeight: CGFloat = 150
    var onSelect: ((String) -> Void)? = nil

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var dense: Bool { days.count > 10 }
    private var spacing: CGFloat { dense ? 3 : 10 }
    /// Height of the label row under the baseline.
    private let labelRow: CGFloat = 26

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            scale
            HStack(alignment: .bottom, spacing: spacing) {
                ForEach(Array(days.enumerated()), id: \.element.id) { index, day in
                    column(day, index: index)
                }
            }
        }
        .frame(height: barHeight + labelRow, alignment: .bottom)
        .overlay(alignment: .bottom) {
            // The baseline the bars stand on, drawn under the labels' row so it
            // separates figures from their names the way a ruled page would.
            Rectangle().fill(theme.hairline).frame(height: 1)
                .padding(.bottom, labelRow - 2)
        }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: selectedDate)
    }

    /// The y-axis: a hairline as tall as the tallest possible bar, with the
    /// range's top and middle written beside it in the label's own type.
    private var scale: some View {
        ZStack(alignment: .topTrailing) {
            Rectangle().fill(theme.hairline).frame(width: 1, height: barHeight)
            if maxSeconds > 0 {
                tick(maxSeconds).offset(y: -6)
                tick(maxSeconds / 2).offset(y: barHeight / 2 - 6)
            }
        }
        .frame(height: barHeight, alignment: .top)
        // Ends on the baseline so the two hairlines meet in a corner.
        .padding(.bottom, labelRow - 1)
        .accessibilityHidden(true)
    }

    private func tick(_ seconds: Double) -> some View {
        Text(TimeFormatting.human(seconds: seconds))
            .font(.caption2)
            .foregroundStyle(theme.mutedInk)
            .monospacedDigit()
            .fixedSize()
            .padding(.trailing, 5)
    }

    private func column(_ day: FocusDayDTO, index: Int) -> some View {
        let selected = day.date == selectedDate
        let height = barHeight(for: day)
        return VStack(spacing: 8) {
            HatchedBar(height: height, highlighted: selected,
                       isEmpty: day.writingSeconds <= 0,
                       cornerRadius: dense ? 3 : 7)
                .frame(maxWidth: .infinity)
            label(day, index: index, selected: selected)
        }
        .frame(maxWidth: .infinity, alignment: .bottom)
        .frame(height: barHeight + labelRow, alignment: .bottom)
        .contentShape(Rectangle())
        .onTapGesture { onSelect?(day.date) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(day.isToday
            ? "\(DateFormatting.weekday(iso: day.date)), heute"
            : DateFormatting.dayMonth(iso: day.date)))
        .accessibilityValue(Text(TimeFormatting.abbreviated(seconds: day.writingSeconds)))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    @ViewBuilder
    private func label(_ day: FocusDayDTO, index: Int, selected: Bool) -> some View {
        let text: String = dense
            ? ((days.count - 1 - index) % 7 == 0 ? DateFormatting.dayNumber(iso: day.date) : "")
            : DateFormatting.shortWeekday(iso: day.date)
        Text(text)
            .font(.caption2.weight(selected ? .semibold : .regular))
            .textCase(.uppercase)
            .tracking(dense ? 0 : 1)
            .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
            .lineLimit(1)
            // Why fixedSize: a dense column is narrower than "19.", and the
            // neighbours' label slots are blank, so the text may overhang them
            // instead of being clipped to its own column.
            .fixedSize()
            .frame(height: 14)
            // A dense chart hides most labels; keeping their slot blank rather
            // than absent keeps every column the same height.
            .opacity(text.isEmpty ? 0 : 1)
    }

    private func barHeight(for day: FocusDayDTO) -> CGFloat {
        guard maxSeconds > 0, day.writingSeconds > 0 else { return 4 }
        return max(6, CGFloat(day.writingSeconds / maxSeconds) * barHeight)
    }
}

#Preview {
    let weekdays = ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]
    let seconds: [Double] = [60, 90, 120, 60, 1080, 60, 300]
    let week: [FocusDayDTO] = (0..<7).map { i in
        FocusDayDTO(date: "2026-08-\(24 + i)", weekday: weekdays[i],
                    writingSeconds: seconds[i], isToday: i == 6)
    }
    let month: [FocusDayDTO] = (0..<30).map { i in
        let iso = String(format: "2026-07-%02d", i + 1)
        let value = Double((i * 137) % 900)
        return FocusDayDTO(date: iso, weekday: "", writingSeconds: value, isToday: i == 29)
    }
    return VStack(spacing: 40) {
        HatchedBarChart(days: week, maxSeconds: 1080, selectedDate: "2026-08-30")
        HatchedBarChart(days: month, maxSeconds: 900, selectedDate: "2026-07-30", barHeight: 100)
    }
    .padding(24)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
