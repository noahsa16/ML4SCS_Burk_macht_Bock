import SwiftUI

/// The creature in a dotted circle on a faint sepia wash — the one way the
/// focus tab shows the animal, whether it is waiting to be drawn, growing
/// during a session, or finished on the closing page.
///
/// Sizes to the frame it is given: the wash and the dashed ring are drawn
/// from the actual side, so the same view serves the 200 pt medallion on the
/// ready page and the near-full-width one over a running session's page.
struct CreatureVignette: View {
    let speciesId: Int
    let strokesDrawn: Int

    @Environment(\.scrybe) private var theme

    var body: some View {
        GeometryReader { geo in
            let side = min(geo.size.width, geo.size.height)
            ZStack {
                Circle()
                    .fill(RadialGradient(colors: [theme.wash(theme.sepia), .clear],
                                         center: .center, startRadius: 0,
                                         endRadius: side / 2))
                Circle()
                    .stroke(theme.sepia.opacity(0.45),
                            style: StrokeStyle(lineWidth: 1, dash: [1.5, 5]))
                CreatureCanvas(speciesId: speciesId, strokesDrawn: strokesDrawn)
                    .padding(side * 0.09)
            }
            .frame(width: side, height: side)
            .position(x: geo.size.width / 2, y: geo.size.height / 2)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

#Preview {
    VStack(spacing: 24) {
        CreatureVignette(speciesId: 0, strokesDrawn: 12)
            .frame(width: 200, height: 200)
        CreatureVignette(speciesId: 2, strokesDrawn: 40)
            .frame(maxWidth: 320)
    }
    .padding(24)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
