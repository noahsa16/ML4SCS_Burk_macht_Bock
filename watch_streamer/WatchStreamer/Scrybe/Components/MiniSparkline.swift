import SwiftUI

/// Tiny writing-intensity polyline for a session row. Samples are mean-proba in
/// [0, 1]; a near-flat high line = steady writing, dips = micro-pauses.
struct MiniSparkline: View {
    let samples: [Double]
    var width: CGFloat = 48
    var height: CGFloat = 18
    @Environment(\.scrybe) private var theme

    var body: some View {
        SparklineShape(normalised: samples)
            .stroke(theme.accent,
                    style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
            .frame(width: width, height: height)
            // The enclosing row's label already carries start time and
            // duration; a second announcement of the same stretch adds noise.
            .accessibilityHidden(true)
    }
}

#Preview {
    MiniSparkline(samples: [0.2, 0.6, 0.9, 0.85, 0.4, 0.95, 0.7])
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
