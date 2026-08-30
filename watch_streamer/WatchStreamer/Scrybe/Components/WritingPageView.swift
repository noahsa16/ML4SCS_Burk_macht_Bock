import SwiftUI

/// Pure geometry for `WritingPageView`: converts session time into positions
/// on a page that wraps like handwriting. No SwiftUI dependency, so gap
/// compression, the paragraph break, and line wrapping are unit-testable
/// without a `Canvas`.
enum WritingPageLayout {

    /// One drawable span of a segment, confined to a single line. A segment
    /// whose drawn width outgrows a line is split into one `Run` per line it
    /// touches — `isSegmentStart`/`isSegmentEnd` mark only the very first and
    /// very last piece, which is where the ink actually sets down or lifts;
    /// the pieces in between are mid-stroke and draw at full, untapered width.
    struct Run: Equatable {
        let kind: FocusSegmentKind
        let line: Int
        /// Offset from the line's writing origin, in drawn seconds (not
        /// wall-clock seconds for a `.lift` — see `drawnSeconds(_:)`).
        let startOffset: Double
        let endOffset: Double
        let isSegmentStart: Bool
        let isSegmentEnd: Bool
        /// The kind of the segment immediately before this one in the
        /// original list — set only when `isSegmentStart` (there is nothing
        /// else it could mean on a mid-wrap piece). Lets the taper suppress
        /// itself when what precedes is a `.resting` pause the stroke must
        /// run through rather than tear before.
        let precedingKind: FocusSegmentKind?
        /// Same, but the segment immediately after — set only when
        /// `isSegmentEnd`.
        let followingKind: FocusSegmentKind?
    }

    /// A `.paragraph` gap: no ink of its own, just the line it breaks onto
    /// and its true (uncompressed) length for the serif figure beside it.
    struct ParagraphMark: Equatable {
        let line: Int
        let durationMs: Int64
    }

    struct Page: Equatable {
        let runs: [Run]
        let paragraphMarks: [ParagraphMark]
        let lineCount: Int
        /// Drawn seconds immediately after the last segment — where the next
        /// one would begin, and the anchor the wet head's trace starts from.
        let endCursor: Double
    }

    /// A segment's own contribution to the page's drawn-time axis, before
    /// line wrapping. Ink and resting spans draw at wall-clock speed; a lift
    /// draws compressed once past `FocusStrokes.restingGapMs`, so a
    /// near-a-minute gap does not cost the page a near-a-minute of line.
    /// `.paragraph` is not compressed by this function at all — `layout`
    /// never measures it in drawn seconds, since a paragraph does not occupy
    /// line width, it starts a fresh one.
    static func drawnSeconds(_ segment: FocusSegment) -> Double {
        let spanSeconds = Double(segment.endMs - segment.startMs) / 1000
        guard segment.kind == .lift else { return spanSeconds }
        let boundSeconds = Double(FocusStrokes.restingGapMs) / 1000
        guard spanSeconds > boundSeconds else { return spanSeconds }
        return boundSeconds + log(1 + (spanSeconds - boundSeconds))
    }

    /// Maps a scalar position on the page's continuous drawn-time axis to a
    /// (line, offset) point, wrapping every `secondsPerLine`.
    static func point(atDrawnSeconds t: Double, secondsPerLine: Double) -> (line: Int, offset: Double) {
        guard secondsPerLine > 0 else { return (0, 0) }
        let line = Int(t / secondsPerLine)
        let offset = t.truncatingRemainder(dividingBy: secondsPerLine)
        return (line, offset)
    }

    /// Lays segments onto lines of `secondsPerLine` drawn seconds each.
    static func layout(_ segments: [FocusSegment], secondsPerLine: Double) -> Page {
        guard secondsPerLine > 0, !segments.isEmpty else {
            return Page(runs: [], paragraphMarks: [], lineCount: 1, endCursor: 0)
        }

        var runs: [Run] = []
        var marks: [ParagraphMark] = []
        var cursor = 0.0
        var maxLine = 0

        for (index, segment) in segments.enumerated() {
            let precedingKind = index > 0 ? segments[index - 1].kind : nil
            let followingKind = index < segments.count - 1 ? segments[index + 1].kind : nil

            if segment.kind == .paragraph {
                // Why: a paragraph is a real line break, not just a wide
                // gap — it always starts a fresh line, even with room left
                // on the current one (Spec §6 "Lücken", > 60 s tier).
                let remainder = cursor.truncatingRemainder(dividingBy: secondsPerLine)
                if remainder != 0 {
                    cursor += secondsPerLine - remainder
                }
                let line = Int(cursor / secondsPerLine)
                maxLine = max(maxLine, line)
                marks.append(ParagraphMark(line: line, durationMs: segment.endMs - segment.startMs))
                continue
            }

            let width = drawnSeconds(segment)
            let start = cursor
            let end = cursor + width
            var lineCursor = start
            var first = true
            repeat {
                let line = Int(lineCursor / secondsPerLine)
                let lineStart = Double(line) * secondsPerLine
                let lineEnd = lineStart + secondsPerLine
                let runEnd = min(end, lineEnd)
                let isEnd = runEnd >= end
                runs.append(Run(kind: segment.kind, line: line,
                                startOffset: lineCursor - lineStart,
                                endOffset: runEnd - lineStart,
                                isSegmentStart: first,
                                isSegmentEnd: isEnd,
                                precedingKind: first ? precedingKind : nil,
                                followingKind: isEnd ? followingKind : nil))
                maxLine = max(maxLine, line)
                first = false
                lineCursor = runEnd
            } while lineCursor < end
            cursor = end
        }

        return Page(runs: runs, paragraphMarks: marks, lineCount: maxLine + 1, endCursor: cursor)
    }
}

/// The session as a page: time runs left to right and wraps like handwriting.
struct WritingPageView: View {
    let segments: [FocusSegment]
    let species: Int
    let strokesDrawn: Int
    /// Wall clock of the pen tip, which runs ahead of the last decision by one
    /// window. Drawn faint so the latency is shown rather than hidden.
    let headMs: Int64

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let lineHeight: CGFloat = 32
    private let marginLeft: CGFloat = 40
    private let marginRight: CGFloat = 24
    private let topInset: CGFloat = 24
    private let bottomInset: CGFloat = 16
    private let paragraphIndent: CGFloat = 16
    private let creatureBoxSize: CGFloat = 32
    /// One line of page holds this much writing (Spec §6).
    private let secondsPerLine: Double = 120
    /// How long the "wet ink" highlight on freshly arrived content takes to
    /// settle back to normal (Spec §6 "trocknet über 4-6 s").
    private let settleSeconds: Double = 5

    // Tracks the ink's own dry-in highlight: the tail of the most recently
    // extended run reads darker/wider for a few seconds, then settles. Keyed
    // off wall-clock time because the model reports segments, not when each
    // one arrived.
    @State private var lastGrowth: (endMs: Int64, at: Date)?

    private var page: WritingPageLayout.Page {
        WritingPageLayout.layout(segments, secondsPerLine: secondsPerLine)
    }

    /// Wall-clock end of the last decided segment — the boundary between
    /// committed ink and the undecided window the wet head traces over.
    private var committedEndMs: Int64 { segments.last?.endMs ?? headMs }
    private var latencySeconds: Double { max(0, Double(headMs - committedEndMs) / 1000) }

    var body: some View {
        // Why: computed once per body evaluation (i.e. once per actual change
        // to `segments`), not once per animation tick — the layout and the
        // static page below share this single value instead of each layer
        // (or worse, every 1/60s tick) re-running `WritingPageLayout.layout`.
        let page = page
        ZStack(alignment: .topLeading) {
            staticPage(page)
            if !reduceMotion {
                // Why: only the wet head moves in real time -- the ruled
                // lines, every ink/resting run, every paragraph mark, and up
                // to 200+ creature strokes are static between decisions and
                // must not be redrawn 60 times a second for a tip that is
                // the only thing actually animating.
                TimelineView(.animation(minimumInterval: 1.0 / 60, paused: reduceMotion)) { timeline in
                    Canvas { context, size in
                        let geo = renderGeometry(page: page, size: size)
                        drawWetHead(page: page, geo: geo, now: timeline.date, in: &context)
                    }
                    .allowsHitTesting(false)
                }
            }
        }
        .frame(height: pageHeight(page: page))
        .background(theme.paper)
        .onChange(of: segments.last?.endMs) { newValue in
            // Why: only genuine ink growth gets the dry-in highlight -- a
            // `.resting`/`.lift` tail merely extending must not refresh it,
            // or a long pause would keep re-lighting ink that was actually
            // written seconds-to-minutes ago.
            guard let newValue, segments.last?.kind == .ink else { return }
            lastGrowth = (newValue, Date())
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("Schreibseite dieser Sitzung"))
    }

    /// Rules, ink, resting hairlines, paragraph marks and the creature — the
    /// entire page except the wet head. Redraws only when SwiftUI decides
    /// this view's own inputs changed, never on the wet head's 60 Hz tick.
    private func staticPage(_ page: WritingPageLayout.Page) -> some View {
        Canvas { context, size in
            let geo = renderGeometry(page: page, size: size)
            drawRules(page: page, width: size.width, in: &context)
            drawCreature(in: &context)
            for run in page.runs {
                draw(run, geo: geo, in: &context)
            }
            for mark in page.paragraphMarks {
                drawParagraphMark(mark, geo: geo, in: &context)
            }
        }
    }

    private func renderGeometry(page: WritingPageLayout.Page, size: CGSize) -> RenderGeometry {
        RenderGeometry(size: size, marginLeft: marginLeft, marginRight: marginRight,
                       paragraphIndent: paragraphIndent, secondsPerLine: secondsPerLine,
                       indentedLines: Set(page.paragraphMarks.map(\.line)))
    }

    // MARK: - Layout-derived geometry (SwiftUI-side; not part of the pure mapping)

    /// Bundles the per-frame pixel math so draw helpers don't each recompute
    /// `pxPerSecond` or thread `size` through every call individually.
    private struct RenderGeometry {
        let pxPerSecond: CGFloat
        let marginLeft: CGFloat
        let paragraphIndent: CGFloat
        let indentedLines: Set<Int>

        init(size: CGSize, marginLeft: CGFloat, marginRight: CGFloat, paragraphIndent: CGFloat,
             secondsPerLine: Double, indentedLines: Set<Int>) {
            let usable = max(0, size.width - marginLeft - marginRight)
            self.pxPerSecond = secondsPerLine > 0 ? usable / CGFloat(secondsPerLine) : 0
            self.marginLeft = marginLeft
            self.paragraphIndent = paragraphIndent
            self.indentedLines = indentedLines
        }

        /// x for a point `offsetSeconds` into `line` — indented past the
        /// margin when that line follows a `.paragraph` break.
        func x(_ offsetSeconds: Double, line: Int) -> CGFloat {
            let start = indentedLines.contains(line) ? marginLeft + paragraphIndent : marginLeft
            return start + CGFloat(offsetSeconds) * pxPerSecond
        }
    }

    private func baselineY(line: Int) -> CGFloat {
        topInset + CGFloat(line) * lineHeight + lineHeight * 0.7
    }

    private func pageHeight(page: WritingPageLayout.Page) -> CGFloat {
        topInset + CGFloat(max(1, page.lineCount)) * lineHeight + bottomInset
    }

    // MARK: - Drawing

    private func drawRules(page: WritingPageLayout.Page, width: CGFloat, in context: inout GraphicsContext) {
        for line in 0..<max(1, page.lineCount) {
            let y = baselineY(line: line)
            var path = Path()
            path.move(to: CGPoint(x: 0, y: y))
            path.addLine(to: CGPoint(x: width, y: y))
            // Why: the ruled baseline is functional, not decorative -- without
            // it a gap reads as nothing rather than an empty line (Spec §6
            // "Aufbau").
            context.stroke(path, with: .color(theme.hairline), lineWidth: 0.5)
        }
    }

    private func drawCreature(in context: inout GraphicsContext) {
        let strokes = Marginalia.strokes(forSpecies: species)
        guard !strokes.isEmpty, strokesDrawn > 0 else { return }
        let scale = creatureBoxSize / 100
        let origin = CGPoint(x: 4, y: topInset)
        for path in strokes.prefix(strokesDrawn) {
            let scaled = path.applying(CGAffineTransform(scaleX: scale, y: scale))
                .offsetBy(dx: origin.x, dy: origin.y)
            // Why: the creature lives in the left margin, drawn `strokesDrawn`
            // strokes at a time from `Marginalia.strokes(forSpecies:)` (Spec
            // §8 "Das Bestiarium").
            context.stroke(scaled, with: .color(theme.secondaryInk), lineWidth: 1.2)
        }
    }

    private func draw(_ run: WritingPageLayout.Run, geo: RenderGeometry, in context: inout GraphicsContext) {
        switch run.kind {
        case .ink:
            drawInk(run, geo: geo, in: &context)
        case .resting:
            drawResting(run, geo: geo, in: &context)
        case .lift, .paragraph:
            // Why: `.lift` draws nothing of its own — the taper belongs to
            // the preceding ink run's `isSegmentEnd`, and the gap's drawn
            // width is already compressed logarithmically by
            // `WritingPageLayout.drawnSeconds`. `.paragraph` is consumed as
            // a `ParagraphMark`, drawn as a line break, never a run.
            break
        }
    }

    private func drawResting(_ run: WritingPageLayout.Run, geo: RenderGeometry, in context: inout GraphicsContext) {
        let y = baselineY(line: run.line)
        var path = Path()
        path.move(to: CGPoint(x: geo.x(run.startOffset, line: run.line), y: y))
        path.addLine(to: CGPoint(x: geo.x(run.endOffset, line: run.line), y: y))
        // Why: a resting gap must read as the pen resting on the page, never
        // a break — a hairline that continues the stroke rather than an
        // omission (Spec §6 "Lücken", <= 15 s tier).
        context.stroke(path, with: .color(theme.ink.opacity(0.35)), lineWidth: 0.6)
    }

    private func drawInk(_ run: WritingPageLayout.Run, geo: RenderGeometry, in context: inout GraphicsContext) {
        let y = baselineY(line: run.line)
        let x0 = geo.x(run.startOffset, line: run.line)
        let x1 = geo.x(run.endOffset, line: run.line)
        guard x1 > x0 else { return }
        // Why: two layers — a broad outer stroke at 70% opacity under a
        // narrow core at full strength — is what gives real ink its dark
        // centre (Spec §6 "Der Strich").
        strokeInkLayer(from: x0, to: x1, y: y, run: run, baseWidth: 2.5, opacity: 0.7, in: &context)
        strokeInkLayer(from: x0, to: x1, y: y, run: run, baseWidth: 1.4, opacity: 1.0, in: &context)
    }

    /// Draws one ink layer, ramping its width up at a genuine pen-down and
    /// down at a genuine pen-up. `GraphicsContext.stroke` only takes one
    /// constant width per call, so the ramp is built from a handful of short
    /// capsule-capped slices rather than a single continuously variable path.
    private func strokeInkLayer(from x0: CGFloat, to x1: CGFloat, y: CGFloat, run: WritingPageLayout.Run,
                                baseWidth: CGFloat, opacity: Double, in context: inout GraphicsContext) {
        let length = x1 - x0
        guard length > 0 else { return }
        let color = theme.ink.opacity(opacity)

        // Why: an ink stroke tapers at a genuine pen-down/pen-up — a segment
        // boundary that neighbours a `.lift` or `.paragraph` — but NOT when
        // what's on the other side is `.resting`: the spec requires that gap
        // to read as the stroke running through, never a break, so the taper
        // is suppressed there rather than firing on every segment boundary
        // regardless of what follows it. Taper length 10-16 pt (offset) /
        // 6-10 pt (onset) per spec (Spec §6 "Der Strich").
        let onsetTapers = run.isSegmentStart && run.precedingKind != .resting
        let offsetTapers = run.isSegmentEnd && run.followingKind != .resting
        let onsetLength = min(CGFloat(8), length / 2)
        let offsetLength = min(CGFloat(13), length / 2)
        let onsetEnd = onsetTapers ? x0 + onsetLength : x0
        let offsetStart = offsetTapers ? x1 - offsetLength : x1

        if onsetTapers, onsetEnd > x0 {
            rampStroke(from: x0, to: onsetEnd, y: y, baseWidth: baseWidth, growing: true, color: color, in: &context)
        }
        let middleStart = max(x0, onsetEnd)
        let middleEnd = min(x1, offsetStart)
        if middleEnd > middleStart {
            var path = Path()
            path.move(to: CGPoint(x: middleStart, y: y))
            path.addLine(to: CGPoint(x: middleEnd, y: y))
            context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: baseWidth, lineCap: .round))
        }
        if offsetTapers, offsetStart < x1 {
            rampStroke(from: max(offsetStart, x0), to: x1, y: y, baseWidth: baseWidth, growing: false,
                      color: color, in: &context)
        }
    }

    private func rampStroke(from x0: CGFloat, to x1: CGFloat, y: CGFloat, baseWidth: CGFloat, growing: Bool,
                            color: Color, in context: inout GraphicsContext) {
        let length = x1 - x0
        guard length > 0 else { return }
        let slices = 6
        for i in 0..<slices {
            let t0 = CGFloat(i) / CGFloat(slices)
            let t1 = CGFloat(i + 1) / CGFloat(slices)
            let midT = growing ? (t0 + t1) / 2 : 1 - (t0 + t1) / 2
            var path = Path()
            path.move(to: CGPoint(x: x0 + t0 * length, y: y))
            path.addLine(to: CGPoint(x: x0 + t1 * length, y: y))
            context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: baseWidth * midT, lineCap: .round))
        }
    }

    private func drawParagraphMark(_ mark: WritingPageLayout.ParagraphMark, geo: RenderGeometry,
                                   in context: inout GraphicsContext) {
        let y = baselineY(line: mark.line)
        // Why: a paragraph is a line break with an indent, and the gap's true
        // (uncompressed) length is shown beside it as a small serif figure —
        // the on-page width is compressed, the number is not (Spec §6
        // "Lücken", > 60 s tier).
        let text = Text(durationLabel(ms: mark.durationMs))
            .font(.system(size: 10, design: .serif))
            .foregroundColor(theme.ink.opacity(0.4))
        context.draw(text, at: CGPoint(x: geo.marginLeft, y: y - 10), anchor: .leading)
    }

    private func durationLabel(ms: Int64) -> String {
        let totalSeconds = max(0, Int(ms / 1000))
        return String(format: "%d:%02d", totalSeconds / 60, totalSeconds % 60)
    }

    /// The pen tip runs ahead of the last decision in real time, with a faint
    /// trace over the latency window that fills in once the decision arrives
    /// — the lag is shown, not hidden (Spec §6 "Der nasse Kopf").
    private func drawWetHead(page: WritingPageLayout.Page, geo: RenderGeometry, now: Date,
                             in context: inout GraphicsContext) {
        highlightRecentInk(page: page, geo: geo, now: now, in: &context)

        guard latencySeconds > 0 else { return }
        let tipCursor = page.endCursor + latencySeconds
        let (startLine, startOffset) = WritingPageLayout.point(atDrawnSeconds: page.endCursor,
                                                               secondsPerLine: secondsPerLine)
        let (tipLine, tipOffset) = WritingPageLayout.point(atDrawnSeconds: tipCursor,
                                                           secondsPerLine: secondsPerLine)

        if startLine == tipLine {
            drawTrace(line: startLine, from: startOffset, to: tipOffset, geo: geo, in: &context)
        } else {
            drawTrace(line: startLine, from: startOffset, to: secondsPerLine, geo: geo, in: &context)
            drawTrace(line: tipLine, from: 0, to: tipOffset, geo: geo, in: &context)
        }

        let tipY = baselineY(line: tipLine)
        let tipX = geo.x(tipOffset, line: tipLine)
        var dot = Path()
        dot.addEllipse(in: CGRect(x: tipX - 1, y: tipY - 1, width: 2, height: 2))
        context.fill(dot, with: .color(theme.ink))
    }

    private func drawTrace(line: Int, from: Double, to: Double, geo: RenderGeometry, in context: inout GraphicsContext) {
        guard to > from else { return }
        let y = baselineY(line: line)
        var path = Path()
        path.move(to: CGPoint(x: geo.x(from, line: line), y: y))
        path.addLine(to: CGPoint(x: geo.x(to, line: line), y: y))
        // Why: the trace over the latency window is a 25% ghost, not
        // committed ink — the pen "writes ahead" of the decision that will
        // fill it in (Spec §6 "Der nasse Kopf").
        context.stroke(path, with: .color(theme.ink.opacity(0.25)), lineWidth: 1.4)
    }

    /// The most recently filled stretch reads darker and wider for a few
    /// seconds before settling — linearly, never a spring (Spec §9
    /// "Bewegung": "Kopf trocknet ... nahezu linear").
    private func highlightRecentInk(page: WritingPageLayout.Page, geo: RenderGeometry, now: Date,
                                    in context: inout GraphicsContext) {
        guard let lastGrowth else { return }
        let elapsed = now.timeIntervalSince(lastGrowth.at)
        guard elapsed >= 0, elapsed < settleSeconds else { return }
        guard let lastInk = page.runs.last(where: { $0.kind == .ink }) else { return }

        let factor = 1 - elapsed / settleSeconds
        let y = baselineY(line: lastInk.line)
        let highlightSeconds = min(2.0, lastInk.endOffset - lastInk.startOffset)
        guard highlightSeconds > 0 else { return }
        let startOffset = lastInk.endOffset - highlightSeconds
        var path = Path()
        path.move(to: CGPoint(x: geo.x(startOffset, line: lastInk.line), y: y))
        path.addLine(to: CGPoint(x: geo.x(lastInk.endOffset, line: lastInk.line), y: y))
        let width = 2.5 * (1 + 0.10 * CGFloat(factor))
        let opacity = min(1.0, 0.7 + 0.10 * factor)
        context.stroke(path, with: .color(theme.ink.opacity(opacity)),
                       style: StrokeStyle(lineWidth: width, lineCap: .round))
    }
}

#Preview {
    let segments: [FocusSegment] = [
        FocusSegment(kind: .ink, startMs: 0, endMs: 45_000),
        FocusSegment(kind: .resting, startMs: 45_000, endMs: 53_000),
        FocusSegment(kind: .ink, startMs: 53_000, endMs: 130_000),
        FocusSegment(kind: .lift, startMs: 130_000, endMs: 165_000),
        FocusSegment(kind: .ink, startMs: 165_000, endMs: 300_000),
        FocusSegment(kind: .paragraph, startMs: 300_000, endMs: 372_000),
        FocusSegment(kind: .ink, startMs: 372_000, endMs: 410_000),
    ]
    return WritingPageView(segments: segments, species: 2, strokesDrawn: 5, headMs: 415_000)
        .padding(24)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
