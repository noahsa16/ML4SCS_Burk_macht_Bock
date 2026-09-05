import AppKit

// Renders app screenshots inside a drawn iPhone frame as a PNG sequence: the
// device holds still while the screens push through it sideways, the way a
// product video shows someone moving through an app.
//
//   cd watch_streamer && swiftc -O -o /tmp/renderdevice tools/render_device_frames.swift
//   /tmp/renderdevice --out /tmp/device_frames \
//       screenshots/02_heute.png screenshots/05_fokus_bereit.png
//
//   ffmpeg -framerate 30 -i /tmp/device_frames/frame_%04d.png \
//       -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le device.mov

struct Options {
    var fps: Int = 30
    var holdSeconds: Double = 1.6
    var pushSeconds: Double = 0.55
    var zoom: Double = 0.04
    var bgHex: UInt32? = nil
    var out = "device_frames"
    var screenshots: [String] = []
}

func parse() -> Options {
    var o = Options()
    var args = Array(CommandLine.arguments.dropFirst())
    while let arg = args.first {
        args.removeFirst()
        func value() -> String { args.isEmpty ? "" : args.removeFirst() }
        switch arg {
        case "--fps": o.fps = Int(value()) ?? 30
        case "--hold": o.holdSeconds = Double(value()) ?? 1.6
        case "--push": o.pushSeconds = Double(value()) ?? 0.55
        case "--zoom": o.zoom = Double(value()) ?? 0.04
        case "--bg": o.bgHex = UInt32(value().replacingOccurrences(of: "#", with: ""), radix: 16)
        case "--out": o.out = value()
        default:
            if arg.hasPrefix("--") {
                FileHandle.standardError.write("unknown flag \(arg)\n".data(using: .utf8)!)
                exit(2)
            }
            o.screenshots.append(arg)
        }
    }
    return o
}

/// Apple's corners are a superellipse, not a circular arc — a plain rounded
/// rect reads visibly pinched at this radius. Sampling the superellipse is
/// simpler than chaining the Bézier approximation and just as accurate here.
func squircle(_ rect: CGRect, radius: CGFloat, exponent: CGFloat = 5) -> CGPath {
    let path = CGMutablePath()
    let r = min(radius, min(rect.width, rect.height) / 2)
    let steps = 24

    // Each corner is walked in the direction the outline travels, so the
    // corners chain edge to edge. Sampling them in a fixed t direction instead
    // connects the end of one corner to the start of the next across the body.
    func corner(cx: CGFloat, cy: CGFloat, sx: CGFloat, sy: CGFloat, fromX: Bool) {
        for step in 0...steps {
            let raw = CGFloat(step) / CGFloat(steps) * .pi / 2
            let t = fromX ? raw : .pi / 2 - raw
            let dx = pow(cos(t), 2 / exponent) * r
            let dy = pow(sin(t), 2 / exponent) * r
            let point = CGPoint(x: cx + sx * dx, y: cy + sy * dy)
            if path.isEmpty { path.move(to: point) } else { path.addLine(to: point) }
        }
    }

    // Counterclockwise from the bottom edge.
    corner(cx: rect.maxX - r, cy: rect.minY + r, sx: 1, sy: -1, fromX: false)
    corner(cx: rect.maxX - r, cy: rect.maxY - r, sx: 1, sy: 1, fromX: true)
    corner(cx: rect.minX + r, cy: rect.maxY - r, sx: -1, sy: 1, fromX: false)
    corner(cx: rect.minX + r, cy: rect.minY + r, sx: -1, sy: -1, fromX: true)
    path.closeSubpath()
    return path
}

func ease(_ t: Double) -> Double {
    let t = min(max(t, 0), 1)
    return t < 0.5 ? 4 * t * t * t : 1 - pow(-2 * t + 2, 3) / 2
}

@main
enum RenderDeviceFrames {
    static func main() {
        let o = parse()
        guard !o.screenshots.isEmpty else {
            FileHandle.standardError.write("pass at least one screenshot path\n".data(using: .utf8)!)
            exit(2)
        }
        let shots = o.screenshots.compactMap { NSImage(contentsOfFile: $0) }
        guard shots.count == o.screenshots.count else {
            FileHandle.standardError.write("could not read every screenshot\n".data(using: .utf8)!)
            exit(1)
        }

        // Geometry in screenshot pixels, so the frame fits whatever device the
        // shots came from rather than a hard-coded model.
        let screen = CGSize(width: shots[0].size.width, height: shots[0].size.height)
        let bezel = screen.width * 0.033
        let rim = screen.width * 0.010
        let screenRadius = screen.width * 0.157
        let body = CGSize(width: screen.width + 2 * (bezel + rim),
                          height: screen.height + 2 * (bezel + rim))
        // Margin absorbs the zoom, so the device never grows past the canvas.
        let margin = body.width * 0.10
        let canvas = CGSize(width: body.width + 2 * margin, height: body.height + 2 * margin)

        let holdFrames = max(1, Int((o.holdSeconds * Double(o.fps)).rounded()))
        let pushFrames = max(1, Int((o.pushSeconds * Double(o.fps)).rounded()))
        let perScreen = holdFrames + pushFrames
        // The last screen holds without a push after it.
        let totalFrames = perScreen * (shots.count - 1) + holdFrames

        let directory = URL(fileURLWithPath: o.out)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        for frame in 0..<totalFrames {
            let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil,
                pixelsWide: Int(canvas.width), pixelsHigh: Int(canvas.height),
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
            let ctx = NSGraphicsContext.current!.cgContext
            ctx.clear(CGRect(origin: .zero, size: canvas))
            if let bg = o.bgHex {
                ctx.setFillColor(CGColor(srgbRed: CGFloat((bg >> 16) & 0xFF) / 255,
                                         green: CGFloat((bg >> 8) & 0xFF) / 255,
                                         blue: CGFloat(bg & 0xFF) / 255, alpha: 1))
                ctx.fill(CGRect(origin: .zero, size: canvas))
            }

            let scale = 1 + o.zoom * (Double(frame) / Double(max(1, totalFrames - 1)))
            ctx.translateBy(x: canvas.width / 2, y: canvas.height / 2)
            ctx.scaleBy(x: CGFloat(scale), y: CGFloat(scale))
            ctx.translateBy(x: -canvas.width / 2, y: -canvas.height / 2)

            let bodyRect = CGRect(x: margin, y: margin, width: body.width, height: body.height)
            let screenRect = bodyRect.insetBy(dx: bezel + rim, dy: bezel + rim)

            // Titanium rim, then the black bezel inside it.
            ctx.addPath(squircle(bodyRect, radius: screenRadius + bezel + rim))
            ctx.setFillColor(NSColor(calibratedWhite: 0.62, alpha: 1).cgColor)
            ctx.fillPath()
            ctx.addPath(squircle(bodyRect.insetBy(dx: rim, dy: rim), radius: screenRadius + bezel))
            ctx.setFillColor(NSColor(calibratedWhite: 0.06, alpha: 1).cgColor)
            ctx.fillPath()

            ctx.saveGState()
            ctx.addPath(squircle(screenRect, radius: screenRadius))
            ctx.clip()

            let index = min(shots.count - 1, frame / perScreen)
            let within = frame - index * perScreen
            // Offsets are in screen widths: the outgoing screen slides left as
            // the incoming one arrives from the right, both on the same curve.
            var offset: CGFloat = 0
            var incoming: Int? = nil
            if within >= holdFrames, index + 1 < shots.count {
                let t = ease(Double(within - holdFrames + 1) / Double(pushFrames))
                offset = -CGFloat(t) * screenRect.width
                incoming = index + 1
            }

            func draw(_ image: NSImage, dx: CGFloat) {
                let target = CGRect(x: screenRect.minX + dx, y: screenRect.minY,
                                    width: screenRect.width, height: screenRect.height)
                image.draw(in: target, from: .zero, operation: .sourceOver, fraction: 1)
            }
            draw(shots[index], dx: offset)
            if let next = incoming { draw(shots[next], dx: offset + screenRect.width) }
            ctx.restoreGState()

            // No Dynamic Island is drawn here: the simulator screenshots already
            // contain it, and a second one stayed put while the baked-in one
            // slid away during a push.
            NSGraphicsContext.restoreGraphicsState()
            let url = directory.appendingPathComponent(String(format: "frame_%04d.png", frame + 1))
            try! rep.representation(using: .png, properties: [:])!.write(to: url)
        }

        print("\(totalFrames) frames, \(shots.count) screens, "
              + "\(Int(canvas.width))x\(Int(canvas.height)) → \(directory.path)")
    }
}
