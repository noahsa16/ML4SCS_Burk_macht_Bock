import SwiftUI

/// Folds 24 hourly writing-seconds buckets into four day-parts — answers
/// "when do I write?". Hatched bars scale to the busiest part, which is the
/// one drawn in the accent.
struct TimeOfDayChart: View {
    let buckets: [FocusHourBucketDTO]
    var barHeight: CGFloat = 110

    @Environment(\.scrybe) private var theme

    private var seconds: [(part: TrendInsights.DayPart, seconds: Double)] {
        TrendInsights.DayPart.allCases.map { ($0, TrendInsights.seconds(for: $0, buckets: buckets)) }
    }
    private var maxSeconds: Double { max(1, seconds.map(\.seconds).max() ?? 1) }

    var body: some View {
        HStack(alignment: .bottom, spacing: 24) {
            ForEach(seconds, id: \.part) { entry in
                let busiest = entry.seconds > 0 && entry.seconds == maxSeconds
                VStack(spacing: 8) {
                    HatchedBar(height: max(4, CGFloat(entry.seconds / maxSeconds) * barHeight),
                               highlighted: busiest,
                               isEmpty: entry.seconds <= 0)
                        .frame(maxWidth: .infinity)
                    Text(label(entry.part))
                        .font(.caption2.weight(busiest ? .semibold : .regular))
                        .textCase(.uppercase)
                        .tracking(1)
                        .foregroundStyle(busiest ? theme.ink : theme.secondaryInk)
                        .frame(height: 14)
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Text(label(entry.part)))
                .accessibilityValue(Text(TimeFormatting.abbreviated(seconds: entry.seconds)))
            }
        }
        .frame(height: barHeight + 26, alignment: .bottom)
        .overlay(alignment: .bottom) {
            Rectangle().fill(theme.hairline).frame(height: 1)
                .padding(.bottom, 24)
        }
    }

    private func label(_ part: TrendInsights.DayPart) -> LocalizedStringKey {
        switch part {
        case .morning: return "Morgen"
        case .noon: return "Mittag"
        case .evening: return "Abend"
        case .night: return "Nacht"
        }
    }
}

#Preview {
    TimeOfDayChart(buckets: (0..<24).map {
        FocusHourBucketDTO(hour: $0, seconds: Double(($0 % 7) * 200))
    })
    .padding(24)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
