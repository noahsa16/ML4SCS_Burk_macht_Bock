import Testing
import SwiftUI
@testable import WatchStreamer

@Suite("Scrybe glyphs")
struct ScrybeGlyphTests {

    /// Why a non-empty path at tab size: a Shape that renders nothing looks
    /// exactly like a correctly wired icon that happens to be invisible, and
    /// the tab bar would ship blank.
    @Test func everyGlyphDrawsSomethingAtTabSize() {
        let box = CGRect(x: 0, y: 0, width: 24, height: 24)
        for glyph in ScrybeGlyph.allCases {
            let path = ScrybeGlyphShape(glyph: glyph).path(in: box)
            #expect(!path.isEmpty, "\(glyph) drew nothing")
            #expect(box.insetBy(dx: -1, dy: -1).contains(path.boundingRect),
                    "\(glyph) drew outside its box")
        }
    }
}
