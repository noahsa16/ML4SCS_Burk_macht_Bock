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
        if !store.all.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Text("Bestiarium")
                    .font(.headline)
                    .foregroundStyle(theme.ink)
                LazyVGrid(columns: columns, spacing: 16) {
                    ForEach(store.all) { entry in
                        CreatureCell(entry: entry)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 24)
        }
    }
}

private struct CreatureCell: View {
    let entry: BestiaryEntry
    @Environment(\.scrybe) private var theme

    private var speciesName: String {
        Marginalia.names.indices.contains(entry.speciesId) ? Marginalia.names[entry.speciesId] : ""
    }

    /// Blank for the creature still in progress — it has no completion date
    /// yet, and the reserved caption line keeps every cell in the row the
    /// same height whether or not it has one.
    private var completedLabel: String {
        entry.completedMs.map { DateFormatting.dayMonth(ms: $0) } ?? ""
    }

    var body: some View {
        VStack(spacing: 8) {
            CreatureCanvas(speciesId: entry.speciesId, strokesDrawn: entry.strokesDrawn)
                .aspectRatio(1, contentMode: .fit)
                .padding(12)
                .scrybeSurface(cornerRadius: 16)
            Text(completedLabel)
                .font(.caption)
                .foregroundStyle(theme.secondaryInk)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
    }

    private var accessibilityLabel: String {
        guard let completedMs = entry.completedMs else { return "\(speciesName), im Entstehen" }
        return "\(speciesName), fertig am \(DateFormatting.dayMonth(ms: completedMs))"
    }
}

/// Draws a creature's first `strokesDrawn` strokes, scaled into the cell.
///
/// Density-matched line width, so a species traced in two hundred strokes
/// gets a finer pen than one traced in twenty — at a fixed width the detail
/// of a dense creature would weld into a blob (mirrors
/// `tools/render_marginalia.swift`'s renderer).
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
            let lineWidth = max(0.9, 2.6 - CGFloat(strokes.count) * 0.03)
            for path in strokes.prefix(strokesDrawn) {
                context.stroke(path, with: .color(theme.secondaryInk), lineWidth: lineWidth)
            }
        }
    }
}

#Preview {
    BestiaryView().scrybeTheme()
}
