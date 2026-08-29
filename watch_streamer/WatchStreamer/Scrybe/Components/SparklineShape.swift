import SwiftUI

/// The polyline both iPhone sparklines draw.
///
/// There were three independent implementations of "scale numbers into a path"
/// — two on iPhone, one on the Watch — and they had drifted: one duplicated a
/// lone sample so it rendered as a flat line, the other drew nothing; one
/// normalised against a fixed 0…1 range, the other against the series maximum.
/// The two iPhone views now share this shape and differ only in how they
/// normalise, which is the part that genuinely differs. The Watch keeps its own
/// copy because it is a separate compilation target.
struct SparklineShape: Shape {
    /// Already normalised to 0…1, in draw order.
    let normalised: [Double]

    func path(in rect: CGRect) -> Path {
        Path { path in
            guard !normalised.isEmpty else { return }
            // A single sample renders as a flat line rather than vanishing:
            // "one reading" and "no readings" must not look the same.
            let values = normalised.count == 1
                ? [normalised[0], normalised[0]]
                : normalised
            let stepX = rect.width / CGFloat(values.count - 1)
            for (i, v) in values.enumerated() {
                let point = CGPoint(x: rect.minX + CGFloat(i) * stepX,
                                    y: rect.maxY - CGFloat(min(1, max(0, v))) * rect.height)
                if i == 0 { path.move(to: point) } else { path.addLine(to: point) }
            }
        }
    }

    /// Scales a series against its own maximum — for unbounded counts.
    static func normalisedByMaximum(_ values: [Int]) -> [Double] {
        let peak = Double(max(values.max() ?? 1, 1))
        return values.map { Double($0) / peak }
    }
}
