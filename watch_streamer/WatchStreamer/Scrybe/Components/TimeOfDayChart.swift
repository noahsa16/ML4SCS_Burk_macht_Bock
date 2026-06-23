import SwiftUI

/// Folds 24 hourly writing-seconds buckets into four day-parts — answers
/// "when do I write?". Bars scale to the busiest part.
struct TimeOfDayChart: View {
    let buckets: [FocusHourBucketDTO]
    @Environment(\.scrybe) private var theme

    private struct Part: Identifiable {
        let id: String
        let label: String
        let hours: Set<Int>
    }

    private let parts: [Part] = [
        Part(id: "morning", label: "Morgen", hours: Set(5..<11)),
        Part(id: "noon", label: "Mittag", hours: Set(11..<17)),
        Part(id: "evening", label: "Abend", hours: Set(17..<23)),
        Part(id: "night", label: "Nacht", hours: [23, 0, 1, 2, 3, 4]),
    ]

    private func seconds(_ part: Part) -> Double {
        buckets.filter { part.hours.contains($0.hour) }.reduce(0) { $0 + $1.seconds }
    }
    private var maxSeconds: Double { max(1, parts.map(seconds).max() ?? 1) }

    var body: some View {
        HStack(alignment: .bottom, spacing: 16) {
            ForEach(parts) { part in
                let secs = seconds(part)
                VStack(spacing: 8) {
                    Capsule()
                        .fill(secs > 0 ? theme.accent : theme.mutedInk)
                        .frame(width: 16, height: max(4, CGFloat(secs / maxSeconds) * 70))
                    Text(LocalizedStringKey(part.label)).font(.caption2).foregroundStyle(theme.sepia)
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(part.label)
                .accessibilityValue(TimeFormatting.human(seconds: secs))
            }
        }
        .frame(height: 70 + 24, alignment: .bottom)
    }
}

#Preview {
    TimeOfDayChart(buckets: (0..<24).map {
        FocusHourBucketDTO(hour: $0, seconds: Double(($0 % 7) * 200))
    })
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
