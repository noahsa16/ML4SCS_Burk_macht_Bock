# Scrybe Fertigstellungs-Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Designsprache der App erreicht ihre Ränder — Tab-Bar, Zeitraum-Umschalter, Streak-Marke, Splash und Empty-States hören auf, nach System-Chrome auszusehen.

**Architecture:** Kein Redesign. Die Token-Ebene in `ScrybeTheme.swift` bleibt unangetastet; ersetzt werden ausschließlich Symbole, Erscheinung und Typografie an fünf benannten Stellen. Der `TabView`-Container selbst bleibt Stock, damit Auswahl, Zustandserhalt und Safe-Area-Verhalten unverändert bleiben.

**Tech Stack:** Swift 5 (Sprachmodus), SwiftUI, iOS 16, Swift Testing, Xcode-Projekt `watch_streamer/WatchStreamer.xcodeproj`.

**Spec:** `docs/specs/2026-08-31-scrybe-launch-fokus-tab-design.md` §10

## Global Constraints

- **Sprache:** Code, Kommentare und Commits auf Englisch; nutzersichtbare Strings auf Deutsch über `String(localized:)` mit englischer Übersetzung in `Localizable.xcstrings`.
- **Der `TabView`-Container bleibt Stock.** Ersetzt werden nur Symbole und Erscheinung, nie der Container.
- **Jedes Tab-Item behält sein Textlabel.** Form ist nie die alleinige Information.
- **Die Serifen-Schalter behalten Button-Rolle und Auswahl-Ansage**, die `Picker` heute liefert.
- **Abbruchkriterium (Spec §10):** Regressiert native Tab-Accessibility oder das Safe-Area-Verhalten, wird der betroffene Teil verschoben — unabhängig davon, ob die Shapes optisch fertig sind. Der Zustand „sieht gut aus, VoiceOver liest schlechter" ist kein Abwägungsfall.
- **Keine Bestiariums-Kreaturen als Tab-Symbole.** Die Kreatur ist die Belohnung des Fokus-Tabs.
- **Testlauf:** `xcodebuild -project watch_streamer/WatchStreamer.xcodeproj -scheme "WatchStreamer" -destination 'id=<simulator-udid>' -only-testing:ScrybeTests test` — UDID, nicht Name.
- **Niemals Probandendaten committen.** Vor jedem Commit `git diff --cached --name-only`.

## File Structure

| Datei | Verantwortung |
|---|---|
| `watch_streamer/WatchStreamer/Scrybe/Components/ScrybeGlyphs.swift` | *(neu)* Vier Tab-Glyphen plus die Streak-Marke als `Shape` |
| `watch_streamer/WatchStreamer/Scrybe/Components/SerifSegmentedControl.swift` | *(neu)* Zwei getönte Schalter statt `Picker` |
| `watch_streamer/WatchStreamer/Scrybe/Components/EmptyPageVignette.swift` | *(neu)* Leere linierte Seite als Empty-State-Motiv |
| `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift` | Glyphen + `UITabBarAppearance` |
| `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift` | Umschalter + Streak-Marke |
| `watch_streamer/WatchStreamer/Scrybe/Components/ScrybeSplashView.swift` | Serife statt `AvenirNext-Heavy` |
| `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift` | Empty-State |

**Voraussetzung:** Plan `2026-08-31-scrybe-focus-area.md` ist umgesetzt — Task 1 unten ersetzt das Symbol eines Tabs, den erst jener Plan anlegt.

---

### Task 1: Die vier Tab-Glyphen

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/ScrybeGlyphs.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift:26-39`
- Test: `watch_streamer/ScrybeTests/ScrybeGlyphTests.swift` *(neu)*

**Interfaces:**
- Produces: `enum ScrybeGlyph: CaseIterable { case today, trends, focus, profile, streak }`, `struct ScrybeGlyphShape: Shape { let glyph: ScrybeGlyph }`

- [ ] **Step 1: Write the failing test**

```swift
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `… -only-testing:ScrybeTests/ScrybeGlyphTests test`
Expected: FAIL — `cannot find 'ScrybeGlyph' in scope`.

- [ ] **Step 3: Write minimal implementation**

```swift
import SwiftUI

/// The app's own tab and marker symbols.
///
/// Why not SF Symbols: the rest of Scrybe is ink on paper, and the tab bar was
/// the one surface where that stopped. Why not the bestiary creatures: a
/// creature is the reward of a finished session, and a navigation icon is not
/// a reward.
enum ScrybeGlyph: CaseIterable {
    /// A filled day: one closed stroke.
    case today
    /// A rising line of three marks.
    case trends
    /// A quill nib.
    case focus
    /// A profile in one stroke.
    case profile
    /// The streak marker that replaces `flame.fill`.
    case streak
}

/// Draws a glyph into whatever box it is given, normalised so the same path
/// works at tab size and inline in a sentence.
struct ScrybeGlyphShape: Shape {
    let glyph: ScrybeGlyph

    func path(in rect: CGRect) -> Path {
        let s = min(rect.width, rect.height)
        let x = rect.minX + (rect.width - s) / 2
        let y = rect.minY + (rect.height - s) / 2
        func p(_ fx: CGFloat, _ fy: CGFloat) -> CGPoint {
            CGPoint(x: x + fx * s, y: y + fy * s)
        }

        var path = Path()
        switch glyph {
        case .today:
            path.addEllipse(in: CGRect(x: x + 0.12 * s, y: y + 0.12 * s,
                                       width: 0.76 * s, height: 0.76 * s))
        case .trends:
            path.move(to: p(0.12, 0.78))
            path.addLine(to: p(0.38, 0.52))
            path.addLine(to: p(0.60, 0.66))
            path.addLine(to: p(0.88, 0.24))
        case .focus:
            path.move(to: p(0.30, 0.16))
            path.addLine(to: p(0.62, 0.16))
            path.addLine(to: p(0.52, 0.74))
            path.addLine(to: p(0.46, 0.88))
            path.addLine(to: p(0.40, 0.74))
            path.closeSubpath()
        case .profile:
            path.addEllipse(in: CGRect(x: x + 0.32 * s, y: y + 0.14 * s,
                                       width: 0.36 * s, height: 0.36 * s))
            path.move(to: p(0.16, 0.88))
            path.addQuadCurve(to: p(0.84, 0.88), control: p(0.50, 0.50))
        case .streak:
            path.move(to: p(0.50, 0.10))
            path.addQuadCurve(to: p(0.74, 0.62), control: p(0.78, 0.30))
            path.addQuadCurve(to: p(0.26, 0.62), control: p(0.50, 0.92))
            path.addQuadCurve(to: p(0.50, 0.10), control: p(0.22, 0.30))
        }
        return path
    }
}

extension ScrybeGlyph {
    /// A `Label`-compatible icon at tab-bar weight.
    var image: some View {
        ScrybeGlyphShape(glyph: self)
            .stroke(style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
            .frame(width: 24, height: 24)
    }
}
```

In `RootPagerView.swift`, replace each `systemImage:` with the glyph, keeping the text label:

```swift
                TodayView()
                    .tabItem { Label { Text("Heute") } icon: { ScrybeGlyph.today.image } }
                    .tag(Tab.today)
```

…and the same for Trends, Fokus and Profil.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Check the abort criterion on a device**

Install on a physical iPhone and confirm with VoiceOver that every tab is still announced with its name and its selected state, and that the bar still sits correctly above the home indicator. If either regressed, revert this task and record why — the criterion is not negotiable.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/ScrybeGlyphs.swift \
        watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift \
        watch_streamer/ScrybeTests/ScrybeGlyphTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): draw the tab bar in the app's own hand"
```

---

### Task 2: Die Tab-Bar in Papierfarben

**Files:**
- Modify: `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift`

- [ ] **Step 1: Apply the appearance**

```swift
    /// Why UIKit here: SwiftUI has no API for the tab bar's background on
    /// iOS 16, and the container stays stock on purpose — this changes how it
    /// looks, never how it behaves.
    private func applyTabBarAppearance() {
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(theme.paperTop)
        appearance.shadowColor = UIColor(theme.track)
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }
```

Call it from `RootPagerView.onAppear`, next to the existing `FocusStore.shared.start()`.

- [ ] **Step 2: Verify in both colour schemes**

Run the app in light and dark mode. The bar must take the paper colour in both; `ScrybeTheme` already mirrors itself, so read the tokens rather than hard-coding either value.

- [ ] **Step 3: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift
git diff --cached --name-only
git commit -m "style(scrybe): set the tab bar on paper"
```

---

### Task 3: Serifen-Schalter statt Segmented-Picker

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/SerifSegmentedControl.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift:35-38`

**Interfaces:**
- Produces: `struct SerifSegmentedControl<Value: Hashable>: View { init(options: [(value: Value, label: String)], selection: Binding<Value>) }`

- [ ] **Step 1: Build the control**

```swift
import SwiftUI

/// Two tinted serif switches where a stock segmented picker used to sit.
///
/// Keeps what `Picker` gave for free: each option is a button, and the
/// selected one announces itself as selected. Losing that would trade an
/// accessibility guarantee for a typeface.
struct SerifSegmentedControl<Value: Hashable>: View {
    let options: [(value: Value, label: String)]
    @Binding var selection: Value

    @Environment(\.scrybe) private var theme

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options, id: \.value) { option in
                let selected = option.value == selection
                Button { selection = option.value } label: {
                    Text(option.label)
                        .font(.system(.subheadline, design: .serif))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
                .background(selected ? theme.wash(theme.accent) : Color.clear,
                            in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
            }
        }
        .padding(4)
        .background(theme.track, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
```

- [ ] **Step 2: Use it in Trends**

Replace the `Picker`/`.pickerStyle(.segmented)` block at `TrendsView.swift:35-38` with `SerifSegmentedControl`, passing the same two options and the same `$range` binding.

- [ ] **Step 3: Verify with VoiceOver**

Both options must be announced as buttons, and the active one as selected. If not, revert per the abort criterion.

- [ ] **Step 4: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/SerifSegmentedControl.swift \
        watch_streamer/WatchStreamer/Scrybe/TrendsView.swift
git diff --cached --name-only
git commit -m "style(scrybe): swap the stock picker for two serif switches"
```

---

### Task 4: Die Streak-Marke

`flame.fill` ist die Fitness-Trope, die `Components/InkRing.swift:37-42` im eigenen Kommentar ablehnt.

**Files:**
- Modify: `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift:82`

- [ ] **Step 1: Replace the symbol**

```swift
                ScrybeGlyphShape(glyph: .streak)
                    .stroke(style: StrokeStyle(lineWidth: 1.4, lineCap: .round))
                    .frame(width: 16, height: 16)
                    .foregroundStyle(theme.sepia)
```

Keep whatever accessibility label the row already carries; if it had none, the streak value must still be announced with its meaning.

- [ ] **Step 2: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/TrendsView.swift
git diff --cached --name-only
git commit -m "style(scrybe): retire the flame the design already refused"
```

---

### Task 5: Der Splash spricht dieselbe Schrift

`AvenirNext-Heavy` kommt sonst nirgends in der App vor — Marke und Anwendung widersprechen sich im ersten Moment des Öffnens.

**Files:**
- Modify: `watch_streamer/WatchStreamer/Scrybe/Components/ScrybeSplashView.swift:21`

- [ ] **Step 1: Change the face**

```swift
                .font(.system(size: 56, weight: .regular, design: .serif))
```

Keep the size relation and the layout; only the face and weight change. Verify at the largest Dynamic Type setting that the word still fits on one line.

- [ ] **Step 2: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/ScrybeSplashView.swift
git diff --cached --name-only
git commit -m "style(scrybe): let the splash speak the app's typeface"
```

---

### Task 6: Empty-States als leere Seite

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/EmptyPageVignette.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift:100`

**Interfaces:**
- Produces: `struct EmptyPageVignette: View { init(side: CGFloat = 64) }`

- [ ] **Step 1: Build the vignette**

```swift
import SwiftUI

/// A few ruled lines on nothing: the same motif the focus tab shows at full
/// size, here small and without a creature. An empty state should look like
/// the page before anyone wrote on it, not like a missing list.
struct EmptyPageVignette: View {
    var side: CGFloat = 64

    @Environment(\.scrybe) private var theme

    var body: some View {
        Canvas { context, size in
            let rows = 4
            let gap = size.height / CGFloat(rows + 1)
            for row in 1...rows {
                var line = Path()
                let y = gap * CGFloat(row)
                line.move(to: CGPoint(x: size.width * 0.12, y: y))
                line.addLine(to: CGPoint(x: size.width * 0.88, y: y))
                context.stroke(line, with: .color(theme.track), lineWidth: 1)
            }
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
    }
}
```

`accessibilityHidden` on purpose: the surrounding text already says what is empty, and a decorative mark announcing itself adds noise.

- [ ] **Step 2: Use it**

Replace `Image(systemName: "list.bullet.rectangle")` at `HistoryView.swift:100` with `EmptyPageVignette()`.

- [ ] **Step 3: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/EmptyPageVignette.swift \
        watch_streamer/WatchStreamer/Scrybe/HistoryView.swift
git diff --cached --name-only
git commit -m "style(scrybe): let an empty list look like an empty page"
```

---

### Task 7: Sichtprüfung gegen das Visual-Quality-Gate

Die Spec macht „grafisch richtig gut" zu einer eigenen Abnahmebedingung (§10, Visual-Quality-Gate).

**Files:**
- Modify: eine Notiz unter `reports/`

- [ ] **Step 1: Screenshots je Zustand**

Für Heute, Trends, Fokus (Bereit / Läuft / Fertig) und Profil je einen Referenz-Screenshot auf iPhone 15 Pro, dazu je einen auf einem kleinen iPhone und bei größter Dynamic-Type-Stufe.

- [ ] **Step 2: Gegen die Kriterien prüfen**

Komposition, Rhythmus, Typografie, Farbe, Tiefe, Animation, Bedienzustände, Gerätebreite — je wie in Spec §10 formuliert. Abweichungen bei Ringgröße, Zentrierung, Textumbruch, Buttonhöhe, Safe Area und Tab-Bar werden notiert, nicht stillschweigend akzeptiert.

- [ ] **Step 3: Abbruchkriterium prüfen**

VoiceOver über die Tab-Bar und den Trends-Umschalter. Regressiert eines gegenüber dem Stock-Verhalten, wird der betreffende Task zurückgenommen — auch wenn die Optik fertig ist.

- [ ] **Step 4: Commit the record**

```bash
git add reports/
git diff --cached --name-only
git commit -m "docs(scrybe): record the finishing pass visual check"
```
