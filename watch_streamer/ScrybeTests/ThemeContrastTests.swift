import Testing
import SwiftUI
@testable import WatchStreamer

/// WCAG 2.1 relative luminance and contrast, implemented here so the threshold
/// is checked rather than asserted from a one-off manual measurement.
private enum WCAG {
    static func linear(_ channel: Double) -> Double {
        channel <= 0.03928 ? channel / 12.92
                           : pow((channel + 0.055) / 1.055, 2.4)
    }

    static func luminance(_ hex: UInt32) -> Double {
        let r = linear(Double((hex >> 16) & 0xFF) / 255)
        let g = linear(Double((hex >> 8) & 0xFF) / 255)
        let b = linear(Double(hex & 0xFF) / 255)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }

    static func contrast(_ a: UInt32, _ b: UInt32) -> Double {
        let la = luminance(a), lb = luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }
}

@Suite("Theme contrast")
struct ThemeContrastTests {
    /// WCAG AA for normal-size text.
    private static let minimum = 4.5

    private static let lightPapers: [UInt32] = [0xF2EBDC, 0xE8DEC8]
    private static let darkPapers: [UInt32] = [0x221E18, 0x14110C]

    // Both paper stops matter: the background is a radial gradient, so text
    // sits over the lighter tone in places and the darker tone in others.
    private func worstContrast(_ colour: UInt32, over papers: [UInt32]) -> Double {
        papers.map { WCAG.contrast(colour, $0) }.min() ?? 0
    }

    @Test("light-mode text tokens clear WCAG AA on both paper stops",
          arguments: [
            ("ink", UInt32(0x2A2733)),
            ("secondaryInk", UInt32(0x76602C)),
            ("successInk", UInt32(0x4D6A42)),
            ("accent", UInt32(0x3B3A6B)),
            ("danger", UInt32(0xA23B46)),
          ])
    func lightTextTokens(name: String, hex: UInt32) {
        let ratio = worstContrast(hex, over: Self.lightPapers)
        #expect(ratio >= Self.minimum,
                "\(name) is \(String(format: "%.2f", ratio)):1")
    }

    @Test("dark-mode text tokens clear WCAG AA on both paper stops",
          arguments: [
            ("ink", UInt32(0xF2ECE0)),
            ("secondaryInk", UInt32(0xC9A85A)),
            ("successInk", UInt32(0x84A877)),
            ("accent", UInt32(0x8C8FD6)),
          ])
    func darkTextTokens(name: String, hex: UInt32) {
        let ratio = worstContrast(hex, over: Self.darkPapers)
        #expect(ratio >= Self.minimum,
                "\(name) is \(String(format: "%.2f", ratio)):1")
    }

    // Guards the reason the split exists: sepia is kept for decoration
    // precisely because it cannot carry text, and a future edit that quietly
    // lightens secondaryInk back toward it should fail here.
    @Test("decorative sepia is documented as failing, so it stays out of text")
    func sepiaIsBelowTextThreshold() {
        let ratio = worstContrast(0xA8893F, over: Self.lightPapers)
        #expect(ratio < Self.minimum,
                "sepia now passes; if that is intended, merge it with secondaryInk")
    }

    @Test("secondaryInk is a genuine improvement over sepia")
    func secondaryInkBeatsSepia() {
        #expect(worstContrast(0x76602C, over: Self.lightPapers)
                > worstContrast(0xA8893F, over: Self.lightPapers))
    }
}
