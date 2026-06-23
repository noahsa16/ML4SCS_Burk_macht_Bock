import SwiftUI

/// Larger writing-intensity curve for the Day-Detail: filled area + line, with a
/// dashed 0.5 line marking the writing-vs-pause threshold.
struct IntensityCurve: View {
    let samples: [Double]
    var height: CGFloat = 120
    @Environment(\.scrybe) private var theme

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            let pts = points(in: size)
            ZStack {
                if pts.count > 1 {
                    area(pts, in: size).fill(theme.accent.opacity(0.15))
                    line(pts).stroke(theme.accent,
                                     style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                }
                // Writing/pause threshold (proba 0.5).
                Path { p in
                    let y = size.height * 0.5
                    p.move(to: CGPoint(x: 0, y: y))
                    p.addLine(to: CGPoint(x: size.width, y: y))
                }
                .stroke(theme.hairline, style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
            }
        }
        .frame(height: height)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Schreibintensität über die Session")
    }

    private func points(in size: CGSize) -> [CGPoint] {
        guard !samples.isEmpty else { return [] }
        let vals = samples.count == 1 ? [samples[0], samples[0]] : samples
        let denom = CGFloat(vals.count - 1)
        return vals.enumerated().map { i, v in
            CGPoint(x: size.width * CGFloat(i) / denom,
                    y: size.height * (1 - CGFloat(min(1, max(0, v)))))
        }
    }

    private func line(_ pts: [CGPoint]) -> Path {
        Path { p in
            guard let first = pts.first else { return }
            p.move(to: first)
            for pt in pts.dropFirst() { p.addLine(to: pt) }
        }
    }

    private func area(_ pts: [CGPoint], in size: CGSize) -> Path {
        Path { p in
            guard let first = pts.first, let last = pts.last else { return }
            p.move(to: CGPoint(x: first.x, y: size.height))
            p.addLine(to: first)
            for pt in pts.dropFirst() { p.addLine(to: pt) }
            p.addLine(to: CGPoint(x: last.x, y: size.height))
            p.closeSubpath()
        }
    }
}

#Preview {
    IntensityCurve(samples: [0.1, 0.5, 0.9, 0.8, 0.3, 0.95, 0.9, 0.6, 0.85])
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
