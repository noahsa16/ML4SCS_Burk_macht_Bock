import SwiftUI

/// The creatures a writer has drawn, one to a margin at a time.
///
/// A creature still in progress shows exactly as far as it has been drawn —
/// no badge, no label, no progress bar. A half-drawn animal already says
/// everything there is to say about it; a percentage next to it would only
/// repeat what the eye can already see.
struct BestiaryView: View {
    @ObservedObject private var store = BestiaryStore.shared
    @Environment(\.scrybe) private var theme

    private let columns = [GridItem(.adaptive(minimum: 96, maximum: 132), spacing: 16)]

    var body: some View {
        if !store.visible.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("Bestiarium")
                    .font(.headline)
                    .foregroundStyle(theme.ink)
                LazyVGrid(columns: columns, spacing: 16) {
                    ForEach(store.visible) { entry in
                        CreatureCell(entry: entry)
                    }
                }
            }
            // No top padding of its own: HistoryView only ever shows this
            // view directly under `days`, whose own `.padding(.bottom, 24)`
            // is already the gap — adding one here would double it.
            .padding(.horizontal, 16)
        }
    }
}

private struct CreatureCell: View {
    let entry: BestiaryEntry
    @Environment(\.scrybe) private var theme

    private var speciesName: String { Marginalia.name(forSpecies: entry.speciesId) }

    var body: some View {
        VStack(spacing: 8) {
            CreatureCanvas(speciesId: entry.speciesId, strokesDrawn: entry.strokesDrawn)
                .aspectRatio(1, contentMode: .fit)
                .padding(12)
                .scrybeSurface(cornerRadius: 16)
            captionRow
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
    }

    /// The completion date once archived, nothing visible while still in
    /// progress — but the row always reserves a full caption line via a
    /// hidden placeholder, rather than trusting an empty string to report
    /// the same height a real one would.
    private var captionRow: some View {
        ZStack {
            Text(" ").hidden()
            if let completedMs = entry.completedMs {
                Text(DateFormatting.dayMonth(ms: completedMs))
            }
        }
        .font(.caption)
        .foregroundStyle(theme.secondaryInk)
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

#Preview {
    BestiaryView().scrybeTheme()
}
