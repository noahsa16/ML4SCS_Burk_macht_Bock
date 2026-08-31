import Testing
import SwiftUI
import UIKit
@testable import WatchStreamer

@Suite("Scrybe glyphs")
struct ScrybeGlyphTests {

    /// Why a non-empty path at tab size: a Shape that renders nothing looks
    /// exactly like a correctly wired icon that happens to be invisible.
    @Test func everyGlyphDrawsSomethingAtTabSize() {
        let box = CGRect(x: 0, y: 0, width: 24, height: 24)
        for glyph in ScrybeGlyph.allCases {
            let path = ScrybeGlyphShape(glyph: glyph).path(in: box)
            #expect(!path.isEmpty, "\(glyph) drew nothing")
            #expect(box.insetBy(dx: -1, dy: -1).contains(path.boundingRect),
                    "\(glyph) drew outside its box")
        }
    }

    /// Why pixels and not the path: a non-empty `Path` was never what was at
    /// risk. The tab bar shipped with no icons at all because `tabItem` drops
    /// any icon view that is not `Text` or `Image`, and the path assertion
    /// above stayed green throughout. This one fails if nothing reaches the
    /// screen.
    @Test @MainActor func everyGlyphRastersToVisiblePixels() {
        for glyph in ScrybeGlyph.allCases {
            guard let image = ScrybeGlyph.renderedPixels(glyph),
                  let cg = image.cgImage else {
                Issue.record("\(glyph) rendered no image"); continue
            }
            let width = cg.width, height = cg.height
            var pixels = [UInt8](repeating: 0, count: width * height * 4)
            let context = CGContext(data: &pixels, width: width, height: height,
                                    bitsPerComponent: 8, bytesPerRow: width * 4,
                                    space: CGColorSpaceCreateDeviceRGB(),
                                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            context?.draw(cg, in: CGRect(x: 0, y: 0, width: width, height: height))
            let inked = stride(from: 3, to: pixels.count, by: 4).contains { pixels[$0] > 0 }
            #expect(inked, "\(glyph) rastered to nothing visible")
        }
    }
}
