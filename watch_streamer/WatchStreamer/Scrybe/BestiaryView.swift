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

    private var speciesName: String {
        Marginalia.names.indices.contains(entry.speciesId) ? Marginalia.names[entry.speciesId] : ""
    }

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

/// Draws a creature's first `strokesDrawn` strokes, scaled into the cell.
///
/// Density-matched line width, so a species traced in two hundred strokes
/// gets a finer pen than one traced in twenty — at a fixed width the detail
/// of a dense creature would weld into a blob (mirrors
/// `tools/render_marginalia.swift`'s renderer, boost included: below the
/// tool's own 100pt reference size the same line reads too faint, so it's
/// widened back up rather than left to fade with the cell).
private struct CreatureCanvas: View {
    let speciesId: Int
    let strokesDrawn: Int
    @Environment(\.scrybe) private var theme

    var body: some View {
        Canvas { context, size in
            let strokes = Marginalia.strokes(forSpecies: speciesId)
            guard !strokes.isEmpty, strokesDrawn > 0 else { return }
            let side = min(size.width, size.height)
            context.translateBy(x: (size.width - side) / 2, y: (size.height - side) / 2)
            // The line width below is defined in this 100-unit box; scaling
            // the coordinate system rather than the paths lets it shrink
            // with the cell the same way it shrinks with stroke density.
            context.scaleBy(x: side / 100, y: side / 100)
            let base = max(0.9, 2.6 - CGFloat(strokes.count) * 0.03)
            let lineWidth = base * (side < 100 ? 1.6 : 1)
            for path in strokes.prefix(strokesDrawn) {
                context.stroke(path, with: .color(theme.secondaryInk), lineWidth: lineWidth)
            }
        }
    }
}

#Preview {
    BestiaryView().scrybeTheme()
}
