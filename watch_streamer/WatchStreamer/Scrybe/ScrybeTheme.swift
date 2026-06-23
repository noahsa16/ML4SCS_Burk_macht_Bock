import SwiftUI

struct ScrybeTheme {
    let paperTop: Color
    let paperBottom: Color
    let ink: Color
    let accent: Color
    let sepia: Color
    let success: Color
    let warning: Color
    let danger: Color

    static let standard = ScrybeTheme(
        paperTop: Color(hex: 0xF6EFE0),
        paperBottom: Color(hex: 0xECE3D0),
        ink: Color(hex: 0x2A2733),
        accent: Color(hex: 0x4B4E8C),
        sepia: Color(hex: 0x8A6D3B),
        success: Color(hex: 0x5A7D4E),
        warning: Color(hex: 0xB8862F),
        danger: Color(hex: 0xA23B46)
    )

    /// Radial cream wash used as the app background.
    var paper: RadialGradient {
        RadialGradient(
            colors: [paperTop, paperBottom],
            center: .top,
            startRadius: 0,
            endRadius: 700
        )
    }

    // Derived tokens — keep ad-hoc opacities to a few named values (design skill).
    var track: Color { ink.opacity(0.10) }     // ring/track backgrounds
    var hairline: Color { ink.opacity(0.06) }   // card strokes, dividers
    var cardFill: Color { paperTop }            // card surface
    var mutedInk: Color { ink.opacity(0.15) }   // inactive dots/bars
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255.0,
            green: Double((hex >> 8) & 0xFF) / 255.0,
            blue: Double(hex & 0xFF) / 255.0,
            opacity: 1.0
        )
    }
}

private struct ScrybeThemeKey: EnvironmentKey {
    static let defaultValue = ScrybeTheme.standard
}

extension EnvironmentValues {
    var scrybe: ScrybeTheme {
        get { self[ScrybeThemeKey.self] }
        set { self[ScrybeThemeKey.self] = newValue }
    }
}

extension View {
    func scrybeTheme(_ theme: ScrybeTheme = .standard) -> some View {
        environment(\.scrybe, theme)
    }
}
