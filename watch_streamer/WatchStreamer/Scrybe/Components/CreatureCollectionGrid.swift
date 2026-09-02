import SwiftUI

/// The collected creatures as a two-column grid of ruled cards: the drawing,
/// its name in italic serif, and one tracked caption underneath — the date it
/// was finished, or how far along it is. Shared by the profile page, which
/// shows the first few, and the gallery, which shows them all.
struct CreatureCollectionGrid: View {
    let entries: [BestiaryEntry]

    private let columns = [
        GridItem(.flexible(), spacing: 16),
        GridItem(.flexible(), spacing: 16),
    ]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 16) {
            ForEach(entries) { entry in
                CreatureCard(entry: entry)
            }
        }
    }
}

struct CreatureCard: View {
    let entry: BestiaryEntry
    @Environment(\.scrybe) private var theme

    private var speciesName: String { Marginalia.name(forSpecies: entry.speciesId) }
    private var percentText: String {
        (entry.writingSeconds / Bestiary.secondsPerCreature)
            .formatted(.percent.precision(.fractionLength(0))
                .locale(ScrybeSettings.localeOverride ?? .current))
    }

    var body: some View {
        VStack(spacing: 12) {
            CreatureCanvas(speciesId: entry.speciesId,
                           strokesDrawn: entry.strokesDrawn,
                           showsUnderdrawing: !entry.isComplete)
                .frame(height: 88)
                .frame(maxWidth: .infinity)
                .opacity(entry.isComplete ? 1 : 0.85)
            VStack(spacing: 6) {
                Text(speciesName)
                    .font(.system(.callout, design: .serif))
                    .italic()
                    .foregroundStyle(theme.ink)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
                caption
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 20)
        .frame(maxWidth: .infinity)
        .frame(minHeight: 190)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(theme.sepia.opacity(entry.isComplete ? 0.55 : 0.3), lineWidth: 1))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
    }

    @ViewBuilder private var caption: some View {
        if let completedMs = entry.completedMs {
            Text(DateFormatting.dayMonth(ms: completedMs)).scrybeCaption()
        } else {
            Text("In Arbeit · \(percentText)").scrybeCaption()
        }
    }

    /// `LocalizedStringKey`, not `String`: binding the `StringProtocol`
    /// overload of `.accessibilityLabel` would make these two phrasings
    /// untranslatable regardless of what the catalog holds. Each branch's
    /// interpolation pattern (`"%@, im Entstehen"` / `"%@, fertig am %@"`)
    /// has its own entry in `Localizable.xcstrings`.
    private var accessibilityLabel: LocalizedStringKey {
        if let completedMs = entry.completedMs {
            return "\(speciesName), fertig am \(DateFormatting.dayMonth(ms: completedMs))"
        }
        return "\(speciesName), im Entstehen"
    }
}

/// The dotted card that stands where the first creature will appear.
struct EmptyCreatureCard: View {
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(spacing: 12) {
            EmptyPageVignette(side: 56)
            Text("Deine erste Kreatur entsteht mit der ersten Sitzung.")
                .font(.system(.footnote, design: .serif))
                .italic()
                .foregroundStyle(theme.secondaryInk)
                .multilineTextAlignment(.center)
        }
        .padding(20)
        .frame(maxWidth: .infinity)
        .frame(minHeight: 150)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(theme.sepia.opacity(0.35), style: StrokeStyle(lineWidth: 1, dash: [4, 5])))
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    let now = Int64(Date().timeIntervalSince1970 * 1000)
    let entries = [
        BestiaryEntry(ordinal: 3, speciesId: 0, startedMs: now, strokesTotal: 40,
                      writingSeconds: 810),
        BestiaryEntry(ordinal: 2, speciesId: 4, startedMs: now, strokesTotal: 60,
                      writingSeconds: 1800, completedMs: now),
        BestiaryEntry(ordinal: 1, speciesId: 6, startedMs: now, strokesTotal: 60,
                      writingSeconds: 1800, completedMs: now),
    ]
    return ScrollView {
        VStack(spacing: 24) {
            CreatureCollectionGrid(entries: entries)
            EmptyCreatureCard()
        }
        .padding(24)
    }
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
