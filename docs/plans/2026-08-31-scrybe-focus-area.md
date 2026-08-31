# Scrybe Fokus-Bereich Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Fokus-Sitzung wird ein eigener Tab, der als fertige Seite öffnet statt als Formular, mit einem Ziel, das ein antippbares Wort ist, und mit Start- und Stopp-Ausgängen, die sagen, was wirklich passiert ist.

**Architecture:** Die Zustandslogik bleibt im `FocusSessionStore` (bewusst nur im Speicher); der Grund für ein Sitzungsende wird ein `FinishReason` am Zustand statt ein Meldungstext. Der Zustand einer laufenden Sitzung wird nach einem App-Neustart bei der Uhr erfragt (`capture_mode` im 1-Hz-Poll), nicht telefonseitig persistiert. `FocusSessionView` wird in vier Views plus eine geteilte Zeichenkomponente zerlegt.

**Tech Stack:** Swift 5 (Sprachmodus), SwiftUI, iOS 16 / watchOS 10.6, WatchConnectivity, Swift Testing (`@Suite`/`@Test`/`#expect`), Xcode-Projekt `watch_streamer/WatchStreamer.xcodeproj`.

**Spec:** `docs/specs/2026-08-31-scrybe-launch-fokus-tab-design.md`

## Global Constraints

- **Sprache:** Code, Kommentare, Commit-Messages und Testnamen auf Englisch. Nutzersichtbare Strings auf Deutsch, über `String(localized:)` und mit englischer Übersetzung in `watch_streamer/WatchStreamer/Localizable.xcstrings` (Quellsprache `de`).
- **Kommentare:** nur `// Why:`-Kommentare für nicht-offensichtliche Zwänge. Keine Beschreibung offensichtlicher Mechanik.
- **Dauerbereich:** 5 bis 120 Minuten, ganze Zahlen. Presets 15 / 25 / 45.
- **Hard-Cap:** `FocusCommandPolicy.sessionCapSeconds` = 120 Minuten, an beiden Enden erzwungen.
- **Fortschrittsformel:** `max(0, Bestiary.secondsPerCreature − BestiaryStore.creatureInProgress().writingSeconds)`, identisch in Bereit-, Lauf- und Fertig-Zustand.
- **`FocusSessionStore` bleibt in-memory.** Live- und Recorder-Fenster teilen nie ein `startMs`; ein Persistieren würde den Tag doppelt zählen.
- **Der Start hängt nicht am Server.** `focus_start`/`focus_stop` sind lokale WatchConnectivity-Fälle.
- **Tests:** Swift Testing, Ziel `ScrybeTests`. Ausführen mit einer Simulator-UDID, nicht mit einem Namen — der Standard `OS:latest` trifft sonst einen Simulator ohne passende OS-Version.
- **Testlauf-Kommando:**
  `xcodebuild -project watch_streamer/WatchStreamer.xcodeproj -scheme "WatchStreamer" -destination 'id=<simulator-udid>' -only-testing:ScrybeTests test`
- **Gerätebuild:**
  `xcodebuild -project watch_streamer/WatchStreamer.xcodeproj -scheme "WatchStreamer" -destination 'generic/platform=iOS' -configuration Debug build`
- **Niemals Probandendaten committen.** Vor jedem Commit `git diff --cached --name-only` prüfen; nichts unter `data/` oder `alldata/` stagen.

## File Structure

| Datei | Verantwortung |
|---|---|
| `watch_streamer/Shared/WatchCommand.swift` | Transport-Vertrag: `capture_mode`-Schlüssel, Cap-Konstante, Start-/Stopp-Ausgänge |
| `watch_streamer/WatchStreamer Watch App/MotionManager.swift` | Füllt `capture_mode` in die Poll-Antwort |
| `watch_streamer/WatchStreamer/Stores/ScrybeSettings.swift` | `focusDurationKey` + Default |
| `watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift` | `FinishReason`, optionales Ziel, injizierbarer Cap, Wiederaufnahme |
| `watch_streamer/WatchStreamer/Scrybe/Logic/FocusProgress.swift` | *(neu)* Die eine Fortschrittsformel |
| `watch_streamer/WatchStreamer/Scrybe/Logic/FocusDurationInput.swift` | *(neu)* Validierung der freien Dauer |
| `watch_streamer/WatchStreamer/Scrybe/Components/CreatureCanvas.swift` | *(neu, aus `BestiaryView` gezogen)* Kreatur in beliebiger Größe |
| `watch_streamer/WatchStreamer/Scrybe/FocusTabView.swift` | *(neu)* `NavigationStack` + Zustandsweiche |
| `watch_streamer/WatchStreamer/Scrybe/FocusReadyView.swift` | *(neu)* Die Bühne: Seite, Kreatur, Sätze, Start |
| `watch_streamer/WatchStreamer/Scrybe/FocusDurationSheet.swift` | *(neu)* Presets, freies Feld, „einfach schreiben" |
| `watch_streamer/WatchStreamer/Scrybe/FocusOutcomeView.swift` | *(neu)* Start-/Stopp-Ausgänge, Fertig |
| `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift` | Vier Tabs, Header-Sichtbarkeit |
| `watch_streamer/WatchStreamer/Scrybe/TodayView.swift` | Karte raus, Statuszeile rein |
| `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift` | „Verlauf öffnen" |
| `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift` | Gibt `NavigationStack` und Bestiarium ab |

`FocusSessionView.swift` wird am Ende gelöscht; sein Inhalt verteilt sich auf die vier neuen Views.

---

### Task 1: `capture_mode` im Watch-Poll

Der Poll trägt heute `is_running`, das nicht zwischen Studien-Aufnahme und Fokus-Sitzung unterscheidet. Ohne diese Unterscheidung kann die App nach einem Neustart keine laufende Sitzung wiederfinden (Spec §8.1).

**Files:**
- Modify: `watch_streamer/Shared/WatchCommand.swift` (enum `WatchPayloadKey.Status`, ab Zeile 131)
- Modify: `watch_streamer/WatchStreamer Watch App/MotionManager.swift` (Poll-Antwort)
- Test: `watch_streamer/ScrybeTests/CaptureModeTests.swift` *(neu)*

**Interfaces:**
- Produces: `WatchPayloadKey.Status.captureMode`, `WatchPayloadKey.Status.focusStartedAtMs`, `enum CaptureMode: String { case idle, recording, focus }`, `CaptureMode.from(poll:) -> CaptureMode`, `CaptureMode.focusStartedAtMs(poll:) -> Int64?`

- [ ] **Step 1: Write the failing test**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Capture mode in the poll")
struct CaptureModeTests {

    @Test func focusPollCarriesModeAndStart() {
        let poll: [String: Any] = [
            WatchPayloadKey.Status.captureMode: "focus",
            WatchPayloadKey.Status.focusStartedAtMs: Int64(1_724_000_000_000),
        ]
        #expect(CaptureMode.from(poll: poll) == .focus)
        #expect(CaptureMode.focusStartedAtMs(poll: poll) == 1_724_000_000_000)
    }

    /// Why: a study recording must never be mistaken for a focus session —
    /// resuming one would let the consumer feature end a proband run.
    @Test func recordingIsNotFocus() {
        let poll: [String: Any] = [WatchPayloadKey.Status.captureMode: "recording"]
        #expect(CaptureMode.from(poll: poll) == .recording)
        #expect(CaptureMode.focusStartedAtMs(poll: poll) == nil)
    }

    /// An older Watch build sends no mode at all. It must read as idle, not
    /// crash and not resume.
    @Test func missingModeIsIdle() {
        #expect(CaptureMode.from(poll: [:]) == .idle)
    }

    @Test func unknownModeIsIdle() {
        let poll: [String: Any] = [WatchPayloadKey.Status.captureMode: "banana"]
        #expect(CaptureMode.from(poll: poll) == .idle)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `xcodebuild -project watch_streamer/WatchStreamer.xcodeproj -scheme "WatchStreamer" -destination 'id=<simulator-udid>' -only-testing:ScrybeTests/CaptureModeTests test`
Expected: FAIL — `cannot find 'CaptureMode' in scope`

- [ ] **Step 3: Write minimal implementation**

In `watch_streamer/Shared/WatchCommand.swift`, inside `enum WatchPayloadKey.Status`, after `fallback`:

```swift
        /// What the Watch's sensors are doing right now. `is_running` cannot
        /// answer this: it is true for a study recording and for a focus
        /// session alike, and resuming the wrong one would end a proband run.
        public static let captureMode = "capture_mode"
        /// Unix ms the focus session began, present only when `capture_mode`
        /// is `focus`. The phone holds no copy — the store is in-memory on
        /// purpose — so this is the only way back after a force-quit.
        public static let focusStartedAtMs = "focus_started_at_ms"
```

At file scope in the same file:

```swift
/// What the Watch's sensors are doing, as read from a poll reply.
public nonisolated enum CaptureMode: String, Sendable, CaseIterable {
    case idle
    case recording
    case focus

    /// Why idle on anything unrecognised: an older Watch build sends no mode,
    /// and a build that sends one this app does not know is not a session this
    /// app may adopt.
    public static func from(poll: [String: Any]) -> CaptureMode {
        guard let raw = poll[WatchPayloadKey.Status.captureMode] as? String,
              let mode = CaptureMode(rawValue: raw) else { return .idle }
        return mode
    }

    public static func focusStartedAtMs(poll: [String: Any]) -> Int64? {
        guard from(poll: poll) == .focus else { return nil }
        return WatchPayloadValue.int64(poll[WatchPayloadKey.Status.focusStartedAtMs])
    }
}
```

If `WatchPayloadValue` has no `int64` helper, add one beside its existing `bool`/`double` helpers:

```swift
    public static func int64(_ value: Any?) -> Int64? {
        if let v = value as? Int64 { return v }
        if let v = value as? Int { return Int64(v) }
        if let v = value as? Double { return Int64(v) }
        if let v = value as? NSNumber { return v.int64Value }
        return nil
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: PASS, 4 tests.

- [ ] **Step 5: Fill the field on the Watch**

In `watch_streamer/WatchStreamer Watch App/MotionManager.swift`, in the poll-status payload that already sets `WatchPayloadKey.Status.isRunning` (around line 1143), add:

```swift
                WatchPayloadKey.Status.captureMode: currentCaptureMode.rawValue,
```

and, where the Watch knows a focus session's start, add `WatchPayloadKey.Status.focusStartedAtMs`. Add the derivation next to the existing focus-session state:

```swift
    /// Why derived rather than stored: `isRunning` plus focus ownership is
    /// already the truth; a second stored flag could disagree with it.
    private var currentCaptureMode: CaptureMode {
        if focusSessionStartedAtMs != nil { return .focus }
        return isRunning ? .recording : .idle
    }
```

Use the Watch's existing focus-session start timestamp; if none is stored yet, store the value `focus_start` already receives at the point it accepts the command.

- [ ] **Step 6: Run the full suite and both builds**

Run: the full `-only-testing:ScrybeTests test` command, then the iOS device build, then the watchOS build.
Expected: all green, `** TEST SUCCEEDED **` and `** BUILD SUCCEEDED **`.

- [ ] **Step 7: Commit**

```bash
git add "watch_streamer/Shared/WatchCommand.swift" \
        "watch_streamer/WatchStreamer Watch App/MotionManager.swift" \
        watch_streamer/ScrybeTests/CaptureModeTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): let the poll say what the sensors are doing"
```

---

### Task 2: Hard-Cap auf 120 Minuten, prüfbar ohne zwei Stunden

Der Cap steigt, und die Prüfung darf nicht die Produktionskonstante abwarten (Spec §5).

**Files:**
- Modify: `watch_streamer/Shared/WatchCommand.swift:275` (`sessionCapSeconds`)
- Modify: `watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift` (Cap injizierbar)
- Test: `watch_streamer/ScrybeTests/FocusSessionStoreTests.swift`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `FocusSessionStore.init(capSeconds: TimeInterval = FocusCommandPolicy.sessionCapSeconds, …)`

- [ ] **Step 1: Write the failing test**

Add to `FocusSessionStoreTests`:

```swift
    /// Why an injected cap: the shipped value is two hours. Testing the
    /// behaviour against the constant would cost that long per run, so the
    /// test proves the mechanism and the device check proves the number.
    @Test func sessionEndsAtTheInjectedCap() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 0.2, bestiary: bestiary)

        store.beginForTesting(targetSeconds: 3600)
        #expect(store.isActive)

        try await Task.sleep(nanoseconds: 400_000_000)
        #expect(!store.isActive)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `… -only-testing:ScrybeTests/FocusSessionStoreTests/sessionEndsAtTheInjectedCap test`
Expected: FAIL — no initialiser takes `capSeconds`.

- [ ] **Step 3: Write minimal implementation**

In `Shared/WatchCommand.swift`, change the constant and extend its comment:

```swift
    /// Longest a focus session may stream before it is ended.
    ///
    /// Shared rather than defined twice because both ends enforce it: the phone
    /// for the clean stop, the Watch as the floor under it. A force-quit voids
    /// every phone-side path while the workout session keeps the sensors
    /// running, so the cap also has to live where the sensor does.
    ///
    /// Raised from one hour to two on 2026-08-31 so the app can offer the long
    /// sessions its duration picker allows. The price is stated rather than
    /// hidden: the window in which a crashed phone leaves the Watch measuring
    /// doubles.
    public static let sessionCapSeconds: TimeInterval = 120 * 60
```

In `FocusSessionStore`, take the cap as an injected value:

```swift
    private let capSeconds: TimeInterval

    init(capSeconds: TimeInterval = FocusCommandPolicy.sessionCapSeconds,
         bestiary: BestiaryStore? = nil,
         classifier: PassiveClassifier? = nil) {
        self.capSeconds = capSeconds
        // … existing initialisation, unchanged
    }
```

Replace every use of `FocusCommandPolicy.sessionCapSeconds` inside the store with `capSeconds`. Keep the existing `shared` singleton using the default.

- [ ] **Step 4: Run test to verify it passes**

Run the command from Step 2.
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Expected: all existing tests still green — the default keeps prior behaviour except for the raised number.

- [ ] **Step 6: Commit**

```bash
git add "watch_streamer/Shared/WatchCommand.swift" \
        watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift \
        watch_streamer/ScrybeTests/FocusSessionStoreTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): raise the session cap and make it testable"
```

---

### Task 3: `FinishReason` — der Grund gehört an den Zustand

Heute steht der Grund nur im Meldungstext, also kann keine Ansicht darauf verzweigen und kein Test ihn prüfen (Spec §8).

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift:26-34` (`Phase`) und die Endpfade
- Test: `watch_streamer/ScrybeTests/FocusSessionStoreTests.swift`

**Interfaces:**
- Produces: `FocusSessionStore.FinishReason` mit `user`, `hardCap`, `studyPreemption`, `watchFailure`, `stopUnconfirmed`; `FocusSessionStore.finishReason: FinishReason?`

- [ ] **Step 1: Write the failing test**

```swift
    @Test func endingReportsWhoEndedIt() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        store.beginForTesting(targetSeconds: 1500)
        store.end()
        #expect(store.finishReason == .user)
    }

    /// Why this one matters most: a study recording taking the Watch is the
    /// one ending the user did not cause and cannot see coming.
    @Test func preemptionIsNamedAsPreemption() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        store.beginForTesting(targetSeconds: 1500)
        store.watchPreemptedByRecording()
        #expect(store.finishReason == .studyPreemption)
    }

    @Test func workoutFailureIsNamedAsWatchFailure() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        store.beginForTesting(targetSeconds: 1500)
        store.watchWorkoutFailed()
        #expect(store.finishReason == .watchFailure)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `value of type 'FocusSessionStore' has no member 'finishReason'`.

- [ ] **Step 3: Write minimal implementation**

```swift
    /// Why the ending is a value and not a sentence: the screen branches on
    /// it, and a test can assert it. A message string can only be compared to
    /// itself.
    enum FinishReason: Equatable {
        case user
        case hardCap
        case studyPreemption
        case watchFailure
        case stopUnconfirmed
    }

    @Published private(set) var finishReason: FinishReason?
```

Set it at each ending: `end()` → `.user`; the cap task → `.hardCap`; `watchPreemptedByRecording()` → `.studyPreemption`; `watchWorkoutFailed()` → `.watchFailure`; the unconfirmed-stop path → `.stopUnconfirmed`. Clear it to `nil` in `returnToIdle()` and at the start of `begin`.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 3 new tests.

- [ ] **Step 5: Run the full suite**

Expected: green. `stopUnconfirmed` keeps its existing meaning and tests.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift \
        watch_streamer/ScrybeTests/FocusSessionStoreTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): make the ending a state, not a sentence"
```

---

### Task 4: Eine Sitzung ohne Ziel

`Phase.running` verlangt heute ein Ziel. „Einfach schreiben" braucht ein Datenmodell, keine Parole (Spec §6).

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift:29` (`Phase.running`), `begin`, `beginForTesting`
- Test: `watch_streamer/ScrybeTests/FocusSessionStoreTests.swift`

**Interfaces:**
- Consumes: `FinishReason` aus Task 3, `capSeconds` aus Task 2
- Produces: `case running(startedAt: Date, targetSeconds: Double?)`, `func begin(targetSeconds: Double?, at: Date = Date())`

- [ ] **Step 1: Write the failing test**

```swift
    /// Why: the goal was always decorative — it fills a subtitle. Making it
    /// optional makes that visible instead of implying a countdown.
    @Test func aGoallessSessionRunsAndEndsOnlyWhenAsked() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        store.begin(targetSeconds: nil)
        guard case .running(_, let target) = store.phase else {
            Issue.record("expected running, got \(store.phase)"); return
        }
        #expect(target == nil)
        #expect(store.isActive)

        store.end()
        #expect(store.finishReason == .user)
    }

    /// The cap does not hang off the goal, so a goalless session still ends.
    @Test func aGoallessSessionStillObeysTheCap() async throws {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 0.2, bestiary: bestiary)

        store.begin(targetSeconds: nil)
        try await Task.sleep(nanoseconds: 400_000_000)
        #expect(!store.isActive)
        #expect(store.finishReason == .hardCap)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `nil` is not convertible to `Double`.

- [ ] **Step 3: Write minimal implementation**

```swift
        case running(startedAt: Date, targetSeconds: Double?)
```

```swift
    /// `nil` means the session has no goal: it ends when the user says so or
    /// when the cap does — never at a chosen value, because there is none.
    func begin(targetSeconds: Double?, at date: Date = Date()) {
```

Update `beginForTesting` to take `Double?` as well, and update every `case .running(let startedAt, let targetSeconds)` consumer to handle `nil`.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Fix any call site the compiler flags. Expected: green.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift \
        watch_streamer/ScrybeTests/FocusSessionStoreTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): let a session run without a goal"
```

---

### Task 5: Ein eigener Schlüssel für die Fokusdauer

Die gewählte Dauer muss den App-Start überleben, darf aber nicht mit dem Tagesziel kollidieren — und muss vom Zurücksetzen erfasst werden (Spec §6).

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/ScrybeSettings.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/ProfileView.swift:265-267` (Lösch-Liste)
- Test: `watch_streamer/ScrybeTests/ScrybeSettingsTests.swift` *(neu, falls nicht vorhanden)*

**Interfaces:**
- Produces: `ScrybeSettings.focusDurationKey`, `ScrybeSettings.defaultFocusMinutes`

- [ ] **Step 1: Write the failing test**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Scrybe settings keys")
struct ScrybeSettingsTests {

    /// Why: the focus duration is not the daily goal. Sharing a key would let
    /// picking a 25-minute session rewrite the day's target.
    @Test func focusDurationHasItsOwnKey() {
        #expect(ScrybeSettings.focusDurationKey != ScrybeSettings.goalKey)
        #expect(ScrybeSettings.defaultFocusMinutes == 25)
    }

    /// "Delete all local data" must mean it. A key left behind is the class of
    /// mismatch between promise and storage that the privacy pass closed.
    @Test func focusDurationIsErasedByReset() {
        #expect(ScrybeSettings.resettableKeys.contains(ScrybeSettings.focusDurationKey))
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `focusDurationKey` and `resettableKeys` do not exist.

- [ ] **Step 3: Write minimal implementation**

In `ScrybeSettings.swift`:

```swift
    // Length of a deliberately started focus session, in whole minutes.
    // Separate from `goalKey`: that one is the day's target, this one is the
    // last session length, and the ready screen opens with it so it never has
    // to ask.
    static let focusDurationKey = "scrybe.focusDurationMinutes"
    static let defaultFocusMinutes = 25

    /// Every key "delete all local data" must remove. Kept here rather than
    /// inline in the view so a new setting cannot be added without a place
    /// that erases it.
    static let resettableKeys = [
        goalKey, reminderEnabledKey, reminderMinutesKey,
        languageKey, weekStartKey, focusDurationKey,
    ]
```

In `ProfileView.swift`, replace the inline array at 265-267 with:

```swift
        ScrybeSettings.resettableKeys.forEach { d.removeObject(forKey: $0) }
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 2 tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Stores/ScrybeSettings.swift \
        watch_streamer/WatchStreamer/Scrybe/ProfileView.swift \
        watch_streamer/ScrybeTests/ScrybeSettingsTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): give the focus duration its own key"
```

---

### Task 6: Die Fortschrittsformel, einmal

Bereit-, Lauf- und Fertig-Zustand müssen denselben Wert zeigen, und die Formel darf nach 30 Minuten nicht negativ werden (Spec §7).

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/FocusProgress.swift`
- Test: `watch_streamer/ScrybeTests/FocusProgressTests.swift` *(neu)*

**Interfaces:**
- Produces: `enum FocusProgress { static func remainingSeconds(writingSeconds: Double) -> Double; static func exceedsCreature(remainingSeconds: Double, sessionSeconds: Double?) -> Bool }`

- [ ] **Step 1: Write the failing test**

```swift
import Testing
@testable import WatchStreamer

@Suite("Focus progress preview")
struct FocusProgressTests {

    @Test func remainingCountsDownFromThirtyMinutes() {
        #expect(FocusProgress.remainingSeconds(writingSeconds: 0) == 30 * 60)
        #expect(FocusProgress.remainingSeconds(writingSeconds: 600) == 24 * 60)
    }

    /// Why the clamp: past the creature's thirty minutes the subtraction goes
    /// negative and the sentence would promise a remaining time below zero.
    @Test func remainingNeverGoesNegative() {
        #expect(FocusProgress.remainingSeconds(writingSeconds: 31 * 60) == 0)
        #expect(FocusProgress.remainingSeconds(writingSeconds: 10_000) == 0)
    }

    @Test func aLongerSessionSaysItStartsANewOne() {
        #expect(FocusProgress.exceedsCreature(remainingSeconds: 12 * 60,
                                              sessionSeconds: 25 * 60))
        #expect(!FocusProgress.exceedsCreature(remainingSeconds: 30 * 60,
                                               sessionSeconds: 15 * 60))
    }

    /// A goalless session makes no claim about finishing anything.
    @Test func noGoalMakesNoClaim() {
        #expect(!FocusProgress.exceedsCreature(remainingSeconds: 60,
                                               sessionSeconds: nil))
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `cannot find 'FocusProgress' in scope`.

- [ ] **Step 3: Write minimal implementation**

```swift
import Foundation

/// How much of the creature in progress is still undrawn.
///
/// One function, three callers: the ready screen, the running screen and the
/// finished screen must not disagree about the same number. The input is
/// always `BestiaryStore.creatureInProgress().writingSeconds` — the store
/// defines that as the creature the next credited second grows, so the value
/// is read after any species change rather than before it.
enum FocusProgress {

    static func remainingSeconds(writingSeconds: Double) -> Double {
        max(0, Bestiary.secondsPerCreature - writingSeconds)
    }

    /// Whether the chosen session would finish this creature and begin another.
    /// A goalless session says nothing: it has no length to compare.
    static func exceedsCreature(remainingSeconds: Double,
                                sessionSeconds: Double?) -> Bool {
        guard let sessionSeconds else { return false }
        return sessionSeconds > remainingSeconds
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Logic/FocusProgress.swift \
        watch_streamer/ScrybeTests/FocusProgressTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): give the progress sentence one formula"
```

---

### Task 7: Die freie Dauer validieren

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/FocusDurationInput.swift`
- Test: `watch_streamer/ScrybeTests/FocusDurationInputTests.swift` *(neu)*

**Interfaces:**
- Produces: `enum FocusDurationInput { static let range: ClosedRange<Int>; static func parse(_ text: String) -> Result<Int, Failure>; enum Failure: Equatable { case empty, notAWholeNumber, outOfRange } }`

- [ ] **Step 1: Write the failing test**

```swift
import Testing
@testable import WatchStreamer

@Suite("Focus duration input")
struct FocusDurationInputTests {

    @Test func acceptsWholeMinutesInRange() {
        #expect(FocusDurationInput.parse("5") == .success(5))
        #expect(FocusDurationInput.parse("25") == .success(25))
        #expect(FocusDurationInput.parse("120") == .success(120))
        #expect(FocusDurationInput.parse(" 40 ") == .success(40))
    }

    @Test func rejectsOutsideTheRange() {
        #expect(FocusDurationInput.parse("4") == .failure(.outOfRange))
        #expect(FocusDurationInput.parse("121") == .failure(.outOfRange))
        #expect(FocusDurationInput.parse("0") == .failure(.outOfRange))
    }

    /// Why not round a decimal: the field says minutes, and silently turning
    /// 12.6 into 13 is the app deciding something the user typed differently.
    @Test func rejectsWhatIsNotAWholeNumber() {
        #expect(FocusDurationInput.parse("12.5") == .failure(.notAWholeNumber))
        #expect(FocusDurationInput.parse("abc") == .failure(.notAWholeNumber))
    }

    @Test func rejectsEmpty() {
        #expect(FocusDurationInput.parse("") == .failure(.empty))
        #expect(FocusDurationInput.parse("   ") == .failure(.empty))
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `cannot find 'FocusDurationInput' in scope`.

- [ ] **Step 3: Write minimal implementation**

```swift
import Foundation

/// Validates the free duration field. Pure, so the sheet stays a view.
enum FocusDurationInput {

    /// Below five minutes is not a session; the ceiling is the hard cap in
    /// `FocusCommandPolicy.sessionCapSeconds`, and offering more than the
    /// Watch will run would promise a length it then cuts.
    static let range = 5...120

    enum Failure: Equatable {
        case empty
        case notAWholeNumber
        case outOfRange
    }

    static func parse(_ text: String) -> Result<Int, Failure> {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return .failure(.empty) }
        guard let minutes = Int(trimmed) else { return .failure(.notAWholeNumber) }
        guard range.contains(minutes) else { return .failure(.outOfRange) }
        return .success(minutes)
    }

    static func message(for failure: Failure) -> String {
        switch failure {
        case .empty:
            return String(localized: "Trage eine Dauer in Minuten ein.")
        case .notAWholeNumber:
            return String(localized: "Nur ganze Minuten.")
        case .outOfRange:
            return String(localized: "Zwischen 5 und 120 Minuten.")
        }
    }
}
```

Add the three German strings to `Localizable.xcstrings` with English translations: "Enter a duration in minutes.", "Whole minutes only.", "Between 5 and 120 minutes."

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Logic/FocusDurationInput.swift \
        watch_streamer/WatchStreamer/Localizable.xcstrings \
        watch_streamer/ScrybeTests/FocusDurationInputTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): validate a freely typed session length"
```

---

### Task 8: Start- und Stopp-Ausgänge trennen

`.noAnswer` deckt heute drei Lagen ab. Die UI kann daraus keine nächste Aktion ableiten (Spec §8).

**Files:**
- Modify: `watch_streamer/Shared/WatchCommand.swift` (`FocusStartOutcome`)
- Modify: `watch_streamer/WatchStreamer/ServerCommandListener.swift` (`startFocusSession`)
- Test: `watch_streamer/ScrybeTests/FocusStartOutcomeTests.swift` *(neu)*

**Interfaces:**
- Produces: `FocusStartOutcome` mit `started`, `refused(FocusStartRefusal)`, `unconfirmed`, `unreachable`

- [ ] **Step 1: Write the failing test**

```swift
import Testing
@testable import WatchStreamer

@Suite("Focus start outcome")
struct FocusStartOutcomeTests {

    @Test func okMeansStarted() {
        #expect(FocusStartOutcome.from(reply: [WatchPayloadKey.ok: true]) == .started)
    }

    @Test func aKnownRefusalKeepsItsReason() {
        let reply: [String: Any] = [
            WatchPayloadKey.ok: false,
            WatchPayloadKey.error: FocusStartRefusal.recordingInProgress.rawValue,
        ]
        #expect(FocusStartOutcome.from(reply: reply) == .refused(.recordingInProgress))
    }

    /// Why unconfirmed and not unreachable: a deadline that passed says
    /// nothing about the Watch. Claiming it was reachable, or that it was
    /// not, would both be inventions.
    @Test func aMissingReplyIsUnconfirmed() {
        #expect(FocusStartOutcome.from(reply: [:]) == .unconfirmed)
    }

    @Test func aTransportFailureIsUnreachable() {
        #expect(FocusStartOutcome.unreachable != FocusStartOutcome.unconfirmed)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `unconfirmed` and `unreachable` do not exist.

- [ ] **Step 3: Write minimal implementation**

```swift
public nonisolated enum FocusStartOutcome: Equatable, Sendable {
    case started
    case refused(FocusStartRefusal)
    /// The deadline passed, or the Watch refused for a reason this build does
    /// not recognise. Says nothing about reachability in either direction.
    case unconfirmed
    /// WatchConnectivity reported a transport failure. The request did not
    /// arrive.
    case unreachable

    public static func from(reply: [String: Any]) -> FocusStartOutcome {
        guard WatchPayloadValue.bool(reply[WatchPayloadKey.ok]) ?? false else {
            let raw = reply[WatchPayloadKey.error] as? String ?? ""
            guard let refusal = FocusStartRefusal(rawValue: raw) else { return .unconfirmed }
            return .refused(refusal)
        }
        return .started
    }
}
```

In `ServerCommandListener.startFocusSession()`, return `.unreachable` on the transport-error path and `.unconfirmed` on the deadline path.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 4 tests.

- [ ] **Step 5: Run the full suite**

Every `case .noAnswer` on the start path becomes two cases. Expected: green after the compiler-guided edits.

- [ ] **Step 6: Commit**

```bash
git add "watch_streamer/Shared/WatchCommand.swift" \
        watch_streamer/WatchStreamer/ServerCommandListener.swift \
        watch_streamer/ScrybeTests/FocusStartOutcomeTests.swift
git diff --cached --name-only
git commit -m "fix(scrybe): stop one sentence from covering three answers"
```

---

### Task 9: Eine laufende Sitzung nach App-Neustart wiederfinden

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift`
- Test: `watch_streamer/ScrybeTests/FocusSessionStoreTests.swift`

**Interfaces:**
- Consumes: `CaptureMode` aus Task 1, `begin(targetSeconds:at:)` aus Task 4
- Produces: `func adoptIfWatchIsInFocus(poll: [String: Any], now: Date = Date())`

- [ ] **Step 1: Write the failing test**

```swift
    /// Why the Watch and not a stored copy: the store is in-memory on purpose,
    /// and the Watch owns the sensor — it is the side that survives the
    /// force-quit this exists for.
    @Test func aFocusPollResumesTheSession() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        let startedAt = Date().addingTimeInterval(-300)
        let poll: [String: Any] = [
            WatchPayloadKey.Status.captureMode: "focus",
            WatchPayloadKey.Status.focusStartedAtMs:
                Int64(startedAt.timeIntervalSince1970 * 1000),
        ]
        store.adoptIfWatchIsInFocus(poll: poll)

        guard case .running(let resumed, _) = store.phase else {
            Issue.record("expected running, got \(store.phase)"); return
        }
        #expect(abs(resumed.timeIntervalSince(startedAt)) < 1)
    }

    /// A study recording must not be adopted as a focus session.
    @Test func aRecordingPollIsNotAdopted() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        store.adoptIfWatchIsInFocus(poll: [WatchPayloadKey.Status.captureMode: "recording"])
        #expect(!store.isActive)
    }

    /// Adopting on top of a live session would restart its clock.
    @Test func adoptingDoesNothingWhileASessionRuns() {
        let (bestiary, url) = tempBestiary()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = FocusSessionStore(capSeconds: 3600, bestiary: bestiary)

        store.beginForTesting(targetSeconds: 1500)
        guard case .running(let original, _) = store.phase else {
            Issue.record("expected running"); return
        }
        let poll: [String: Any] = [
            WatchPayloadKey.Status.captureMode: "focus",
            WatchPayloadKey.Status.focusStartedAtMs: Int64(0),
        ]
        store.adoptIfWatchIsInFocus(poll: poll)

        guard case .running(let after, _) = store.phase else {
            Issue.record("expected running"); return
        }
        #expect(after == original)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — no member `adoptIfWatchIsInFocus`.

- [ ] **Step 3: Write minimal implementation**

```swift
    /// Picks a session back up that the Watch is still running — after a
    /// force-quit, a crash, or simply the app being killed in the background.
    ///
    /// Why no goal is restored: the target lives only in the phone's UI, and
    /// the store is in-memory on purpose. An adopted session is a goalless
    /// one, which is honest — nobody can say what was chosen before.
    func adoptIfWatchIsInFocus(poll: [String: Any], now: Date = Date()) {
        guard !isActive,
              CaptureMode.from(poll: poll) == .focus,
              let startedMs = CaptureMode.focusStartedAtMs(poll: poll) else { return }
        let startedAt = Date(timeIntervalSince1970: Double(startedMs) / 1000)
        begin(targetSeconds: nil, at: startedAt)
    }
```

Call it from the place that already handles poll replies on the phone, once per poll.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 3 tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Stores/FocusSessionStore.swift \
        watch_streamer/ScrybeTests/FocusSessionStoreTests.swift
git diff --cached --name-only
git commit -m "feat(scrybe): pick up a session the Watch is still running"
```

---

### Task 10: Der Tracking-Punkt sagt „misst gerade", nicht „hat geschrieben"

`WatchStatusDot` und `TodayView` fragen beide `isRecentlyWriting()` mit 15-Minuten-Fenster. Für eine laufende Fokus-Sitzung liegt die Wahrheit live vor (Spec §9).

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/FocusStore.swift` (nichts entfernen — ergänzen)
- Modify: `watch_streamer/WatchStreamer/Scrybe/Components/WatchStatusDot.swift:21`
- Test: `watch_streamer/ScrybeTests/FocusStoreLocalTests.swift`

**Interfaces:**
- Consumes: `CaptureMode` aus Task 1
- Produces: `FocusStore.isMeasuringNow: Bool`

- [ ] **Step 1: Write the failing test**

```swift
    /// Why two statements and not two answers to one question: the passive
    /// path cannot say "now" — the recorder is readable only minutes later —
    /// while a focus session can. One dot saying both makes it mean neither.
    @Test func recencyAndMeasuringAreDifferentClaims() {
        // `tempStore()` already exists in this suite: it isolates the decision
        // file, the archive and the UserDefaults suite, because `.standard` is
        // process-wide and would leak between tests.
        let (store, _, _) = tempStore()
        store.applyCaptureMode(.focus)
        #expect(store.isMeasuringNow)
        #expect(!store.isRecentlyWriting())

        store.applyCaptureMode(.idle)
        #expect(!store.isMeasuringNow)
    }

    @Test func aStudyRecordingAlsoCountsAsMeasuring() {
        let (store, _, _) = tempStore()
        store.applyCaptureMode(.recording)
        #expect(store.isMeasuringNow)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — no `applyCaptureMode` / `isMeasuringNow`.

- [ ] **Step 3: Write minimal implementation**

```swift
    /// Whether the Watch's sensors are running right now, for a focus session
    /// or a study recording. Distinct from `isRecentlyWriting()`, which
    /// answers "has written lately" for the passive path and cannot answer
    /// this one.
    @Published private(set) var isMeasuringNow = false

    func applyCaptureMode(_ mode: CaptureMode) {
        isMeasuringNow = mode != .idle
    }
```

In `WatchStatusDot.swift:21`, change `private var writing: Bool { focus.isRecentlyWriting(now: at) }` so the tracking dot reads `focus.isMeasuringNow`, and give it an accessibility label that says which of the two it means. Leave `TodayView.swift:37` on `isRecentlyWriting()` — the daily ring's claim is unchanged.

Feed `applyCaptureMode` from the same poll handler as Task 9.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS, 2 tests.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add watch_streamer/WatchStreamer/Stores/FocusStore.swift \
        watch_streamer/WatchStreamer/Scrybe/Components/WatchStatusDot.swift \
        watch_streamer/ScrybeTests/FocusStoreLocalTests.swift
git diff --cached --name-only
git commit -m "fix(scrybe): let the dot say measuring, not wrote lately"
```

---

### Task 11: `CreatureCanvas` aus der Galerie ziehen

Sie ist `private` in `BestiaryView.swift:91` und damit auf der Bühne nicht verwendbar.

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/CreatureCanvas.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/BestiaryView.swift:39,91-112`
- Modify: `watch_streamer/WatchStreamer/Scrybe/Components/Marginalia.swift`
- Test: `watch_streamer/ScrybeTests/CreatureNamingTests.swift` *(neu)*

**Interfaces:**
- Produces: `struct CreatureCanvas: View { init(speciesId: Int, strokesDrawn: Int) }` (unverändert, nur nicht mehr `private`); `Marginalia.name(forSpecies: Int) -> String`

- [ ] **Step 1: Write the failing test**

The canvas takes no size — it fills whatever frame it is given, which is why the gallery wraps it in `.aspectRatio(1, contentMode: .fit)`. Keep that: the ready screen sets a frame instead. What is testable is the name lookup, which is today a `private var speciesName` inside `BestiaryView` and therefore not reachable from the focus tab either.

```swift
import Testing
import SwiftUI
@testable import WatchStreamer

@Suite("Creature naming")
struct CreatureNamingTests {

    @Test func everySpeciesHasAName() {
        for id in Marginalia.names.indices {
            #expect(!Marginalia.name(forSpecies: id).isEmpty)
        }
    }

    /// Why an empty string and not a crash: a species id from a stored entry
    /// written by a future build must not take the screen down.
    @Test func anUnknownSpeciesNamesNothing() {
        #expect(Marginalia.name(forSpecies: -1).isEmpty)
        #expect(Marginalia.name(forSpecies: Marginalia.names.count).isEmpty)
    }

    /// Compile-level: if this line builds, the canvas is reachable outside
    /// `BestiaryView`, which is the visibility defect being fixed.
    @Test @MainActor func canvasIsUsableOutsideTheGallery() {
        _ = CreatureCanvas(speciesId: 0, strokesDrawn: 3)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `cannot find 'CreatureCanvas' in scope` and no `name(forSpecies:)`.

- [ ] **Step 3: Write minimal implementation**

Move the `CreatureCanvas` struct **verbatim** from `BestiaryView.swift:91-112` into the new file and drop `private`. Do not add a size parameter: it already fills its frame, and two sizing mechanisms would drift.

```swift
import SwiftUI

/// One bestiary creature. Fills whatever frame it is given — the gallery uses
/// `.aspectRatio(1, contentMode: .fit)`, the focus tab a fixed frame.
///
/// Lives here rather than inside `BestiaryView` because the focus tab shows
/// the same creature at drawing size while the margin shows it at line height.
/// Two drawing paths would drift.
struct CreatureCanvas: View {
    // … moved unchanged from BestiaryView:91-112
}
```

Add the name lookup where the names already live, so it is not a second table:

In `watch_streamer/WatchStreamer/Scrybe/Components/Marginalia.swift` (where `names` is declared at line 12, `internal`, so the extension is internal too):

```swift
extension Marginalia {
    /// The creature's name, or an empty string for an id this build does not
    /// know. Was a private computed property inside the gallery, which left
    /// the focus tab without a way to name the creature it draws.
    static func name(forSpecies id: Int) -> String {
        names.indices.contains(id) ? names[id] : ""
    }
}
```

In `BestiaryView.swift:39`, replace the private `speciesName` body with `Marginalia.name(forSpecies: entry.speciesId)`.

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Expected: green, and the gallery renders unchanged.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/Components/CreatureCanvas.swift \
        watch_streamer/WatchStreamer/Scrybe/BestiaryView.swift \
        watch_streamer/WatchStreamer/Scrybe/Components/Marginalia.swift \
        watch_streamer/ScrybeTests/CreatureNamingTests.swift
git diff --cached --name-only
git commit -m "refactor(scrybe): let the creature be drawn and named outside the gallery"
```

---

### Task 12: Das Dauer-Sheet

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/FocusDurationSheet.swift`
- Modify: `watch_streamer/WatchStreamer/Localizable.xcstrings`

**Interfaces:**
- Consumes: `FocusDurationInput` (Task 7), `ScrybeSettings.focusDurationKey` (Task 5)
- Produces: `struct FocusDurationSheet: View { init(minutes: Binding<Int?>, isPresented: Binding<Bool>) }` — `nil` bedeutet „einfach schreiben"

- [ ] **Step 1: Build the sheet**

```swift
import SwiftUI

/// Presets, a free field and "just write". Opened by tapping the number in
/// the ready screen's sentence, never shown on arrival — the form exists, it
/// is just not the first thing anyone meets.
struct FocusDurationSheet: View {
    @Binding var minutes: Int?
    @Binding var isPresented: Bool

    @Environment(\.scrybe) private var theme
    @State private var freeText = ""
    @State private var failure: FocusDurationInput.Failure?

    private static let presets = [15, 25, 45]

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Wie lange?")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)

            HStack(spacing: 12) {
                ForEach(Self.presets, id: \.self) { preset in
                    presetChip(preset)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    TextField("Minuten", text: $freeText)
                        .keyboardType(.numberPad)
                        .font(.system(.body, design: .serif))
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel(Text("Eigene Dauer in Minuten"))
                    Button("Übernehmen") { applyFreeText() }
                        .buttonStyle(.plain)
                        .foregroundStyle(theme.accent)
                }
                if let failure {
                    Text(FocusDurationInput.message(for: failure))
                        .font(.footnote)
                        .foregroundStyle(theme.danger)
                }
            }

            Button {
                minutes = nil
                isPresented = false
            } label: {
                Text("Einfach schreiben")
                    .font(.system(.body, design: .serif))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.secondaryInk)
            .accessibilityHint(Text("Startet ohne Ziel. Die Sitzung endet, wenn du sie beendest."))
        }
        .padding(20)
        .presentationDetents([.height(320)])
    }

    private func presetChip(_ preset: Int) -> some View {
        let selected = minutes == preset
        return Button {
            minutes = preset
            isPresented = false
        } label: {
            Text("\(preset) Min")
                .font(.system(.body, design: .serif))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(selected ? theme.ink : theme.secondaryInk)
        .background(selected ? theme.wash(theme.accent) : theme.track,
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    private func applyFreeText() {
        switch FocusDurationInput.parse(freeText) {
        case .success(let value):
            minutes = value
            failure = nil
            isPresented = false
        case .failure(let reason):
            failure = reason
        }
    }
}
```

- [ ] **Step 2: Add the strings**

Add to `Localizable.xcstrings` with English translations: „Wie lange?" → "How long?", „Minuten" → "Minutes", „Übernehmen" → "Apply", „Einfach schreiben" → "Just write", „Eigene Dauer in Minuten" → "Custom duration in minutes", „Startet ohne Ziel. Die Sitzung endet, wenn du sie beendest." → "Starts without a goal. The session ends when you end it."

- [ ] **Step 3: Run the full suite and the device build**

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/FocusDurationSheet.swift \
        watch_streamer/WatchStreamer/Localizable.xcstrings
git diff --cached --name-only
git commit -m "feat(scrybe): put the duration form behind a tap"
```

---

### Task 13: Die Bühne — `FocusReadyView`

Der Zustand, der heute eine Frage stellt, zeigt künftig die Kreatur (Spec §4).

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/FocusReadyView.swift`
- Modify: `watch_streamer/WatchStreamer/Localizable.xcstrings`

**Interfaces:**
- Consumes: `CreatureCanvas` (Task 11), `FocusProgress` (Task 6), `FocusDurationSheet` (Task 12), `ScrybeSettings.focusDurationKey` (Task 5)
- Produces: `struct FocusReadyView: View { init(onStart: @escaping (Double?) -> Void) }`

- [ ] **Step 1: Build the view**

```swift
import SwiftUI

/// The focus tab on arrival: a ruled page, the creature that is being drawn,
/// and a sentence whose number can be tapped. No question, no form — the page
/// is ready to start.
struct FocusReadyView: View {
    /// Seconds, or `nil` for a session without a goal.
    let onStart: (Double?) -> Void

    @ObservedObject private var bestiary = BestiaryStore.shared
    @Environment(\.scrybe) private var theme
    @AppStorage(ScrybeSettings.focusDurationKey) private var storedMinutes =
        ScrybeSettings.defaultFocusMinutes
    @State private var goalless = false
    @State private var sheetPresented = false
    @ScaledMetric(relativeTo: .largeTitle) private var creatureSide: CGFloat = 140

    private var chosenMinutes: Int? { goalless ? nil : storedMinutes }
    private var chosenSeconds: Double? { chosenMinutes.map { Double($0) * 60 } }

    var body: some View {
        let creature = bestiary.creatureInProgress()
        let remaining = FocusProgress.remainingSeconds(writingSeconds: creature.writingSeconds)

        VStack(spacing: 20) {
            CreatureCanvas(speciesId: creature.speciesId,
                           strokesDrawn: creature.strokesDrawn)
                .frame(width: creatureSide, height: creatureSide)
                .accessibilityLabel(Text(creatureLabel(remaining: remaining)))

            VStack(spacing: 6) {
                Text(Marginalia.name(forSpecies: creature.speciesId))
                    .font(.system(.title3, design: .serif))
                    .italic()
                    .foregroundStyle(theme.ink)
                Text(progressSentence(remaining: remaining))
                    .font(.footnote)
                    .foregroundStyle(theme.secondaryInk)
                    .multilineTextAlignment(.center)
            }

            durationSentence

            Button { onStart(chosenSeconds) } label: {
                Text("Sitzung starten")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.paperTop)
            .background(theme.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .padding(20)
        .sheet(isPresented: $sheetPresented) {
            FocusDurationSheet(minutes: Binding(
                get: { chosenMinutes },
                set: { newValue in
                    if let newValue { storedMinutes = newValue; goalless = false }
                    else { goalless = true }
                }), isPresented: $sheetPresented)
        }
    }

    private var durationSentence: some View {
        Button { sheetPresented = true } label: {
            if let minutes = chosenMinutes {
                Text("Eine Sitzung von ") + Text("\(minutes) Minuten").foregroundColor(theme.accent)
            } else {
                Text("Ohne Ziel — ") + Text("einfach schreiben").foregroundColor(theme.accent)
            }
        }
        .buttonStyle(.plain)
        .font(.system(.body, design: .serif))
        .foregroundStyle(theme.ink)
        .accessibilityLabel(Text(durationAccessibilityLabel))
        .accessibilityHint(Text("Ändert die Dauer."))
    }

    private var durationAccessibilityLabel: String {
        if let minutes = chosenMinutes {
            return String(localized: "Dauer: \(minutes) Minuten")
        }
        return String(localized: "Dauer: ohne Ziel")
    }

    private func progressSentence(remaining: Double) -> String {
        let minutes = Int((remaining / 60).rounded())
        if FocusProgress.exceedsCreature(remainingSeconds: remaining,
                                         sessionSeconds: chosenSeconds) {
            return String(localized: "Noch etwa \(minutes) Minuten, bis er fertig gezeichnet ist — und du beginnst ein neues.")
        }
        return String(localized: "Noch etwa \(minutes) Minuten, bis er fertig gezeichnet ist.")
    }

    private func creatureLabel(remaining: Double) -> String {
        let name = Marginalia.name(forSpecies: bestiary.creatureInProgress().speciesId)
        return "\(name), \(progressSentence(remaining: remaining))"
    }
}
```

`Marginalia.name(forSpecies:)` comes from Task 11; `CreatureCanvas` takes no size, so the frame here is what makes it a drawing rather than a margin mark.

- [ ] **Step 2: Add the strings**

Add each German literal above to `Localizable.xcstrings` with an English translation.

- [ ] **Step 3: Run the full suite and the device build**

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/FocusReadyView.swift \
        watch_streamer/WatchStreamer/Localizable.xcstrings
git diff --cached --name-only
git commit -m "feat(scrybe): open the focus tab on a page, not a question"
```

---

### Task 14: Die Ausgänge — `FocusOutcomeView`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/FocusOutcomeView.swift`
- Modify: `watch_streamer/WatchStreamer/Localizable.xcstrings`

**Interfaces:**
- Consumes: `FocusStartOutcome` (Task 8), `FocusSessionStore.FinishReason` (Task 3)
- Produces: `struct FocusOutcomeView: View { init(outcome: Outcome, onRetry: @escaping () -> Void, onDismiss: @escaping () -> Void) }` mit `enum Outcome { case refused(FocusStartRefusal), unconfirmed, unreachable, finished(FocusSessionStore.FinishReason) }`

- [ ] **Step 1: Build the view**

Each case names what happened and offers the one action that fits it:

```swift
import SwiftUI

/// Why a session is not running: refused, unconfirmed, unreachable, or simply
/// over. Each carries the next action that fits it — a retry helps a timeout
/// and does nothing for a missing permission.
struct FocusOutcomeView: View {
    enum Outcome: Equatable {
        case refused(FocusStartRefusal)
        case unconfirmed
        case unreachable
        case finished(FocusSessionStore.FinishReason)
    }

    let outcome: Outcome
    let onRetry: () -> Void
    let onDismiss: () -> Void

    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(spacing: 16) {
            Text(title)
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
            Text(detail)
                .font(.subheadline)
                .foregroundStyle(theme.secondaryInk)
                .multilineTextAlignment(.center)
            if showsRetry {
                button("Erneut versuchen", action: onRetry)
            }
            button("Zurück", action: onDismiss)
        }
        .padding(20)
        .frame(maxWidth: .infinity)
        .scrybeSurface(cornerRadius: 16)
    }

    private var showsRetry: Bool {
        switch outcome {
        case .unconfirmed, .unreachable: return true
        case .refused, .finished: return false
        }
    }

    private var title: String {
        switch outcome {
        case .refused(.recordingInProgress):
            return String(localized: "Die Uhr nimmt gerade auf")
        case .refused(.workoutPermissionMissing):
            return String(localized: "Die Workout-Freigabe fehlt")
        case .unconfirmed:
            return String(localized: "Start unbestätigt")
        case .unreachable:
            return String(localized: "Die Uhr ist nicht erreichbar")
        case .finished(.user):
            return String(localized: "Sitzung beendet")
        case .finished(.hardCap):
            return String(localized: "Zeitgrenze erreicht")
        case .finished(.studyPreemption):
            return String(localized: "Eine Aufnahme hat die Uhr übernommen")
        case .finished(.watchFailure):
            return String(localized: "Die Uhr konnte nicht weiter messen")
        case .finished(.stopUnconfirmed):
            return String(localized: "Beendet, ohne Bestätigung")
        }
    }

    private var detail: String {
        switch outcome {
        case .refused(.recordingInProgress):
            return String(localized: "Beende sie zuerst, dann kann die Sitzung starten.")
        case .refused(.workoutPermissionMissing):
            return String(localized: "Erteile sie in den Health-Einstellungen.")
        case .unconfirmed:
            return String(localized: "Binnen 8 Sekunden kam keine Antwort. Ob die Uhr misst, ist damit offen.")
        case .unreachable:
            return String(localized: "Die Anfrage kam nicht an. Prüfe, ob die Uhr in Reichweite ist.")
        case .finished(.user), .finished(.hardCap):
            return String(localized: "Deine Schreibzeit ist gutgeschrieben.")
        case .finished(.studyPreemption):
            return String(localized: "Die Sitzung endete, weil eine Studien-Aufnahme die Sensoren braucht.")
        case .finished(.watchFailure):
            return String(localized: "Prüfe die Workout-Freigabe in den Health-Einstellungen.")
        case .finished(.stopUnconfirmed):
            return String(localized: "Die Uhr hat den Stopp nicht bestätigt. Der Sensorstrom läuft womöglich weiter.")
        }
    }

    private func button(_ title: LocalizedStringKey,
                        action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.paperTop)
        .background(theme.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
```

- [ ] **Step 2: Add the strings**

Every German literal above goes into `Localizable.xcstrings` with an English translation.

- [ ] **Step 3: Run the full suite and the device build**

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/FocusOutcomeView.swift \
        watch_streamer/WatchStreamer/Localizable.xcstrings
git diff --cached --name-only
git commit -m "feat(scrybe): give each ending its own screen and action"
```

---

### Task 15: Der Tab selbst

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/FocusTabView.swift`
- Modify: `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift:3-45`
- Modify: `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift:21,31`
- Modify: `watch_streamer/WatchStreamer/Scrybe/TodayView.swift:74-78,116-147`
- Modify: `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift`
- Delete: `watch_streamer/WatchStreamer/Scrybe/FocusSessionView.swift`

**Interfaces:**
- Consumes: `FocusReadyView` (13), `FocusOutcomeView` (14), `FocusStartOutcome` (8), `FocusSessionStore` (3, 4)
- Produces: `struct FocusTabView: View`

- [ ] **Step 1: Build the tab**

```swift
import SwiftUI

/// The focus area. Owns the tab's `NavigationStack` — `HistoryView` and
/// `BestiaryView` give theirs up, because a pushed stack inside a stack
/// produces two navigation bars and an unpredictable back gesture.
struct FocusTabView: View {
    @ObservedObject private var session = FocusSessionStore.shared
    @Environment(\.scrybe) private var theme
    @State private var startOutcome: FocusOutcomeView.Outcome?

    var body: some View {
        NavigationStack {
            ScrollView { content.padding(.horizontal, 16) }
                .background { theme.paper.ignoresSafeArea() }
                .navigationDestination(for: BestiaryDestination.self) { _ in
                    BestiaryView()
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let startOutcome {
            FocusOutcomeView(outcome: startOutcome,
                             onRetry: { self.startOutcome = nil; start(seconds: lastRequested) },
                             onDismiss: { self.startOutcome = nil })
        } else {
            switch session.phase {
            case .idle:
                FocusReadyView(onStart: start(seconds:))
            case .starting:
                starting
            case .running(let startedAt, let target):
                TimelineView(.periodic(from: startedAt, by: 1)) { context in
                    running(startedAt: startedAt, target: target, now: context.date)
                }
            case .failed, .finished:
                FocusOutcomeView(outcome: .finished(session.finishReason ?? .user),
                                 onRetry: {},
                                 onDismiss: { session.returnToIdle() })
            }
        }
    }

    @State private var lastRequested: Double?

    private func start(seconds: Double?) {
        lastRequested = seconds
        session.markStarting()
        // Why unstructured: leaving this screen must not abandon a start the
        // Watch may already have accepted.
        Task {
            switch await ServerCommandListener.shared.startFocusSession() {
            case .started:      session.begin(targetSeconds: seconds)
            case .refused(let r): startOutcome = .refused(r); session.returnToIdle()
            case .unconfirmed:  startOutcome = .unconfirmed; session.returnToIdle()
            case .unreachable:  startOutcome = .unreachable; session.returnToIdle()
            }
        }
    }
}

/// A push target with no payload; the gallery reads the shared store.
struct BestiaryDestination: Hashable {}
```

Move the `starting` and `running` view bodies verbatim from `FocusSessionView.swift:144-180`, adapting `running` to a `Double?` target: with a goal, the subtitle stays „von 25 min"; without one, it reads „seit 12:34". Keep `WritingPageView` and the „Beenden" button, and make that button the only exit — the tab bar is hidden in this state.

- [ ] **Step 2: Rework the root**

In `RootPagerView.swift`, replace the `history` tab with `focus`:

```swift
    private enum Tab: String {
        case today = "Heute"
        case trends = "Trends"
        case focus = "Fokus"
        case profile = "Profil"
    }
```

```swift
                FocusTabView()
                    .tabItem { Label("Fokus", systemImage: "circle.dashed") }
                    .tag(Tab.focus)
```

(The custom glyph replaces `circle.dashed` in the second plan.) Hide the header while a session runs:

```swift
        VStack(spacing: 12) {
            // Why: the header is a sibling of the TabView, so hiding the tab
            // bar alone would leave it standing over a page meant to be alone.
            if !FocusSessionStore.shared.isActive {
                ScrybeHeader(label: selection.rawValue)
            }
```

Add `.toolbar(.hidden, for: .tabBar)` to `FocusTabView`'s content while `session.isActive`.

- [ ] **Step 3: Move the bestiary and free the stack**

In `HistoryView.swift`, remove the `NavigationStack` at line 21 and the `BestiaryView()` at line 31. In `TrendsView.swift`, add a row at the foot that pushes `HistoryView`, and wrap `TrendsView` in the tab's own `NavigationStack`.

In `TodayView.swift`, delete the focus card (116-147) and the `fullScreenCover` (74-78), and add a status line shown only while a session is active:

```swift
            if session.isActive {
                Button { selection = .focus } label: {
                    Text("Fokus läuft · \(sessionClock) — öffnen")
                }
            }
```

Route the tab switch through the binding `RootPagerView` already owns.

- [ ] **Step 4: Delete the old view**

```bash
git rm watch_streamer/WatchStreamer/Scrybe/FocusSessionView.swift
```

- [ ] **Step 5: Run the full suite and both builds**

Expected: `** TEST SUCCEEDED **` and two `** BUILD SUCCEEDED **`. Fix every call site the compiler names.

- [ ] **Step 6: Commit**

```bash
git add watch_streamer/WatchStreamer/Scrybe/
git diff --cached --name-only
git commit -m "feat(scrybe): make focus a place instead of a sheet"
```

---

### Task 16: Gerätenachweis

Kein Test in diesem Plan beweist die Punkte unten; sie brauchen echte Hardware (Spec §13).

**Files:**
- Modify: `reports/sensor_probe.md` oder eine neue Notiz unter `reports/`

- [ ] **Step 1: Build and install**

```bash
xcodebuild -project watch_streamer/WatchStreamer.xcodeproj -scheme "WatchStreamer" \
  -destination 'generic/platform=iOS' -configuration Debug build
xcrun devicectl device install app --device <iphone-udid> <app>
xcrun devicectl device install app --device <watch-udid> "<app>/Watch/WatchStreamer Watch App.app"
```

- [ ] **Step 2: Work through the list and write down what happened**

- Fokusstart bei getrennter Server-WebSocket-Verbindung, aber erreichbarer Uhr.
- Watch-App im Vordergrund; Watch-App im Hintergrund.
- Workout-Freigabe verweigert — die Ablehnung wird als Ablehnung erklärt, nicht als Timeout.
- Cap greift auf der Uhr, einmal mit herabgesetztem Wert.
- Force-Quit des iPhones bei laufender Sitzung, danach App-Neustart: die Sitzung wird über `capture_mode` wiedergefunden.
- Neustart der Uhr bei laufender Sitzung.
- Header und Tab-Bar verschwinden im Lauf-Zustand und kommen zurück.
- Die Kreatur ist bei 140 Punkten lesbar, auch bei größter Dynamic-Type-Stufe und auf einem kleinen iPhone.
- VoiceOver über Tabs, Dauersatz, Tracking-Punkt und Kreatur.

- [ ] **Step 3: Commit the record**

```bash
git add reports/
git diff --cached --name-only
git commit -m "docs(scrybe): record the focus tab device run"
```

---

## Was dieser Plan nicht enthält

Die fünf Stock-Ränder (Tab-Glyphen, Segmented-Picker, `flame.fill`, Splash-Typografie, Empty-States) stehen im zweiten Plan, `docs/plans/2026-08-31-scrybe-finishing-edges.md`. Sie hängen nicht am Fokus-Bereich und können unabhängig abgenommen werden.

Der vollständige `WatchConnectionState` über Header, Profil und Offline-Banner bleibt offen und ist laut Spec §9 **verpflichtender Bestandteil von Phase A vor einem echten Launch**.
