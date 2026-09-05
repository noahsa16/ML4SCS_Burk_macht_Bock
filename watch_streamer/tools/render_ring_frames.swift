import AppKit

// Renders the Scrybe activity ring filling up as a PNG sequence with a
// TRANSPARENT background, so the ring can be composited into a product video
// without masking a screen recording.
//
// Build and run (no app sources needed — the ring is redrawn here from the
// same palette and geometry as InkRing.swift):
//
//   cd watch_streamer && swiftc -O -o /tmp/renderring tools/render_ring_frames.swift \
//       && /tmp/renderring --out /tmp/ring_frames
//
// Then assemble. ProRes 4444 keeps the alpha channel (Final Cut, Premiere,
// Resolve, After Effects all read it):
//
//   ffmpeg -framerate 60 -i /tmp/ring_frames/ring_%04d.png \
//       -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le ring.mov
//
// A WebM with alpha for the web instead:
//
//   ffmpeg -framerate 60 -i /tmp/ring_frames/ring_%04d.png \
//       -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 24 ring.webm

struct Options {
    var size: CGFloat = 1024
    var lineWidth: CGFloat = 68
    var fps: Int = 60
    var duration: Double = 4
    var holdSeconds: Double = 1
    var from: Double = 0
    var to: Double = 1
    var goalSeconds: Double = 2 * 3600
    var easing = "inout"
    var dark = false
    var ringOnly = false
    /// Explicit colours override the app palette, for a clip that has to sit in
    /// a video rather than match the screen it came from.
    var trackHex: UInt32? = nil
    var fillHex: UInt32? = nil
    var textHex: UInt32? = nil
    /// Opaque backdrop. Rendering the ring straight onto it — rather than
    /// overlaying a transparent frame afterwards — lets the antialiased edge
    /// blend against the final colour, which is what a chroma key needs.
    var bgHex: UInt32? = nil
    var out = "ring_frames"
}

enum Palette {
    static func colors(dark: Bool) -> (ink: NSColor, accent: NSColor, goal: NSColor) {
        dark
            ? (hex(0xF2ECE0), hex(0x8C8FD6), hex(0xE07A50))
            : (hex(0x2A2733), hex(0x3B3A6B), hex(0xC25B3A))
    }

    static func rgb(_ v: UInt32) -> NSColor { hex(v) }

    private static func hex(_ v: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((v >> 16) & 0xFF) / 255,
                green: CGFloat((v >> 8) & 0xFF) / 255,
                blue: CGFloat(v & 0xFF) / 255,
                alpha: 1)
    }
}

func ease(_ t: Double, _ kind: String) -> Double {
    let t = min(max(t, 0), 1)
    switch kind {
    case "linear": return t
    case "out": return 1 - pow(1 - t, 3)
    case "in": return t * t * t
    default: return t < 0.5 ? 4 * t * t * t : 1 - pow(-2 * t + 2, 3) / 2
    }
}

/// "2 Std." for a whole-hour goal, "2:30 Std." otherwise — a goal of exactly
/// two hours should not read as a stopwatch.
func goalLabel(seconds: Double) -> String {
    let minutes = Int(max(0, seconds)) / 60
    return minutes % 60 == 0 ? "\(minutes / 60) Std." : "\(clock(seconds: seconds)) Std."
}

func clock(seconds: Double) -> String {
    let total = Int(max(0, seconds)) / 60
    return "\(total / 60):\(String(format: "%02d", total % 60))"
}

/// Serif, monospaced digits — the same two properties the in-app centre figure
/// relies on. Without monospacing the number jitters horizontally as it counts.
func serifFont(size: CGFloat) -> NSFont {
    let base = NSFont.systemFont(ofSize: size, weight: .regular)
    let descriptor = base.fontDescriptor
        .withDesign(.serif)?
        .addingAttributes([
            .featureSettings: [[
                NSFontDescriptor.FeatureKey.typeIdentifier: kNumberSpacingType,
                NSFontDescriptor.FeatureKey.selectorIdentifier: kMonospacedNumbersSelector,
            ]],
        ]) ?? base.fontDescriptor
    return NSFont(descriptor: descriptor, size: size) ?? base
}

func parse() -> Options {
    var o = Options()
    var args = Array(CommandLine.arguments.dropFirst())
    while let flag = args.first {
        args.removeFirst()
        func value() -> String { args.isEmpty ? "" : args.removeFirst() }
        switch flag {
        case "--size": o.size = CGFloat(Double(value()) ?? 1024)
        case "--line-width": o.lineWidth = CGFloat(Double(value()) ?? 68)
        case "--fps": o.fps = Int(value()) ?? 60
        case "--duration": o.duration = Double(value()) ?? 4
        case "--hold": o.holdSeconds = Double(value()) ?? 1
        case "--from": o.from = Double(value()) ?? 0
        case "--to": o.to = Double(value()) ?? 1
        case "--goal-minutes": o.goalSeconds = (Double(value()) ?? 120) * 60
        case "--ease": o.easing = value()
        case "--dark": o.dark = true
        case "--ring-only": o.ringOnly = true
        case "--track": o.trackHex = UInt32(value().replacingOccurrences(of: "#", with: ""), radix: 16)
        case "--fill": o.fillHex = UInt32(value().replacingOccurrences(of: "#", with: ""), radix: 16)
        case "--text": o.textHex = UInt32(value().replacingOccurrences(of: "#", with: ""), radix: 16)
        case "--bg": o.bgHex = UInt32(value().replacingOccurrences(of: "#", with: ""), radix: 16)
        case "--out": o.out = value()
        default:
            FileHandle.standardError.write("unknown flag \(flag)\n".data(using: .utf8)!)
            exit(2)
        }
    }
    return o
}

func render(_ o: Options, fraction: Double) -> NSBitmapImageRep {
    let side = Int(o.size)
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!

    NSGraphicsContext.saveGraphicsState()
    defer { NSGraphicsContext.restoreGraphicsState() }
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext
    // No background fill: every pixel the ring does not cover stays fully
    // transparent, which is the whole point of this renderer.
    ctx.clear(CGRect(x: 0, y: 0, width: o.size, height: o.size))
    if let bg = o.bgHex {
        ctx.setFillColor(Palette.rgb(bg).cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: o.size, height: o.size))
    }

    let (paletteInk, paletteAccent, goal) = Palette.colors(dark: o.dark)
    let ink = o.textHex.map(Palette.rgb) ?? paletteInk
    let accent = o.fillHex.map(Palette.rgb) ?? paletteAccent
    // A track given explicitly is drawn solid: the palette's 10 %-of-ink track
    // is nearly transparent and would pick up the backdrop under a key.
    let track = o.trackHex.map(Palette.rgb) ?? paletteInk.withAlphaComponent(0.10)
    let center = CGPoint(x: o.size / 2, y: o.size / 2)
    // Why the extra inset: the round line cap overshoots the stroke centre by
    // half the line width, so a radius that merely fits the stroke clips the
    // cap at the top of the canvas.
    let radius = (o.size - o.lineWidth) / 2 - o.size * 0.02
    let met = fraction >= 1
    let clamped = min(max(fraction, 0), 1)

    ctx.setLineWidth(o.lineWidth)
    ctx.setStrokeColor(track.cgColor)
    ctx.addArc(center: center, radius: radius,
               startAngle: 0, endAngle: 2 * .pi, clockwise: false)
    ctx.strokePath()

    if clamped > 0 {
        ctx.setLineCap(.round)
        ctx.setStrokeColor((met && o.fillHex == nil ? goal : accent).cgColor)
        // Why clockwise from the top: matches InkRing's `.rotationEffect(-90°)`
        // on a trim that grows clockwise. AppKit's y axis points up, so the top
        // of the circle is +90° and the sweep runs toward decreasing angles.
        ctx.addArc(center: center, radius: radius,
                   startAngle: .pi / 2,
                   endAngle: .pi / 2 - 2 * .pi * clamped,
                   clockwise: true)
        ctx.strokePath()
    }

    if !o.ringOnly {
        let seconds = clamped * o.goalSeconds
        let figure = NSAttributedString(string: clock(seconds: seconds), attributes: [
            .font: serifFont(size: o.size * 0.21),
            .foregroundColor: ink,
        ])
        let caption = NSAttributedString(
            string: "\(Int((clamped * 100).rounded())) % von \(goalLabel(seconds: o.goalSeconds))",
            attributes: [
                .font: NSFont.systemFont(ofSize: o.size * 0.045),
                .foregroundColor: ink.withAlphaComponent(o.textHex == nil ? 0.65 : 0.8),
            ])

        let gap = o.size * 0.035
        let figureSize = figure.size()
        let captionSize = caption.size()
        let block = figureSize.height + gap + 1 + gap + captionSize.height
        var y = center.y + block / 2 - figureSize.height

        figure.draw(at: CGPoint(x: center.x - figureSize.width / 2, y: y))
        y -= gap + 1
        ink.withAlphaComponent(0.06).setFill()
        NSRect(x: center.x - o.size * 0.08, y: y, width: o.size * 0.16, height: 1).fill()
        y -= gap + captionSize.height
        caption.draw(at: CGPoint(x: center.x - captionSize.width / 2, y: y))
    }

    return rep
}

let options = parse()
let directory = URL(fileURLWithPath: options.out)
try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

let sweepFrames = max(1, Int((options.duration * Double(options.fps)).rounded()))
let holdFrames = max(0, Int((options.holdSeconds * Double(options.fps)).rounded()))

for frame in 0..<(sweepFrames + holdFrames) {
    let progress = frame < sweepFrames
        ? ease(Double(frame) / Double(sweepFrames - 1 == 0 ? 1 : sweepFrames - 1), options.easing)
        : 1
    let fraction = options.from + (options.to - options.from) * progress
    let rep = render(options, fraction: fraction)
    let url = directory.appendingPathComponent(String(format: "ring_%04d.png", frame + 1))
    try! rep.representation(using: .png, properties: [:])!.write(to: url)
}

print("""
\(sweepFrames + holdFrames) frames → \(directory.path)

  ffmpeg -framerate \(options.fps) -i \(directory.path)/ring_%04d.png \\
      -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le ring.mov
""")
