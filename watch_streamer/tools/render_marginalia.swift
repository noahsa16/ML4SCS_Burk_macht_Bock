import AppKit
import SwiftUI

// Renders every marginal creature as a labelled grid so they can be looked at
// rather than reasoned about.
//
// Build together with the source it draws — a standalone program cannot import
// the app module:
//
//   cd watch_streamer && swiftc -O -o /tmp/render \
//       tools/render_marginalia.swift \
//       WatchStreamer/Scrybe/Components/Marginalia.swift && /tmp/render
//
// Pass a species index to render that one alone at a larger size:
//   /tmp/render 3

@main
enum RenderMarginalia {
    static func main() {
        let cell: CGFloat = 200
        let label: CGFloat = 26
        let paper = NSColor(calibratedRed: 0.969, green: 0.957, blue: 0.918, alpha: 1)
        let ink = NSColor(calibratedRed: 0.122, green: 0.165, blue: 0.239, alpha: 1)
        let rule = NSColor(calibratedRed: 0.878, green: 0.855, blue: 0.804, alpha: 1)

        let single = CommandLine.arguments.dropFirst().first.flatMap(Int.init)
        let indices = single.map { [$0] } ?? Array(0..<Marginalia.names.count)
        let columns = single == nil ? 4 : 1
        let scale: CGFloat = single == nil ? 1 : 2
        let rows = Int(ceil(Double(indices.count) / Double(columns)))

        let width = Int(CGFloat(columns) * cell * scale)
        let height = Int(CGFloat(rows) * (cell + label) * scale)

        let rep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!

        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let ctx = NSGraphicsContext.current!.cgContext

        ctx.setFillColor(paper.cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

        for (slot, species) in indices.enumerated() {
            let column = slot % columns
            let row = slot / columns
            let originX = CGFloat(column) * cell * scale
            // Why measured from the top: AppKit's origin is bottom-left, and reading a
            // grid in the order it was authored is worth the arithmetic.
            let originY = CGFloat(height) - CGFloat(row + 1) * (cell + label) * scale

            ctx.saveGState()
            ctx.translateBy(x: originX, y: originY + label * scale)

            // A baseline, so a creature that floats or sinks is obvious.
            ctx.setStrokeColor(rule.cgColor)
            ctx.setLineWidth(1)
            ctx.move(to: CGPoint(x: 12 * scale, y: 18 * scale))
            ctx.addLine(to: CGPoint(x: (cell - 12) * scale, y: 18 * scale))
            ctx.strokePath()

            // Why the flip: SwiftUI counts y downward, AppKit counts it up. Without
            // this every creature is drawn mirrored against how the app shows it, and
            // inspection would approve the wrong image.
            ctx.translateBy(x: 0, y: cell * scale)
            ctx.scaleBy(x: 1, y: -1)
            let fit = (cell * scale) / 100
            ctx.scaleBy(x: fit, y: fit)

            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            let all = Marginalia.strokes(forSpecies: species)
            // A detailed creature needs a finer pen. At nine strokes a heavy
            // line reads as confident; at seventy the same line welds the
            // detail into blobs, so the weight follows the stroke count.
            let base = max(0.9, 2.6 - CGFloat(all.count) * 0.03)
            for (index, stroke) in all.enumerated() {
                // Later strokes sit slightly finer, the way a pen loses ink.
                ctx.setLineWidth(base - min(base * 0.3, CGFloat(index) * 0.01))
                ctx.addPath(stroke.cgPath)
                ctx.strokePath()
            }
            ctx.restoreGState()

            let name = "\(species)  \(Marginalia.names[species])"
            let strokes = Marginalia.strokeCount(forSpecies: species)
            let text = "\(name)  ·  \(strokes) Striche" as NSString
            text.draw(at: NSPoint(x: originX + 12 * scale, y: originY + 6 * scale),
                      withAttributes: [
                        .font: NSFont.systemFont(ofSize: 11 * scale),
                        .foregroundColor: NSColor(calibratedWhite: 0.35, alpha: 1)])
        }

        NSGraphicsContext.restoreGraphicsState()

        let out = URL(fileURLWithPath: "/tmp/marginalia.png")
        try! rep.representation(using: .png, properties: [:])!.write(to: out)
        print("wrote \(out.path)  (\(width)x\(height), \(indices.count) species)")
    }
}
