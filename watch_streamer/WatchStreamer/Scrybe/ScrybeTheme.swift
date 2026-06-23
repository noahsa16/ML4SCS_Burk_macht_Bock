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
    /// Warm terracotta shown only at the goal-met moment (ring fill + badge).
    let goalReached: Color

    /// Light palette — warm cream paper, deep indigo accent, muted gold.
    static let standard = ScrybeTheme(
        paperTop: Color(hex: 0xF2EBDC),
        paperBottom: Color(hex: 0xE8DEC8),
        ink: Color(hex: 0x2A2733),
        accent: Color(hex: 0x3B3A6B),
        sepia: Color(hex: 0xA8893F),
        success: Color(hex: 0x5A7D4E),
        warning: Color(hex: 0xB8862F),
        danger: Color(hex: 0xA23B46),
        goalReached: Color(hex: 0xC25B3A)
    )

    /// Dark palette — mirror of `standard`: warm brown-black paper, off-white
    /// ink, brighter accent/gold/goal tones tuned to read on the dark ground.
    static let dark = ScrybeTheme(
        paperTop: Color(hex: 0x221E18),
        paperBottom: Color(hex: 0x14110C),
        ink: Color(hex: 0xF2ECE0),
        accent: Color(hex: 0x8C8FD6),
        sepia: Color(hex: 0xC9A85A),
        success: Color(hex: 0x84A877),
        warning: Color(hex: 0xD4A84A),
        danger: Color(hex: 0xD06B74),
        goalReached: Color(hex: 0xE07A50)
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

/// Injects `.standard` / `.dark` based on the active system color scheme. Wrap
/// the app root in this once so every screen follows light/dark automatically.
struct ScrybeThemeProvider<Content: View>: View {
    @Environment(\.colorScheme) private var colorScheme
    @ViewBuilder var content: Content

    var body: some View {
        content.scrybeTheme(colorScheme == .dark ? .dark : .standard)
    }
}

/// Applies the in-app DE/EN language override (set in Profil) to the view tree.
/// "system" leaves the device locale untouched.
struct ScrybeLocaleProvider<Content: View>: View {
    @AppStorage(ScrybeSettings.languageKey) private var language = ScrybeSettings.defaultLanguage
    @ViewBuilder var content: Content

    var body: some View {
        if let loc = override {
            content.environment(\.locale, loc)
        } else {
            content
        }
    }

    private var override: Locale? {
        switch language {
        case "de": return Locale(identifier: "de")
        case "en": return Locale(identifier: "en")
        default: return nil
        }
    }
}

// MARK: - Liquid Glass (iOS 26+) with matte-paper fallback
//
// Single home for all glass treatment so the iOS-26 API lives in one place and
// every surface stays consistent (spec: design system centralized in ScrybeTheme).
// Earlier OS — and Reduce Transparency at any OS — fall back to the paper card.

extension View {
    /// Rounded card / panel surface.
    func scrybeSurface(cornerRadius: CGFloat = 16, tint: Color? = nil, interactive: Bool = false) -> some View {
        modifier(ScrybeGlassSurface(
            clip: AnyShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)),
            tint: tint, interactive: interactive))
    }

    /// Capsule chip surface (live chip, offline banner, tags).
    func scrybeCapsuleSurface(tint: Color? = nil, interactive: Bool = false) -> some View {
        modifier(ScrybeGlassSurface(clip: AnyShape(Capsule()), tint: tint, interactive: interactive))
    }
}

private struct ScrybeGlassSurface: ViewModifier {
    let clip: AnyShape
    var tint: Color? = nil
    var interactive: Bool = false

    @Environment(\.scrybe) private var theme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        if #available(iOS 26, *), !reduceTransparency {
            content.glassEffect(glass, in: clip)
        } else {
            content
                .background(clip.fill(tint ?? theme.cardFill))
                .overlay(clip.stroke(theme.hairline))
        }
    }

    @available(iOS 26, *)
    private var glass: Glass {
        var g = Glass.regular
        if let tint { g = g.tint(tint) }
        if interactive { g = g.interactive() }
        return g
    }
}

/// Wraps coexisting glass surfaces in a `GlassEffectContainer` on iOS 26 (shared
/// sampling + correct blending when elements are near each other); a passthrough
/// on earlier OS.
struct ScrybeGlassGroup<Content: View>: View {
    var spacing: CGFloat = 16
    @ViewBuilder var content: Content

    var body: some View {
        if #available(iOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content }
        } else {
            content
        }
    }
}
