import AppKit

// Renders a creature being drawn, stroke by stroke, as a PNG sequence with a
// TRANSPARENT background — the animated counterpart to render_marginalia.swift's
// still grid, meant to be composited into a product video.
//
// Build together with the sources it draws (a standalone program cannot import
// the app module):
//
//   cd watch_streamer && swiftc -O -o /tmp/rendercreature \
//       tools/render_creature_frames.swift \
//       WatchStreamer/Scrybe/Components/Marginalia.swift \
//       WatchStreamer/Scrybe/Components/CreaturePen.swift
//
//   /tmp/rendercreature --out /tmp/creatures            # all eight
//   /tmp/rendercreature --species 3 --out /tmp/creature3
//
// Then per creature:
//   ffmpeg -framerate 60 -i /tmp/creatures/3/frame_%04d.png \
//       -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le creature3.mov

struct Options {
    var size: CGFloat = 1024
    var fps: Int = 60
    var duration: Double = 6
    var holdSeconds: Double = 1.5
    var species: Int? = nil
    var dark = false
    var inkHex: UInt32? = nil
    /// Draw every stroke fully opaque instead of tapering hairlines with
    /// `CreaturePen.opacity`. Semi-transparent white does not survive a
    /// chroma key, so a greenscreen render wants a flat tone.
    var flatTone = false
    var out = "creature_frames"
}

/// Total arc length of a path, in the coordinate space the path is authored in.
/// CoreGraphics has no length API, and the length is what lets a stroke be
/// drawn *partially* — see `draw(stroke:fraction:)`.
func arcLength(_ path: CGPath) -> CGFloat {
    var total: CGFloat = 0
    var current = CGPoint.zero
    var start = CGPoint.zero

    func distance(_ a: CGPoint, _ b: CGPoint) -> CGFloat {
        hypot(b.x - a.x, b.y - a.y)
    }

    // Curves are subdivided rather than solved: 16 segments is well past the
    // point where more changes the drawn result at these stroke lengths.
    func flatten(_ points: [CGPoint], from p0: CGPoint) -> CGFloat {
        let steps = 16
        var previous = p0
        var length: CGFloat = 0
        for step in 1...steps {
            let t = CGFloat(step) / CGFloat(steps)
            let point: CGPoint
            if points.count == 3 {
                let mt = 1 - t
                point = CGPoint(
                    x: mt * mt * mt * p0.x + 3 * mt * mt * t * points[0].x
                        + 3 * mt * t * t * points[1].x + t * t * t * points[2].x,
                    y: mt * mt * mt * p0.y + 3 * mt * mt * t * points[0].y
                        + 3 * mt * t * t * points[1].y + t * t * t * points[2].y)
            } else {
                let mt = 1 - t
                point = CGPoint(
                    x: mt * mt * p0.x + 2 * mt * t * points[0].x + t * t * points[1].x,
                    y: mt * mt * p0.y + 2 * mt * t * points[0].y + t * t * points[1].y)
            }
            length += distance(previous, point)
            previous = point
        }
        return length
    }

    path.applyWithBlock { element in
        let e = element.pointee
        switch e.type {
        case .moveToPoint:
            current = e.points[0]
            start = current
        case .addLineToPoint:
            total += distance(current, e.points[0])
            current = e.points[0]
        case .addQuadCurveToPoint:
            total += flatten([e.points[0], e.points[1]], from: current)
            current = e.points[1]
        case .addCurveToPoint:
            total += flatten([e.points[0], e.points[1], e.points[2]], from: current)
            current = e.points[2]
        case .closeSubpath:
            total += distance(current, start)
            current = start
        @unknown default:
            break
        }
    }
    return total
}

func parse() -> Options {
    var o = Options()
    var args = Array(CommandLine.arguments.dropFirst())
    while let flag = args.first {
        args.removeFirst()
        func value() -> String { args.isEmpty ? "" : args.removeFirst() }
        switch flag {
        case "--size": o.size = CGFloat(Double(value()) ?? 1024)
        case "--fps": o.fps = Int(value()) ?? 60
        case "--duration": o.duration = Double(value()) ?? 6
        case "--hold": o.holdSeconds = Double(value()) ?? 1.5
        case "--species": o.species = Int(value())
        case "--dark": o.dark = true
        case "--flat-tone": o.flatTone = true
        case "--ink": o.inkHex = UInt32(value().replacingOccurrences(of: "#", with: ""), radix: 16)
        case "--out": o.out = value()
        default:
            FileHandle.standardError.write("unknown flag \(flag)\n".data(using: .utf8)!)
            exit(2)
        }
    }
    return o
}

@main
enum RenderCreatureFrames {
    static func main() {
        let o = parse()
        // The app draws a creature in `secondaryInk`; keeping that here means the
        // clip matches the screen it was lifted from.
        let hex = o.inkHex ?? (o.dark ? 0xC9A85A : 0x76602C)
        let ink = NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                          green: CGFloat((hex >> 8) & 0xFF) / 255,
                          blue: CGFloat(hex & 0xFF) / 255,
                          alpha: 1)

        let species = o.species.map { [$0] } ?? Array(0..<Marginalia.names.count)
        for id in species {
            render(species: id, ink: ink, options: o)
        }
    }

    static func render(species: Int, ink: NSColor, options o: Options) {
        let strokes = Marginalia.strokes(forSpecies: species)
        guard !strokes.isEmpty else { return }
        let heaviest = strokes.map(\.width).max() ?? 1
        let lengths = strokes.map { arcLength($0.path.cgPath) }

        let directory = URL(fileURLWithPath: o.out)
            .appendingPathComponent(String(format: "%d_%@", species,
                                           Marginalia.names[species]
                                            .replacingOccurrences(of: " ", with: "_")))
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let drawFrames = max(1, Int((o.duration * Double(o.fps)).rounded()))
        let holdFrames = max(0, Int((o.holdSeconds * Double(o.fps)).rounded()))
        let side = Int(o.size)

        for frame in 0..<(drawFrames + holdFrames) {
            let progress = frame < drawFrames
                ? Double(frame + 1) / Double(drawFrames)
                : 1
            let cursor = progress * Double(strokes.count)

            let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side,
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
            let ctx = NSGraphicsContext.current!.cgContext
            ctx.clear(CGRect(x: 0, y: 0, width: o.size, height: o.size))

            // Why the flip: the paths are authored in SwiftUI's y-down space,
            // AppKit counts y up. Without it every creature comes out mirrored.
            ctx.translateBy(x: 0, y: o.size)
            ctx.scaleBy(x: 1, y: -1)
            ctx.scaleBy(x: o.size / 100, y: o.size / 100)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)

            let complete = Int(cursor)
            for (i, stroke) in strokes.enumerated() {
                let fraction: Double
                if i < complete { fraction = 1 }
                else if i == complete { fraction = cursor - Double(complete) }
                else { break }
                guard fraction > 0 else { continue }

                let tone = o.flatTone
                    ? 1
                    : CreaturePen.opacity(stroke.width, reference: heaviest)
                ctx.setStrokeColor(ink.withAlphaComponent(tone).cgColor)
                ctx.setLineWidth(CreaturePen.lineWidth(stroke.width, side: o.size))
                if fraction < 1 {
                    // A dash whose first segment is the drawn part and whose gap
                    // outruns the path leaves exactly the leading fraction inked,
                    // which is how a stroke appears to be drawn rather than to pop.
                    let length = lengths[i]
                    ctx.setLineDash(phase: 0,
                                    lengths: [length * CGFloat(fraction), length + 1])
                } else {
                    ctx.setLineDash(phase: 0, lengths: [])
                }
                ctx.addPath(stroke.path.cgPath)
                ctx.strokePath()
            }
            ctx.setLineDash(phase: 0, lengths: [])
            NSGraphicsContext.restoreGraphicsState()

            let url = directory.appendingPathComponent(String(format: "frame_%04d.png", frame + 1))
            try! rep.representation(using: .png, properties: [:])!.write(to: url)
        }

        print("\(Marginalia.names[species]): \(drawFrames + holdFrames) frames, "
              + "\(strokes.count) strokes → \(directory.path)")
    }
}
