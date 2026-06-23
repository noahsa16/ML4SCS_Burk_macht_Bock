import SwiftUI

/// Tiny writing-intensity polyline for a session row. Samples are mean-proba in
/// [0, 1]; a near-flat high line = steady writing, dips = micro-pauses.
struct MiniSparkline: View {
    let samples: [Double]
    var width: CGFloat = 48
    var height: CGFloat = 18
    @Environment(\.scrybe) private var theme

    var body: some View {
        Path { path in
            let pts = points(in: CGSize(width: width, height: height))
            guard let first = pts.first else { return }
            path.move(to: first)
            for p in pts.dropFirst() { path.addLine(to: p) }
        }
        .stroke(theme.accent,
                style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        .frame(width: width, height: height)
        .accessibilityHidden(true)
    }

    private func points(in size: CGSize) -> [CGPoint] {
        guard !samples.isEmpty else { return [] }
        let vals = samples.count == 1 ? [samples[0], samples[0]] : samples
        let denom = CGFloat(vals.count - 1)
        return vals.enumerated().map { i, v in
            let x = size.width * CGFloat(i) / denom
            let y = size.height * (1 - CGFloat(min(1, max(0, v))))
            return CGPoint(x: x, y: y)
        }
    }
}

#Preview {
    MiniSparkline(samples: [0.2, 0.6, 0.9, 0.85, 0.4, 0.95, 0.7])
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
