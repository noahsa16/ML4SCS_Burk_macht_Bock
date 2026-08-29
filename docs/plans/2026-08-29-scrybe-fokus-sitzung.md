# Scrybe Fokus-Sitzung, Bestiarium und Ernte — Implementierungsplan

> **Für agentische Ausführung:** ERFORDERLICHE SUB-SKILL: `superpowers:subagent-driven-development`
> (empfohlen) oder `superpowers:executing-plans`, Aufgabe für Aufgabe. Schritte
> nutzen Checkbox-Syntax (`- [ ]`).

**Ziel:** Eine bewusst gestartete Schreib-Sitzung, deren Tintenlinie live auf dem
iPhone wächst, im Seitenrand ein sammelbares Tintenwesen zeichnet, plus eine
Ernte-Geste, die neu erkannte Minuten sichtbar in den Tages-Ring fließen lässt.

**Architektur:** Die Uhr misst, das Telefon rechnet. Während einer Sitzung
streamt die Uhr 6 IMU-Kanäle bei 50 Hz über den bestehenden Aufnahmeweg; das
iPhone klassifiziert mit `ScrybeActive` (tcn_bigru, bereits im Bundle) und hält
die Entscheidungen nur im Speicher. Der Passiv-Ganztag-Pfad bleibt unangetastet
und bleibt alleinige Quelle der Schreibzeit-Buchhaltung.

**Tech-Stack:** Swift 5.9 / SwiftUI (iOS 16+, watchOS 10.6+), Core ML,
WatchConnectivity, HealthKit (`HKWorkoutSession`), Swift Testing.

**Spec:** `docs/specs/2026-08-29-scrybe-fokus-sitzung-design.md`

## Globale Randbedingungen

- **Sprache:** Code, Bezeichner, Kommentare und Commit-Nachrichten englisch;
  Oberflächentexte deutsch (bestehende Konvention, siehe `Localizable.xcstrings`).
- **Abstände** ausschließlich aus 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48.
- **Deckkraft** nie an der Aufrufstelle erfinden: `ScrybeTheme.wash(_:)`,
  `theme.track`, `theme.hairline`.
- **Kein `minimumScaleFactor`.** Passt Text nicht, wird der Text gekürzt.
- **Kurven nach Zweck:** Ankommen bremst ab, Verlassen beschleunigt,
  gleichförmiger Fortschritt ist linear. Verboten: `.bouncy`, Federn mit
  `dampingFraction < 0.85`.
- **Reduce Motion** wird in jeder animierten View über
  `@Environment(\.accessibilityReduceMotion)` behandelt.
- **Modellparameter sind fix:** `ScrybeActive` = 6 Kanäle in der Reihenfolge
  `ax, ay, az, rx, ry, rz`, `seqLen = 250`, `strideSamples = 125`,
  `nominalHz = 50`, Schwelle `logit >= 0`.
- **Tests** laufen mit:
  `xcodebuild test -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:ScrybeTests`
- **Vor jedem Commit** `git diff --cached --name-only` prüfen. Niemals Dateien
  unter `data/` committen.

## Dateiübersicht

| Datei | Verantwortung |
|---|---|
| `Shared/ScrybeModel.swift` | *(verschoben)* manifest-getriebener Core-ML-Lader, beide Targets |
| `Shared/FocusStrokes.swift` | Entscheidungen → Striche und Lücken (reine Funktion) |
| `Shared/Bestiary.swift` | Art-Auswahl und Strichzahl (reine Funktion) |
| `WatchStreamer/Stores/FocusSessionStore.swift` | Sitzungs-Zustandsmaschine, Fensterbau, Klassifikation |
| `WatchStreamer/Stores/BestiaryStore.swift` | JSON-Persistenz der gesammelten Wesen |
| `WatchStreamer/Scrybe/Components/Marginalia.swift` | die Arten als `Path`-Daten |
| `WatchStreamer/Scrybe/Components/WritingPageView.swift` | Canvas: Seite, Linie, Wesen |
| `WatchStreamer/Scrybe/FocusSessionView.swift` | der Sitzungs-Bildschirm |
| `WatchStreamer/Scrybe/BestiaryView.swift` | die Sammlung im Verlauf |

---

### Task 1: Core-ML-Lader nach `Shared/` verschieben

`WatchScrybeModel` liegt heute nur im Watch-Target, ist aber nicht
watch-spezifisch: er lädt ein beliebiges manifest-beschriebenes Modell. Das
iPhone braucht ihn für `ScrybeActive`.

**Files:**
- Create: `watch_streamer/Shared/ScrybeModel.swift` (Inhalt aus der bisherigen Datei)
- Delete: `watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift`
- Modify: `watch_streamer/WatchStreamer Watch App/PassiveTracker.swift`,
  `watch_streamer/WatchStreamer Watch App/MotionManager.swift`,
  `watch_streamer/ScrybeTests/ScrybeModelParityTests.swift`

**Interfaces:**
- Produces: `final class ScrybeModel { init(resourceName: String, channels: Int, seqLen: Int) throws; func logit(window: [Float]) throws -> Float; let manifest: PassiveModelManifest }`
- `extension ScrybeModel: PassiveClassifier {}` ersetzt die bisherige Extension auf `WatchScrybeModel`.

- [ ] **Step 1: Die vorhandene Paritätsprüfung als Netz laufen lassen**

Run: `xcodebuild test -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:ScrybeTests/ScrybeModelParityTests`
Expected: PASS. Diese Prüfung ist das Sicherheitsnetz für den ganzen Task —
sie vergleicht Core-ML-Logits gegen PyTorch-Referenzwerte und schlägt an, wenn
der Modellpfad beim Verschieben bricht.

- [ ] **Step 2: Datei verschieben und Typ umbenennen**

```bash
git mv "watch_streamer/WatchStreamer Watch App/WatchScrybeModel.swift" \
       watch_streamer/Shared/ScrybeModel.swift
```

Dann in `Shared/ScrybeModel.swift` jedes `WatchScrybeModel` durch `ScrybeModel`
ersetzen. Die Klasse bleibt `final class`, alle Member unverändert.

Wichtig: der Datei-System-synchronisierte Xcode-Ordner nimmt `Shared/` in beide
Targets auf — es ist keine `project.pbxproj`-Änderung nötig.

- [ ] **Step 3: Aufrufstellen nachziehen**

```bash
cd watch_streamer
grep -rl "WatchScrybeModel" --include='*.swift' . \
  | xargs sed -i '' 's/WatchScrybeModel/ScrybeModel/g'
grep -rn "WatchScrybeModel" --include='*.swift' .   # muss leer sein
```

- [ ] **Step 4: Beide Targets bauen**

Run: `xcodebuild build -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'generic/platform=iOS' -configuration Debug CODE_SIGNING_ALLOWED=NO`
Expected: `** BUILD SUCCEEDED **`. Der Watch-Target wird mitgebaut; ein Fehler
dort bedeutet, dass eine Aufrufstelle übersehen wurde.

- [ ] **Step 5: Volle Suite**

Run: `xcodebuild test -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:ScrybeTests`
Expected: PASS, 214 Tests, davon `ScrybeModelParityTests` grün.

- [ ] **Step 6: Commit**

```bash
git add -A watch_streamer/Shared/ScrybeModel.swift \
  "watch_streamer/WatchStreamer Watch App" watch_streamer/ScrybeTests
git diff --cached --name-only
git commit -m "refactor(scrybe): move the Core ML loader into Shared

The loader is manifest-driven and not watch-specific; the phone needs it
to run ScrybeActive. The golden-vector parity test covers the move."
```

---

### Task 2: Striche und Lücken aus Entscheidungen

Die Seite braucht aus der Entscheidungsfolge drei Lückenklassen (Spec §6). Das
ist reine Numerik und wird ohne UI getestet.

**Files:**
- Create: `watch_streamer/Shared/FocusStrokes.swift`
- Test: `watch_streamer/ScrybeTests/FocusStrokesTests.swift`

**Interfaces:**
- Produces:
  `enum FocusSegmentKind: Equatable { case ink, resting, lift, paragraph }`
  `struct FocusSegment: Equatable { let kind: FocusSegmentKind; let startMs: Int64; let endMs: Int64 }`
  `enum FocusStrokes { static let restingGapMs: Int64 = 15_000; static let paragraphGapMs: Int64 = 60_000; static func segments(from decisions: [PassiveDecision]) -> [FocusSegment] }`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus strokes")
struct FocusStrokesTests {

    private func decision(_ offset: Int64, writing: Bool) -> PassiveDecision {
        PassiveDecision(startMs: offset, endMs: offset + 5_000,
                        logit: writing ? 2 : -2, writing: writing,
                        creditSeconds: 2.5)
    }

    // A ten-second look at the page is not an interruption; the stroke has to
    // survive it, or the page claims something the writer did not do.
    @Test("a short pause rests the pen instead of lifting it")
    func shortPauseRests() {
        let d = [decision(0, writing: true),
                 decision(10_000, writing: false),
                 decision(20_000, writing: true)]
        let kinds = FocusStrokes.segments(from: d).map(\.kind)
        #expect(kinds == [.ink, .resting, .ink])
    }

    @Test("a longer gap lifts the pen")
    func mediumGapLifts() {
        let d = [decision(0, writing: true),
                 decision(30_000, writing: false),
                 decision(40_000, writing: true)]
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .lift, .ink])
    }

    @Test("a gap past a minute starts a new paragraph")
    func longGapBreaksParagraph() {
        let d = [decision(0, writing: true),
                 decision(90_000, writing: false),
                 decision(100_000, writing: true)]
        #expect(FocusStrokes.segments(from: d).map(\.kind) == [.ink, .paragraph, .ink])
    }
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `xcodebuild test -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -only-testing:ScrybeTests/FocusStrokesTests`
Expected: FAIL, „cannot find 'FocusStrokes' in scope".

- [ ] **Step 3: Minimale Implementierung**

```swift
import Foundation

/// What one span of a session's page shows.
public nonisolated enum FocusSegmentKind: Equatable {
    /// Writing was detected: full ink.
    case ink
    /// A pause short enough that the pen is still on the page.
    case resting
    /// The pen came off the page.
    case lift
    /// Long enough that the page starts a new line.
    case paragraph
}

public nonisolated struct FocusSegment: Equatable {
    public let kind: FocusSegmentKind
    public let startMs: Int64
    public let endMs: Int64
}

/// Turns the session's decisions into what the page draws.
///
/// Why three kinds and not two: writing consists of writing *and* thinking. A
/// two-state line tore on every ten-second look at the page and claimed an
/// interruption the writer had not made.
public nonisolated enum FocusStrokes {
    /// Up to this, the pen merely rests. Also the bound past which a gap's
    /// drawn width is compressed — one threshold, two effects.
    public static let restingGapMs: Int64 = 15_000
    /// Past this, the page starts a new line.
    public static let paragraphGapMs: Int64 = 60_000

    public static func segments(from decisions: [PassiveDecision]) -> [FocusSegment] {
        let sorted = decisions.sorted { $0.startMs < $1.startMs }
        var out: [FocusSegment] = []
        for d in sorted {
            let kind: FocusSegmentKind
            if d.writing {
                kind = .ink
            } else {
                let span = d.endMs - d.startMs
                kind = span > paragraphGapMs ? .paragraph
                     : span > restingGapMs ? .lift
                     : .resting
            }
            if let last = out.last, last.kind == kind, last.endMs >= d.startMs {
                out[out.count - 1] = FocusSegment(kind: kind,
                                                  startMs: last.startMs,
                                                  endMs: max(last.endMs, d.endMs))
            } else {
                out.append(FocusSegment(kind: kind, startMs: d.startMs, endMs: d.endMs))
            }
        }
        return merged(out)
    }

    /// Adjacent non-writing spans describe one gap; classify it by its total
    /// length rather than by each five-second window on its own.
    private static func merged(_ segments: [FocusSegment]) -> [FocusSegment] {
        var out: [FocusSegment] = []
        for s in segments {
            guard s.kind != .ink, let last = out.last, last.kind != .ink else {
                out.append(s); continue
            }
            let startMs = last.startMs
            let endMs = max(last.endMs, s.endMs)
            let span = endMs - startMs
            let kind: FocusSegmentKind = span > paragraphGapMs ? .paragraph
                                       : span > restingGapMs ? .lift
                                       : .resting
            out[out.count - 1] = FocusSegment(kind: kind, startMs: startMs, endMs: endMs)
        }
        return out
    }
}
```

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Run: wie Step 2.
Expected: PASS, 3 Tests.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/Shared/FocusStrokes.swift watch_streamer/ScrybeTests/FocusStrokesTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): classify session gaps into resting, lift and paragraph"
```

---

### Task 3: Bestiarium-Numerik

Art-Auswahl und Strichzahl, gegen Zerhacken invariant (Spec §8).

**Files:**
- Create: `watch_streamer/Shared/Bestiary.swift`
- Test: `watch_streamer/ScrybeTests/BestiaryTests.swift`

**Interfaces:**
- Produces:
  `struct BestiaryEntry: Codable, Equatable { let speciesId: Int; let dateMs: Int64; let strokesDrawn: Int; let strokesTotal: Int; let writingSeconds: Double }`
  `enum Bestiary { static let speciesCount = 8; static func species(forSessionStartMs: Int64) -> Int; static func strokesDrawn(writingSeconds: Double, targetSeconds: Double, strokesTotal: Int) -> Int }`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Bestiary")
struct BestiaryTests {

    // An earlier draft grew the creature once per completed writing run, which
    // paid for fragmentation: four short bursts earned four strokes where one
    // continuous stretch earned one. Growth follows the amount written.
    @Test("the same writing time draws the same creature, however broken up")
    func invariantToFragmentation() {
        let whole = Bestiary.strokesDrawn(writingSeconds: 600,
                                          targetSeconds: 1_500, strokesTotal: 10)
        let pieces = Bestiary.strokesDrawn(writingSeconds: 150 * 4,
                                           targetSeconds: 1_500, strokesTotal: 10)
        #expect(whole == pieces)
        #expect(whole == 4)
    }

    @Test("stopping early leaves a partly drawn creature, never none")
    func partialIsKept() {
        #expect(Bestiary.strokesDrawn(writingSeconds: 1, targetSeconds: 1_500,
                                      strokesTotal: 10) == 0)
        #expect(Bestiary.strokesDrawn(writingSeconds: 900, targetSeconds: 1_500,
                                      strokesTotal: 10) == 6)
    }

    @Test("reaching the target never overdraws")
    func clampedAtTotal() {
        #expect(Bestiary.strokesDrawn(writingSeconds: 9_999, targetSeconds: 1_500,
                                      strokesTotal: 10) == 10)
    }

    @Test("the species is reproducible from the session start")
    func speciesIsDeterministic() {
        let a = Bestiary.species(forSessionStartMs: 1_788_010_163_073)
        let b = Bestiary.species(forSessionStartMs: 1_788_010_163_073)
        #expect(a == b)
        #expect((0..<Bestiary.speciesCount).contains(a))
    }
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/BestiaryTests`
Expected: FAIL, „cannot find 'Bestiary' in scope".

- [ ] **Step 3: Minimale Implementierung**

```swift
import Foundation

/// One collected creature.
public nonisolated struct BestiaryEntry: Codable, Equatable {
    public let speciesId: Int
    public let dateMs: Int64
    public let strokesDrawn: Int
    public let strokesTotal: Int
    public let writingSeconds: Double

    public init(speciesId: Int, dateMs: Int64, strokesDrawn: Int,
                strokesTotal: Int, writingSeconds: Double) {
        self.speciesId = speciesId
        self.dateMs = dateMs
        self.strokesDrawn = strokesDrawn
        self.strokesTotal = strokesTotal
        self.writingSeconds = writingSeconds
    }

    public var isComplete: Bool { strokesDrawn >= strokesTotal }
}

public nonisolated enum Bestiary {
    public static let speciesCount = 8

    /// Seeded from the session's start so abandoning and restarting cannot
    /// reroll for a rarer creature.
    public static func species(forSessionStartMs ms: Int64) -> Int {
        var x = UInt64(bitPattern: Int64(ms))
        x ^= x >> 33; x = x &* 0xff51afd7ed558ccd
        x ^= x >> 33; x = x &* 0xc4ceb9fe1a85ec53
        x ^= x >> 33
        return Int(x % UInt64(speciesCount))
    }

    /// Strokes earned by writing time. Pauses hold this still; they never
    /// reduce it, and there is no failure state — a short session simply
    /// leaves a partly drawn creature.
    public static func strokesDrawn(writingSeconds: Double,
                                    targetSeconds: Double,
                                    strokesTotal: Int) -> Int {
        guard targetSeconds > 0, strokesTotal > 0 else { return 0 }
        let per = targetSeconds / Double(strokesTotal)
        return min(strokesTotal, max(0, Int(writingSeconds / per)))
    }
}
```

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Run: wie Step 2. Expected: PASS, 4 Tests.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/Shared/Bestiary.swift watch_streamer/ScrybeTests/BestiaryTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): grow the marginal creature on writing time"
```

---

### Task 4: Kommando-Vokabular

**Files:**
- Modify: `watch_streamer/Shared/WatchCommand.swift`
- Test: `watch_streamer/ScrybeTests/WatchCommandRoutingTests.swift`

**Interfaces:**
- Consumes: nichts.
- Produces: `WatchCommandName.focusStart` (`"focus_start"`), `.focusStop` (`"focus_stop"`).

- [ ] **Step 1: Fehlschlagenden Test schreiben**

An `WatchCommandRoutingTests` anhängen:

```swift
    // A session start that lands minutes late is wrong, not late: it must never
    // fall back to the durable queue.
    @Test("focus commands are live-only operations that bypass the dispatcher")
    func focusCommandRouting() {
        for name in [WatchCommandName.focusStart, .focusStop] {
            #expect(name.transport == .idempotentOperation)
            #expect(name.bypassesRecordingDispatcher)
            #expect(!name.mayFallBackToUserInfo)
            #expect(!name.mayReplaceDurableState)
            #expect(!name.isDiagnostic)
        }
    }
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/WatchCommandRoutingTests`
Expected: FAIL, „type 'WatchCommandName' has no member 'focusStart'".

- [ ] **Step 3: Fälle ergänzen**

In `Shared/WatchCommand.swift` nach `case syncDecisions`:

```swift
    /// Begin a focus session: switch the stream to 50 Hz and consume locally.
    case focusStart = "focus_start"
    /// End a focus session and restore the previous capture configuration.
    case focusStop = "focus_stop"
```

Danach die fünf `switch self`-Blöcke ergänzen, sodass `focusStart`/`focusStop`
in `transport` als `.idempotentOperation` und in `bypassesRecordingDispatcher`
als `true` erscheinen; in `mayReplaceDurableState`, `mayFallBackToUserInfo` und
`isDiagnostic` bleiben sie im `false`-Zweig. Der Compiler erzwingt die
Vollständigkeit, weil die `switch` erschöpfend sind.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Run: wie Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/Shared/WatchCommand.swift watch_streamer/ScrybeTests/WatchCommandRoutingTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): add focus_start and focus_stop to the command vocabulary"
```

---

### Task 5: `FocusSessionStore` — Zustand und Klassifikation

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift`
- Test: `watch_streamer/ScrybeTests/FocusSessionStoreTests.swift`

**Interfaces:**
- Consumes: `ScrybeModel` (Task 1), `FocusStrokes` (Task 2), `Bestiary` (Task 3),
  `PassiveWindowBuilder.append(_:) -> [PassiveWindow]`.
- Produces:
  `@MainActor final class FocusSessionStore: ObservableObject`
  mit `enum Phase: Equatable { case idle, starting, running(startedAt: Date, targetSeconds: Double), finished(BestiaryEntry) }`,
  `@Published private(set) var phase: Phase`,
  `@Published private(set) var decisions: [PassiveDecision]`,
  `var writingSeconds: Double`, `var segments: [FocusSegment]`,
  `func consume(_ samples: [PassiveSample])`,
  `init(classifier: PassiveClassifier? = nil)`.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus session store")
@MainActor
struct FocusSessionStoreTests {

    private struct FixedClassifier: PassiveClassifier {
        let value: Float
        func logit(window: [Float]) throws -> Float { value }
    }

    /// `count` samples at 50 Hz, six channels, starting at t = 0.
    private func samples(_ count: Int) -> [PassiveSample] {
        (0..<count).map { i in
            PassiveSample(timestamp: Double(i) / 50.0, x: 0.1, y: 0.2, z: 0.98)
        }
    }

    @Test("one decision per stride once the first window is full")
    func decisionsFollowStride() {
        let store = FocusSessionStore(classifier: FixedClassifier(value: 1))
        store.beginForTesting(targetSeconds: 1_500)
        store.consume(samples(250))
        #expect(store.decisions.count == 1)
        store.consume(samples(125))
        #expect(store.decisions.count == 2)
    }

    // The viewfinder principle: the daily accounting must never see these.
    @Test("a session writes nothing to the passive decision store")
    func nothingIsPersisted() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("focus-\(UUID().uuidString).jsonl")
        defer { try? FileManager.default.removeItem(at: url) }
        let raw = PassiveDecisionStore(fileURL: url)

        let store = FocusSessionStore(classifier: FixedClassifier(value: 1))
        store.beginForTesting(targetSeconds: 1_500)
        store.consume(samples(500))

        #expect(!store.decisions.isEmpty)
        #expect(raw.allDecisions().isEmpty)
    }
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/FocusSessionStoreTests`
Expected: FAIL, „cannot find 'FocusSessionStore' in scope".

- [ ] **Step 3: Minimale Implementierung**

```swift
import Combine
import Foundation
import SwiftUI

/// A deliberately started writing session.
///
/// Holds everything in memory on purpose. Live and recorder windows never share
/// a `startMs`, so persisting both would double-count the day and idempotency
/// could not catch it. The passive path stays the single source of truth for
/// writing time; the only thing a session leaves behind is one `BestiaryEntry`.
@MainActor
final class FocusSessionStore: ObservableObject {
    static let shared = FocusSessionStore()

    enum Phase: Equatable {
        case idle
        case starting
        case running(startedAt: Date, targetSeconds: Double)
        case finished(BestiaryEntry)
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var decisions: [PassiveDecision] = []

    private var builder = PassiveWindowBuilder(seqLen: 250, strideSamples: 125,
                                               nominalHz: 50)
    private let injected: PassiveClassifier?
    private var classifier: PassiveClassifier?

    init(classifier: PassiveClassifier? = nil) {
        self.injected = classifier
    }

    var writingSeconds: Double {
        decisions.filter(\.writing).reduce(0) { $0 + $1.creditSeconds }
    }

    var segments: [FocusSegment] { FocusStrokes.segments(from: decisions) }

    /// Test seam: enter `running` without the Watch round-trip.
    func beginForTesting(targetSeconds: Double, at date: Date = Date()) {
        reset()
        classifier = injected
        phase = .running(startedAt: date, targetSeconds: targetSeconds)
    }

    /// Feeds samples handed over by `PhoneBridge` while a session runs.
    func consume(_ samples: [PassiveSample]) {
        guard case .running = phase else { return }
        if classifier == nil {
            classifier = injected ?? (try? ScrybeModel(resourceName: "ScrybeActive",
                                                       channels: 6, seqLen: 250))
        }
        guard let classifier else { return }
        for window in builder.append(samples) {
            guard let logit = try? classifier.logit(window: window.values) else { continue }
            decisions.append(PassiveDecision(
                startMs: Int64(window.startTimestamp * 1000),
                endMs: Int64(window.endTimestamp * 1000),
                logit: logit,
                writing: logit >= 0,
                creditSeconds: builder.secondsPerWindow))
        }
    }

    private func reset() {
        decisions.removeAll()
        builder.reset()
    }
}
```

Hinweis: `PassiveSample` trägt drei Achsen. Für die sechs Kanäle wird der
Sample-Typ in Task 6 erweitert; bis dahin liefert der Test drei Achsen und der
Builder verarbeitet sie unverändert.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Run: wie Step 2. Expected: PASS, 2 Tests.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift \
        watch_streamer/ScrybeTests/FocusSessionStoreTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): add the in-memory focus session store"
```

---

### Task 6: Sechs Kanäle im Fensterbau

`PassiveWindowBuilder` baut heute 3-Kanal-Fenster. `ScrybeActive` braucht 6 in
der Reihenfolge `ax, ay, az, rx, ry, rz`.

**Files:**
- Modify: `watch_streamer/Shared/PassiveWindowBuilder.swift`
- Test: `watch_streamer/ScrybeTests/PassiveWindowBuilderTests.swift`

**Interfaces:**
- Produces: `PassiveSample` erhält optionale Gyro-Achsen
  `init(timestamp: TimeInterval, x: Float, y: Float, z: Float, rx: Float = 0, ry: Float = 0, rz: Float = 0)`;
  `PassiveWindowBuilder.init(..., channels: Int = 3)`; `values` ist
  zeilenweise `(seqLen, channels)`.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
    // The model's channel order is fixed by the exported artifact; getting it
    // wrong produces confident nonsense rather than an error.
    @Test("six-channel windows are row-major ax, ay, az, rx, ry, rz")
    func sixChannelLayout() {
        var b = PassiveWindowBuilder(seqLen: 2, strideSamples: 2,
                                     nominalHz: 50, channels: 6)
        let s = (0..<2).map { i in
            PassiveSample(timestamp: Double(i) / 50.0,
                          x: 1, y: 2, z: 3, rx: 4, ry: 5, rz: 6)
        }
        let windows = b.append(s)
        #expect(windows.count == 1)
        #expect(windows[0].values == [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6])
    }
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/PassiveWindowBuilderTests`
Expected: FAIL, „extra argument 'channels' in call".

- [ ] **Step 3: Implementierung**

In `PassiveSample` die drei Gyro-Achsen mit Default `0` ergänzen (bestehende
Aufrufstellen bleiben damit gültig). In `PassiveWindowBuilder` ein
`public let channels: Int` mit Default `3` aufnehmen und beim Befüllen von
`values` je Sample entweder drei oder sechs Werte schreiben:

```swift
        for sample in buffer.prefix(seqLen) {
            values.append(sample.x); values.append(sample.y); values.append(sample.z)
            if channels == 6 {
                values.append(sample.rx); values.append(sample.ry); values.append(sample.rz)
            }
        }
```

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Run: die volle Suite, weil der Passiv-Pfad denselben Builder nutzt:
`... -only-testing:ScrybeTests`
Expected: PASS. Insbesondere `PassiveTrackerEngineTests` muss unverändert grün
sein — der Default `channels: 3` hält den Passiv-Pfad bit-identisch.

- [ ] **Step 5: `FocusSessionStore` auf sechs Kanäle stellen**

In `FocusSessionStore` den Builder ersetzen durch:

```swift
    private var builder = PassiveWindowBuilder(seqLen: 250, strideSamples: 125,
                                               nominalHz: 50, channels: 6)
```

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/Shared/PassiveWindowBuilder.swift \
        watch_streamer/ScrybeTests/PassiveWindowBuilderTests.swift \
        watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift
git diff --cached --name-only
git commit -m "feat(scrybe): let the window builder emit six-channel windows"
```

---

### Task 7: Uhr — 50 Hz und gegenseitiger Ausschluss

**Files:**
- Modify: `watch_streamer/WatchStreamer Watch App/MotionManager.swift`
- Test: `watch_streamer/ScrybeTests/FocusExclusionTests.swift`

**Interfaces:**
- Consumes: `WatchCommandName.focusStart` / `.focusStop` (Task 4).
- Produces: Antwort-Payload `[ok: Bool, error: String?]` auf `focus_start`.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus and recording are exclusive")
struct FocusExclusionTests {

    // Both claim the same sensor stream and the same HKWorkoutSession, and
    // MotionManager deliberately never ends its own.
    @Test("focus_start is refused while a recording runs")
    func focusRefusedDuringRecording() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: true,
                                                     healthKitAuthorized: true)
        #expect(reply.ok == false)
        #expect(reply.error?.isEmpty == false)
    }

    // Without the workout session the stream dies when the wrist lowers, so
    // starting anyway would fail silently halfway through a session.
    @Test("focus_start is refused without workout permission")
    func focusRefusedWithoutHealthKit() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: false,
                                                     healthKitAuthorized: false)
        #expect(reply.ok == false)
    }

    @Test("focus_start is accepted when idle and requests 50 Hz")
    func focusAcceptedWhenIdle() {
        let reply = FocusCommandPolicy.replyForStart(isRecording: false,
                                                     healthKitAuthorized: true)
        #expect(reply.ok)
        #expect(reply.requestedHz == 50)
    }
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/FocusExclusionTests`
Expected: FAIL, „cannot find 'FocusCommandPolicy' in scope".

- [ ] **Step 3: Reine Politik-Funktion plus Verdrahtung**

Neu in `Shared/WatchCommand.swift` (Politik ohne CoreMotion, damit testbar):

```swift
/// Whether a focus session may start, and at what rate.
///
/// Split out of `MotionManager` because the decision is the part worth testing
/// and CoreMotion cannot run in a unit test.
public nonisolated enum FocusCommandPolicy {
    public struct StartReply: Equatable {
        public let ok: Bool
        public let error: String?
        public let requestedHz: Int
    }

    /// The shipped active model was trained on 50 Hz and never saw 100 Hz, so a
    /// session states the rate rather than resampling into it afterwards.
    public static let sessionHz = 50

    public static func replyForStart(isRecording: Bool,
                                     healthKitAuthorized: Bool) -> StartReply {
        guard !isRecording else {
            return StartReply(ok: false,
                              error: "recording in progress",
                              requestedHz: 0)
        }
        // Why refused rather than attempted: without a workout session the
        // motion stream stops as soon as the wrist lowers, and the page would
        // quietly stop growing mid-session with no visible cause.
        guard healthKitAuthorized else {
            return StartReply(ok: false,
                              error: "workout permission missing",
                              requestedHz: 0)
        }
        return StartReply(ok: true, error: nil, requestedHz: sessionHz)
    }
}
```

In `MotionManager.handleCommandOffDispatcher` (dort, wo `syncDecisions`
behandelt wird) die beiden neuen Fälle ergänzen: `focusStart` ruft
`FocusCommandPolicy.replyForStart(isRecording: isRunning, healthKitAuthorized:)`, setzt bei `ok` die
Capture-Rate auf `FocusCommandPolicy.sessionHz` und startet den Motion-Stream;
`focusStop` stoppt ihn und stellt die vorherige Rate wieder her.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Run: wie Step 2. Expected: PASS, 2 Tests.

- [ ] **Step 5: Gerätebuild**

Run: `xcodebuild build -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'generic/platform=iOS' -configuration Debug CODE_SIGNING_ALLOWED=NO`
Expected: `** BUILD SUCCEEDED **` (der Watch-Target wird mitgebaut).

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/Shared/WatchCommand.swift \
        "watch_streamer/WatchStreamer Watch App/MotionManager.swift" \
        watch_streamer/ScrybeTests/FocusExclusionTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): drive focus sessions at 50 Hz, exclusive with recording"
```

---

### Task 8: `PhoneBridge` — Samples während einer Sitzung lokal verbrauchen

**Files:**
- Modify: `watch_streamer/WatchStreamer/PhoneBridge.swift` (bei
  `uploadQueue.append(normalized)`, dort steht bereits der Fan-out
  `IMUDataStore.shared.pushBatch`)

**Interfaces:**
- Consumes: `FocusSessionStore.shared.consume(_:)` (Task 5).

- [ ] **Step 1: Fan-out ergänzen**

Direkt nach `IMUDataStore.shared.pushBatch(...)`:

```swift
                // Why here and not in place of the upload: a focus session is a
                // second reader of the same stream, not a different stream. The
                // study path keeps working unchanged, including its queue.
                FocusSessionStore.shared.consume(
                    PhoneBridge.passiveSamples(from: samples))
```

- [ ] **Step 2: Umwandlung ergänzen**

```swift
    /// Maps a received watch batch onto the model's sample type.
    ///
    /// Channel order is fixed by the exported artifact: ax, ay, az, rx, ry, rz.
    static func passiveSamples(from samples: [[String: Any]]) -> [PassiveSample] {
        samples.compactMap { s in
            guard let ts = WatchPayloadValue.int64(s["ts"]) else { return nil }
            func f(_ key: String) -> Float { Float((s[key] as? Double) ?? 0) }
            return PassiveSample(timestamp: Double(ts) / 1000,
                                 x: f("ax"), y: f("ay"), z: f("az"),
                                 rx: f("rx"), ry: f("ry"), rz: f("rz"))
        }
    }
```

- [ ] **Step 3: Volle Suite**

Run: `... -only-testing:ScrybeTests`
Expected: PASS. `FocusSessionStore.shared` steht auf `.idle`, `consume` ist dann
ein No-op — der Studien-Aufnahmeweg bleibt unverändert.

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer/PhoneBridge.swift
git diff --cached --name-only
git commit -m "feat(scrybe): tee the watch stream into a running focus session"
```

---

### Task 9: Die acht Marginalien

Zeichenarbeit. Ein prozeduraler Generator ist ausdrücklich abgelehnt (Spec §8):
er erzeugt Varianten derselben Form, und genau diese Gleichförmigkeit ist das
Merkmal, das vermieden werden soll.

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/Marginalia.swift`
- Create: `watch_streamer/tools/render_marginalia.swift` (Vorschau-Renderer)
- Test: `watch_streamer/ScrybeTests/MarginaliaTests.swift`

**Interfaces:**
- Produces: `enum Marginalia { static func strokeCount(forSpecies: Int) -> Int; static func strokes(forSpecies: Int) -> [Path]; static let names: [String] }`
  Jeder `Path` ist in einer 100×100-Einheitsbox definiert.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
import Testing
import SwiftUI
@testable import WatchStreamer

@Suite("Marginalia")
struct MarginaliaTests {

    @Test("every species has between six and twelve ordered strokes")
    func strokeCounts() {
        for id in 0..<Bestiary.speciesCount {
            let strokes = Marginalia.strokes(forSpecies: id)
            #expect((6...12).contains(strokes.count))
            #expect(Marginalia.strokeCount(forSpecies: id) == strokes.count)
        }
    }

    @Test("every stroke stays inside the 100x100 box")
    func strokesAreInBounds() {
        for id in 0..<Bestiary.speciesCount {
            for stroke in Marginalia.strokes(forSpecies: id) {
                let b = stroke.boundingRect
                #expect(b.minX >= -0.5 && b.minY >= -0.5)
                #expect(b.maxX <= 100.5 && b.maxY <= 100.5)
            }
        }
    }

    @Test("each species is named")
    func namesMatchCount() {
        #expect(Marginalia.names.count == Bestiary.speciesCount)
    }
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/MarginaliaTests`
Expected: FAIL, „cannot find 'Marginalia' in scope".

- [ ] **Step 3: Erste Art zeichnen und ansehen**

`Marginalia.swift` anlegen mit `names` (acht deutsche Namen, z. B. „Trompeten-Hase",
„Panzerschnecke", „Dreibein-Vogel", „Lesender Fuchs", „Bücherwurm", „Mondhund",
„Federfisch", „Zwei-Kopf-Kranich") und der ersten Art als geordnete `Path`-Liste
in der 100×100-Box.

Dann rendern und **hinsehen**, nicht blind weiterschreiben:

```bash
cd watch_streamer && swift tools/render_marginalia.swift --out /tmp/marginalia.png
```

Der Renderer zeichnet alle Arten als Raster in eine PNG. Diese Datei ansehen,
bevor die nächste Art entsteht. Eine Art gilt erst als fertig, wenn sie im
gerenderten Bild als das erkennbar ist, was ihr Name behauptet.

- [ ] **Step 4: Restliche sieben Arten, je einzeln gerendert und geprüft**

Nach jeder Art erneut rendern und ansehen. Nicht acht Arten schreiben und
einmal am Ende prüfen — dann sehen alle gleich aus.

- [ ] **Step 5: Die Sitzung an das Wesen anschließen**

Erst jetzt, weil `Marginalia` bis hierhin nicht existierte. In
`FocusSessionStore` ergänzen:

```swift
    var currentSpecies: Int {
        guard case .running(let startedAt, _) = phase else { return 0 }
        return Bestiary.species(
            forSessionStartMs: Int64(startedAt.timeIntervalSince1970 * 1000))
    }

    var strokesTotal: Int { Marginalia.strokeCount(forSpecies: currentSpecies) }

    var strokesDrawn: Int {
        guard case .running(_, let target) = phase else { return 0 }
        return Bestiary.strokesDrawn(writingSeconds: writingSeconds,
                                     targetSeconds: target,
                                     strokesTotal: strokesTotal)
    }
```

- [ ] **Step 6: Test laufen lassen, grün bestätigen**

Run: wie Step 2, danach die volle Suite. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/Marginalia.swift \
        watch_streamer/tools/render_marginalia.swift \
        watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift \
        watch_streamer/ScrybeTests/MarginaliaTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): draw eight marginal creatures as ordered strokes"
```

---

### Task 10: `WritingPageView`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/WritingPageView.swift`

**Interfaces:**
- Consumes: `[FocusSegment]` (Task 2), `Marginalia.strokes(forSpecies:)` (Task 9),
  `ScrybeTheme` (`theme.ink`, `theme.paperTop`, `theme.hairline`).
- Produces: `struct WritingPageView: View { init(segments: [FocusSegment], species: Int, strokesDrawn: Int, headMs: Int64) }`

- [ ] **Step 1: View schreiben**

```swift
import SwiftUI

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
    /// One line of page holds this much writing (Spec §6).
    private let secondsPerLine: Double = 120

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60, paused: reduceMotion)) { _ in
            Canvas { context, size in
                drawRules(in: &context, size: size)
                drawCreature(in: &context, size: size)
                for segment in segments {
                    draw(segment, in: &context, size: size)
                }
                if !reduceMotion { drawWetHead(in: &context, size: size) }
            }
        }
        .background(theme.paper)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("Schreibseite dieser Sitzung"))
    }

    private func draw(_ segment: FocusSegment, in context: inout GraphicsContext,
                      size: CGSize) {
        switch segment.kind {
        case .ink:
            // Two layers: a broad outer stroke at 70 % under a narrow core at
            // full strength. That is what gives real ink its dark centre.
            stroke(segment, in: &context, size: size,
                   width: 2.5, opacity: 0.7)
            stroke(segment, in: &context, size: size,
                   width: 1.4, opacity: 1.0)
        case .resting:
            // The pen is still on the page. Never a break: a ten-second look at
            // what you wrote is not an interruption.
            stroke(segment, in: &context, size: size,
                   width: 0.6, opacity: 0.35)
        case .lift:
            // Nothing is drawn; the taper belongs to the preceding ink run and
            // the gap's width is compressed logarithmically.
            break
        case .paragraph:
            break   // consumed by the layout, which starts a new line
        }
    }
}
```

Die Hilfsfunktionen `drawRules`, `drawCreature`, `drawWetHead`, `stroke` und die
Zeit→Punkt-Abbildung (inklusive logarithmischer Lückenstauchung ab 15 s und
Zeilenumbruch ab 60 s) gehören in dieselbe Datei. Maße aus Spec §6:
Zeilenhöhe 32, linker Rand 40, rechter Rand 24, Zeitskala 2 Minuten je Zeile.

Regeln, die im Code als `// Why:`-Kommentar stehen müssen:
- `.ink` → zwei Lagen (Außenstrich 2,5 pt bei 70 %, Kern 1,4 pt bei 100 %)
- `.resting` → Haarlinie 0,6 pt bei 35 %, **kein** Abriss
- `.lift` → Verjüngung über 10–16 pt, Breite logarithmisch gestaucht
- `.paragraph` → Zeilenumbruch mit Einzug plus Serifenziffer 10 pt bei 40 %
- Kopf: Punkt in Echtzeit voraus, dahinter 25-%-Spur über 5 s
- Wesen im linken Rand, `strokesDrawn` Striche von `strokes(forSpecies:)`

- [ ] **Step 2: Vorschau prüfen**

Eine `#Preview` mit einer erfundenen Segmentfolge anlegen, die alle vier
Segmentarten enthält, und im Xcode-Canvas ansehen. Alternativ über den
Simulator-Screenshot prüfen.

- [ ] **Step 3: Bauen**

Run: `xcodebuild build -project watch_streamer/WatchStreamer.xcodeproj -scheme WatchStreamer -destination 'generic/platform=iOS' -configuration Debug CODE_SIGNING_ALLOWED=NO`
Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/WritingPageView.swift
git diff --cached --name-only
git commit -m "feat(scrybe): draw the session as a page of ink"
```

---

### Task 11: `BestiaryStore` und `BestiaryView`

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/BestiaryStore.swift`
- Create: `watch_streamer/WatchStreamer/Scrybe/BestiaryView.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift`
- Test: `watch_streamer/ScrybeTests/BestiaryStoreTests.swift`

**Interfaces:**
- Consumes: `BestiaryEntry` (Task 3).
- Produces: `@MainActor final class BestiaryStore: ObservableObject { init(fileURL: URL); static func defaultFileURL() -> URL; func record(_ entry: BestiaryEntry); func all() -> [BestiaryEntry]; func deleteAll() }`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Bestiary store")
@MainActor
struct BestiaryStoreTests {

    private func tempStore() -> (BestiaryStore, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("bestiary-\(UUID().uuidString).json")
        return (BestiaryStore(fileURL: url), url)
    }

    @Test("entries survive a new store on the same file")
    func entriesPersist() {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.record(BestiaryEntry(speciesId: 3, dateMs: 1_788_000_000_000,
                                   strokesDrawn: 6, strokesTotal: 10,
                                   writingSeconds: 900))
        #expect(BestiaryStore(fileURL: url).all().count == 1)
    }

    @Test("an unfinished creature is kept and marked unfinished")
    func partialIsStored() {
        let (store, url) = tempStore()
        defer { try? FileManager.default.removeItem(at: url) }
        store.record(BestiaryEntry(speciesId: 1, dateMs: 1, strokesDrawn: 4,
                                   strokesTotal: 10, writingSeconds: 600))
        let entry = try! #require(store.all().first)
        #expect(!entry.isComplete)
    }
}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/BestiaryStoreTests`
Expected: FAIL, „cannot find 'BestiaryStore' in scope".

- [ ] **Step 3: Store implementieren**

```swift
import Combine
import Foundation

/// The collected creatures. One record per session — never a window and never
/// a second of writing time, so the daily accounting stays with the passive
/// path (Spec §2).
@MainActor
final class BestiaryStore: ObservableObject {
    static let shared = BestiaryStore(fileURL: BestiaryStore.defaultFileURL())

    @Published private(set) var entries: [BestiaryEntry] = []

    private let fileURL: URL

    init(fileURL: URL) {
        self.fileURL = fileURL
        entries = (try? JSONDecoder().decode([BestiaryEntry].self,
                                             from: Data(contentsOf: fileURL))) ?? []
    }

    /// Mirrors `FocusArchive.defaultFileURL()` so both live in one place.
    static func defaultFileURL() -> URL {
        let fm = FileManager.default
        let base = (try? fm.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                appropriateFor: nil, create: true))
            ?? fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("bestiary.json")
    }

    func record(_ entry: BestiaryEntry) {
        entries.append(entry)
        write()
    }

    func all() -> [BestiaryEntry] { entries }

    func deleteAll() {
        entries.removeAll()
        try? FileManager.default.removeItem(at: fileURL)
    }

    private func write() {
        guard let data = try? JSONEncoder().encode(entries) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}
```

- [ ] **Step 4: `BestiaryView` und Einhängung**

Raster aus Rändern, je Wesen plus Datum, unfertige mit den gezeichneten Strichen
und ohne Zusatzkennzeichnung — das halb gezeichnete Tier ist selbsterklärend.
In `HistoryView` unter der bestehenden Liste einhängen.

- [ ] **Step 5: Test laufen lassen, grün bestätigen**

Run: `... -only-testing:ScrybeTests` Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Stores/BestiaryStore.swift \
        watch_streamer/WatchStreamer/Scrybe/BestiaryView.swift \
        watch_streamer/WatchStreamer/Scrybe/HistoryView.swift \
        watch_streamer/ScrybeTests/BestiaryStoreTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): collect finished and unfinished creatures"
```

---

### Task 12: `FocusSessionView` — der Bildschirm

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/FocusSessionView.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/TodayView.swift` (Einstieg)
- Modify: `watch_streamer/WatchStreamer/ServerCommandListener.swift` (Start/Stopp senden)

**Interfaces:**
- Consumes: `FocusSessionStore` (Task 5), `WritingPageView` (Task 10),
  `BestiaryStore` (Task 11), `WatchCommandName.focusStart/.focusStop` (Task 4).

- [ ] **Step 1: Start und Stopp mit Zeitgrenze**

In `ServerCommandListener` nach dem Muster von
`WatchDecisionSync.requestSync(timeout:)`:

```swift
    /// Asks the Watch to begin a focus session.
    ///
    /// Why a deadline: `sendMessage` does not guarantee that either handler
    /// runs. Without it the caller waits forever and the screen sits in
    /// `starting` with no way back — the failure this project already shipped
    /// once on pull-to-refresh.
    func startFocusSession(timeout: TimeInterval = 8) async -> Bool {
        await withCheckedContinuation { continuation in
            var resumed = false
            let deadline = DispatchWorkItem {
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: false)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout, execute: deadline)
            forwardToWatch([WatchPayloadKey.command: WatchCommandName.focusStart.rawValue,
                            WatchPayloadKey.commandID: UUID().uuidString]) { reply in
                guard !resumed else { return }
                resumed = true
                deadline.cancel()
                continuation.resume(returning: reply[WatchPayloadKey.ok] as? Bool ?? false)
            }
        }
    }
```

- [ ] **Step 2: Bildschirm bauen**

Zieldauer-Wahl (15 / 25 / 45 min), Start-Knopf, laufende Sitzung mit
`WritingPageView`, Beenden-Knopf. Beim Beenden `BestiaryEntry` aus
`FocusSessionStore` bilden und in `BestiaryStore` ablegen.

Haptik: ein weiches `UIImpactFeedbackGenerator(style: .soft)` beim Übergang von
`.ink` zu `.lift` — nicht bei `.resting`, sonst vibriert jede Denkpause.

- [ ] **Step 3: Harte Obergrenze**

60 Minuten, danach automatischer Stopp. Der Sensorstrom kostet Handgelenk-Akku;
eine vergessene Sitzung darf nicht bis zum leeren Akku laufen.

- [ ] **Step 4: Bauen und volle Suite**

Run: Build (`generic/platform=iOS`) und `... -only-testing:ScrybeTests`
Expected: beide grün.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/FocusSessionView.swift \
        watch_streamer/WatchStreamer/Scrybe/TodayView.swift \
        watch_streamer/WatchStreamer/ServerCommandListener.swift
git diff --cached --name-only
git commit -m "feat(scrybe): add the focus session screen"
```

---

### Task 13: Ernte beim Ziehen

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/FocusStore.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/Components/InkRefreshControl.swift`
- Test: `watch_streamer/ScrybeTests/FocusStoreLocalTests.swift`

**Interfaces:**
- Produces: `FocusStore.harvestDelta(now:) -> Double`, `FocusStore.markHarvested()`

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```swift
    // The number shown on a pull is what arrived since the user last looked,
    // so two pulls in a row must not claim the same minutes twice.
    @Test("a second pull claims no minutes")
    func harvestIsNotDoubleCounted() async {
        let (store, _, _) = tempStore()
        await store.ingest(windows(0, count: 8))
        await store.refresh()
        let first = store.harvestDelta()
        #expect(first == 20.0)
        store.markHarvested()
        #expect(store.harvestDelta() == 0)
    }

    @Test("the first ever pull does not claim the whole history")
    func firstRunClaimsNothing() async {
        let (store, _, _) = tempStore()
        await store.ingest(windows(-3, count: 8) + windows(0, count: 8))
        await store.refresh()
        store.primeHarvestBaseline()
        #expect(store.harvestDelta() == 0)
    }
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `... -only-testing:ScrybeTests/FocusStoreLocalTests`
Expected: FAIL, „value of type 'FocusStore' has no member 'harvestDelta'".

- [ ] **Step 3: Implementierung**

`lastHarvestedSeconds` als `Double` in `UserDefaults`
(`"focusStore.lastHarvestedSeconds"`), `harvestDelta()` =
`max(0, todayWritingSeconds - lastHarvestedSeconds)`, `markHarvested()` setzt
den Stand, `primeHarvestBaseline()` initialisiert ihn beim ersten Start.

- [ ] **Step 4: Kapsel und Ring**

In `InkRefreshControl` die Beschriftung im Fall `.updated` auf
`„+14 Minuten"` umstellen, wenn ein Delta vorliegt, sonst die bisherige Zeile.
Der Ring animiert auf den neuen Wert mit
`.timingCurve(0.2, 0.9, 0.3, 1.0, duration: 1.4)` — schneller Anfluss, langes
Auslaufen. Bei Reduce Motion ein Crossfade plus Zahl.

- [ ] **Step 5: Test laufen lassen, grün bestätigen**

Run: `... -only-testing:ScrybeTests` Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Stores/FocusStore.swift \
        watch_streamer/WatchStreamer/Scrybe/Components/InkRefreshControl.swift \
        watch_streamer/ScrybeTests/FocusStoreLocalTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): flow newly detected minutes into the ring on a pull"
```

---

### Task 14: Ringzahl und Abschluss

**Files:**
- Modify: `watch_streamer/WatchStreamer/Scrybe/Components/InkRing.swift`

- [ ] **Step 1: Gewicht der Ringzahl ändern**

```swift
                        .font(.system(.largeTitle, design: .serif).weight(.regular))
```

Begründung als `// Why:`-Kommentar: Serifen tragen Hierarchie über Größe, nicht
über Fettung; Bold plus rund plus zentriert ist der Fitness-App-Reflex.

- [ ] **Step 2: Volle Suite und Gerätebuild**

Run: `... -only-testing:ScrybeTests` und Build für `generic/platform=iOS`.
Expected: beide grün.

- [ ] **Step 3: Auf beide Geräte ausrollen und ansehen**

```bash
xcrun devicectl device install app --device <iphone-udid> <app>
xcrun devicectl device install app --device <watch-udid> "<app>/Watch/WatchStreamer Watch App.app"
```

Eine echte Sitzung über fünf Minuten laufen lassen und prüfen: wächst die Linie
gleichmäßig, überlebt eine Zehn-Sekunden-Lesepause als Haarlinie, wächst das
Wesen, landet nach dem Beenden ein Eintrag im Bestiarium.

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/InkRing.swift
git diff --cached --name-only
git commit -m "style(scrybe): set the ring figure in regular serif"
```
