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
//       Shared/Marginalia.swift && /tmp/render
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

        let args = Array(CommandLine.arguments.dropFirst())
        // `grow N` shows one creature at the stages a session draws it, which
        // is the only way to judge the mechanic: a creature can look right
        // finished and read as scribble at a third of the way through.
        if args.first == "grow" {
            growth(species: args.dropFirst().first.flatMap(Int.init) ?? 0)
            return
        }
        let single = args.first.flatMap(Int.init)
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

    /// One creature at six points of a session, plus the same at margin size.
    static func growth(species: Int) {
        let strokes = Marginalia.strokes(forSpecies: species)
        let targetMinutes = 25.0
        let stages = [0.08, 0.25, 0.45, 0.65, 0.85, 1.0]

        let cell: CGFloat = 190
        let label: CGFloat = 30
        let small: CGFloat = 64          // roughly the size in a page margin
        let width = Int(cell * CGFloat(stages.count))
        let height = Int(cell + label + small + label)

        let paper = NSColor(calibratedRed: 0.949, green: 0.937, blue: 0.878, alpha: 1)
        let ink = NSColor(calibratedRed: 0.165, green: 0.153, blue: 0.200, alpha: 1)

        let rep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let ctx = NSGraphicsContext.current!.cgContext
        ctx.setFillColor(paper.cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

        func draw(_ count: Int, at origin: CGPoint, side: CGFloat) {
            ctx.saveGState()
            ctx.translateBy(x: origin.x, y: origin.y + side)
            ctx.scaleBy(x: 1, y: -1)
            ctx.scaleBy(x: side / 100, y: side / 100)
            ctx.setStrokeColor(ink.cgColor)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            let base = max(0.9, 2.6 - CGFloat(strokes.count) * 0.03) * (side < 100 ? 1.6 : 1)
            for (i, stroke) in strokes.prefix(count).enumerated() {
                // The newest stroke is still wet, so it sits a shade darker.
                let fresh = i == count - 1 && count < strokes.count
                ctx.setLineWidth(fresh ? base * 1.15 : base)
                ctx.setAlpha(fresh ? 1.0 : 0.92)
                ctx.addPath(stroke.cgPath)
                ctx.strokePath()
            }
            ctx.setAlpha(1)
            ctx.restoreGState()
        }

        for (i, fraction) in stages.enumerated() {
            let count = max(1, Int((Double(strokes.count) * fraction).rounded()))
            let x = CGFloat(i) * cell

            draw(count, at: CGPoint(x: x + 10, y: CGFloat(height) - cell - label), side: cell - 20)
            draw(count, at: CGPoint(x: x + (cell - small) / 2, y: label), side: small)

            let minutes = targetMinutes * fraction
            let top = "\(Int(minutes)) min · \(count)/\(strokes.count)" as NSString
            top.draw(at: NSPoint(x: x + 14, y: CGFloat(height) - cell - label + 6),
                     withAttributes: [.font: NSFont.systemFont(ofSize: 12),
                                      .foregroundColor: NSColor(calibratedWhite: 0.38, alpha: 1)])
        }

        let caption = "oben in voller Groesse, unten wie im Seitenrand" as NSString
        caption.draw(at: NSPoint(x: 14, y: 8),
                     withAttributes: [.font: NSFont.systemFont(ofSize: 12),
                                      .foregroundColor: NSColor(calibratedWhite: 0.5, alpha: 1)])

        NSGraphicsContext.restoreGraphicsState()
        let out = URL(fileURLWithPath: "/tmp/marginalia_growth.png")
        try! rep.representation(using: .png, properties: [:])!.write(to: out)
        print("wrote \(out.path)  (\(strokes.count) strokes over \(Int(targetMinutes)) min)")
    }
}
