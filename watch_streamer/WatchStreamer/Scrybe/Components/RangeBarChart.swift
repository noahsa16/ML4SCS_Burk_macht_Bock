import SwiftUI

/// Compact many-day bar chart for the Trends month view (no per-day labels —
/// today highlighted). WeekStrip stays the labelled 7-day variant.
struct RangeBarChart: View {
    let days: [FocusDayDTO]
    let maxSeconds: Double
    var maxBarHeight: CGFloat = 70
    @Environment(\.scrybe) private var theme

    var body: some View {
        HStack(alignment: .bottom, spacing: 4) {
            ForEach(days) { day in
                Capsule()
                    .fill(day.isToday ? theme.accent : theme.mutedInk)
                    .frame(maxWidth: .infinity)
                    .frame(height: barHeight(day))
            }
        }
        .frame(height: maxBarHeight, alignment: .bottom)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Verlauf der letzten \(days.count) Tage")
        // Why a derived value and not just the title: the bars carry total,
        // peak and typical day visually, and a label naming only the range
        // leaves a VoiceOver user with none of it.
        .accessibilityValue(summary)
    }

    private var summary: String {
        let seconds = days.map(\.writingSeconds)
        let total = seconds.reduce(0, +)
        guard total > 0 else { return "Keine Schreibzeit im Zeitraum" }
        let active = seconds.filter { $0 > 0 }
        let average = active.isEmpty ? 0 : total / Double(active.count)
        var parts = [
            "insgesamt \(TimeFormatting.human(seconds: total))",
            "Durchschnitt \(TimeFormatting.human(seconds: average)) pro aktivem Tag",
        ]
        if let peak = days.max(by: { $0.writingSeconds < $1.writingSeconds }),
           peak.writingSeconds > 0 {
            parts.append("Bestwert \(TimeFormatting.human(seconds: peak.writingSeconds)) am \(DateFormatting.dayMonth(iso: peak.date))")
        }
        return parts.joined(separator: ", ")
    }

    private func barHeight(_ day: FocusDayDTO) -> CGFloat {
        guard maxSeconds > 0 else { return 3 }
        return max(3, CGFloat(day.writingSeconds / maxSeconds) * maxBarHeight)
    }
}

#Preview {
    let days = (0..<30).map { i in
        FocusDayDTO(date: "2026-06-\(i + 1)", weekday: "Mon",
                    writingSeconds: Double((i * 137) % 5000), isToday: i == 29)
    }
    return RangeBarChart(days: days, maxSeconds: 5000)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
