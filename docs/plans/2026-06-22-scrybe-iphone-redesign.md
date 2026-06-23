# Scrybe — iPhone-App-Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the iPhone app (`watch_streamer/WatchStreamer/`) into "Scrybe", a calm writing-focus tracker for the writer, with the existing operator UI moved behind a hidden, PIN-gated Admin panel — backed by the existing server's `/focus` aggregation plus one new history endpoint.

**Architecture:** A new SwiftUI front (`Scrybe/`: a horizontal `TabView(.page)` pager — Today / Trends / History) is built **in parallel** with the current `iPhoneView`, consuming the same singleton managers (`PhoneBridge`, `ServerCommandListener`) and the server's `/focus/*` HTTP + `live_inference` WebSocket data. The operator surface is rebuilt as `Admin/` cards reusing the existing stores. At the end, the `@main` root is switched from `iPhoneView()` to `RootPagerView()` and the legacy view + AirPods code are deleted. Pure logic (streak, goal %, "data flowing", time formatting) lives in view-free, unit-tested types.

**Tech Stack:** SwiftUI (iOS 16 floor), `ObservableObject`/`@Published` (no `@Observable`/SwiftData at iOS 16), `URLSession` async/await, Swift Testing (`import Testing`) for the first-ever test target; FastAPI/Python for the one new server endpoint.

---

## Global Constraints

Copied verbatim from the spec — every task implicitly includes these.

- **Scope:** Redesign the iOS app only. The server/ML pipeline is unchanged **except** the single new `GET /focus/history` endpoint (Task 1). Do **not** touch the Watch app.
- **No AirPods anywhere** in Scrybe or Admin. `AirPodsMotionManager` is removed during migration (Task 35).
- **iOS deployment target = 16.0.** Do not use `@Observable` (iOS 17+), `SwiftData` (iOS 17+), or any iOS 17/18-only API without an `@available` guard. `TabView(.page)`, `NavigationStack`, `Charts`, `Gauge` are all available at 16.
- **Design system is centralized** in `ScrybeTheme` (distributed via Environment). No scattered color/spacing constants. Exact tokens: paper radial `#F6EFE0 → #ECE3D0`; ink text `#2A2733`; ink-accent indigo `#4B4E8C`; sepia `#8A6D3B`; success ink-green `#5A7D4E`; warning `#B8862F`; danger ink-red `#A23B46`. Serif for display numbers + the "Scrybe" wordmark; system font for body. **Dynamic Type supported** — use text styles, never a fixed point size as the sole sizing mechanism.
- **Manager access pattern (existing convention):** all managers are singletons (`static let shared`), consumed in views via `@ObservedObject private var x = X.shared`. New Scrybe stores follow the same convention (`final class … : ObservableObject { static let shared = … }`, `@MainActor` where they mutate published UI state). No app-level `@EnvironmentObject` plumbing except the theme (`\.scrybe`).
- **Server base URL:** build all `/focus` URLs from `PhoneBridge.serverBaseURL` (e.g. `PhoneBridge.serverBaseURL + "/focus/today"`). Server IP lives in `UserDefaults["serverIP"]`, default `ServerConfig.defaultIP` (`192.168.178.147`).
- **Live "schreibt gerade" = `writing == true`** (model proba ≥ 0.5), consistent with the server and Recording-Health.
- **Streak rule:** a day counts toward the streak **only if the daily goal was reached**; the streak breaks on any goal-miss. Today not yet at goal is "pending" (does not break a streak intact through yesterday).
- **Text quality:** all UI strings, comments, and docs strictly professional German/English — no AI filler, no person-name references in shipped strings.
- **Code comments:** none by default; only `# Why:` / `// Why:` lines for non-obvious constraints (project convention).

**Skill-derived conventions (apply to every task — from `swift-concurrency-expert`, `swiftui-design-principles`, `swift-testing-expert`):**

- **Default actor isolation is MainActor** (`SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`, `SWIFT_APPROACHABLE_CONCURRENCY = YES`). New UI stores are MainActor — keep them simple. `FocusAPI` stays MainActor-default (the network runs off-main inside `URLSession`; the ≤90-bucket JSON decode on resume is negligible) and stores **no non-Sendable closure** (it calls `PhoneBridge.serverBaseURL` inline).
- **Sendable across the WS main-hop.** `LiveInferencePayload` is captured into `ServerCommandListener`'s `DispatchQueue.main.async { self.liveInference = payload }` from a background WebSocket callback — a real actor-boundary crossing, so it **must be `Sendable`**. `Focus*DTO` and `DayWriting` are also `Sendable` (value types — cheap hygiene). Keep the existing `PhoneBridge`/`ServerCommandListener` `DispatchQueue.main.async` hop pattern for new mutations in those two classes — consistency with the just-hardened lock/main-hop code beats a divergent isolation model.
- **Parameterized tests** (`@Test(arguments:)`) for any input→output table; `try #require(...)` (not `#expect`) when a later line depends on an unwrapped value. `import Testing` only in `ScrybeTests`.
- **Spacing grid:** only 4, 8, 12, 16, 20, 24, 32, 40, 48. **Type scale:** ≤5 roles, hierarchy by weight; **Dynamic Type via text styles**, never fixed `.system(size:)` as the sole sizing (spec requirement — this overrides the design skill's fixed-size examples). **Cards:** 12–14 pt radius, single hairline stroke.
- **The custom ink-&-paper palette is intentional and overrides the design skill's "use semantic system colors" rule** (the spec mandates the hex palette). The skill's deeper rule — centralize, few values — is honored by `ScrybeTheme`: prefer its derived tokens (`track`, `hairline`, `cardFill`, `mutedInk`) over ad-hoc `theme.ink.opacity(0.xx)`.

---

## Verification Model (READ FIRST — this plan has three test modalities)

SwiftUI **cannot be built or rendered in the planning environment** (no Xcode/SDK/simulator). The plan is honest about where each task is proven:

1. **Python tasks (Phase 0 only) — fully runnable here.** Real TDD: write failing `pytest`, run it (it fails), implement, run it (it passes), commit. Exact commands + expected output are given.

2. **Swift pure-logic tasks (Phase 2, parts of 3) — test-first, run by YOU.** The `@Test` is written before the implementation. The "run" step is **you** executing `⌘U` in Xcode (or `xcodebuild test -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 15'`). The plan gives the exact test + impl code and the expected pass/fail; the loop is: I hand you a task, you run the tests and report pass/fail before we proceed.

3. **SwiftUI view tasks (Phases 4–7) — build + screenshot + skill review.** No unit test. Each ends with: (a) **you** add a `#Preview` (provided) and confirm `⌘B` builds clean; (b) **you** run the relevant Preview / simulator and send a screenshot to compare against the confirmed mockups; (c) the code is reviewed with the installed quality skills (`swiftui-pro`, `swiftui-design-principles`, `swiftui-accessibility-auditor`, `swiftui-performance-audit`) **after a session restart** (skills load at start). A view task is "done" only after the screenshot matches and the skill review passes.

**Commit cadence:** every task ends with a commit. Swift tasks commit even though they were verified on your machine — the commit records the reviewed code, and the verification result is noted in the commit body.

---

## File Structure

**All new iOS files live under `watch_streamer/WatchStreamer/` and auto-join the `WatchStreamer` target** (filesystem-synchronized groups — no `project.pbxproj` edits). The one exception is the test target (Task 6), which needs Xcode project surgery.

```
watch_streamer/WatchStreamer/
  Scrybe/
    ScrybeApp.swift            NEW @main (created last, Phase 7) — replaces WatchStreamerApp's @main
    ScrybeTheme.swift          Tinte-&-Papier tokens + Environment(\.scrybe) + Color(hex:)
    RootPagerView.swift        TabView(.page): Today/Trends/History + long-press wordmark → Admin gate
    TodayView.swift            Hero: InkRing + Streak + LiveChip + WeekStrip
    TrendsView.swift           Week summary + bar chart + StreakCalendar
    HistoryView.swift          Chronological day list → DayDetailView
    DayDetailView.swift        Per-day stretches timeline (analog to web #focus)
    OnboardingView.swift       Empty/first-run state
    Logic/
      TimeFormatting.swift     h:mm + "1h 47m" (pure, tested)
      DailyGoalProgress.swift  fraction + percent + isMet (pure, tested)
      StreakCalculator.swift   goal-met consecutive days (pure, tested)
      DataFlowEvaluator.swift  counter-delta-in-window + baseline-skip (pure, tested)
    Components/
      InkRing.swift            ink progress ring, round cap
      WeekStrip.swift          7 bars, today highlighted
      StreakCalendar.swift     habit dot grid
      LiveChip.swift           "schreibt gerade" pill
      OfflineBanner.swift      subtle offline hint
  Admin/
    AdminGateView.swift        PIN gate (paper look)
    AdminPanelView.swift       sectioned panel + "‹ Scrybe" exit
    Sections/
      RecordingHealthCard.swift  Gesund/Stau/Fehler (dataFlowing && pollFresh)
      DataflowCard.swift         In Queue / Hochgeladen / Verworfen + backlog sparkline
      ConnectionsCard.swift      Server · iPhone-Bridge · Watch (NO AirPods)
      SessionCard.swift          running session + STOP/START
      RepairCard.swift           drain / clear watch spill
      LogCard.swift              event log (state-change only)
      SettingsCard.swift         server IP, motion config, admin PIN
  Stores/
    FocusStore.swift           loads /focus/{today,week,history} + live WS, @MainActor singleton
    ScrybeSettings.swift        daily-goal + admin-PIN keys/defaults (UserDefaults)
    IMUDataStore.swift          EXTRACTED from iPhoneView_v4.swift (Task 3)
    RecordingHealthStore.swift  EXTRACTED from iPhoneView_v4.swift (Task 4)
    EventLogStore.swift         EXTRACTED FTLogStore + FTLogEntry (Task 5)
  Networking/
    FocusAPI.swift             /focus client + Decodable DTOs
    LiveInferencePayload.swift  Decodable for status.live_inference (Phase 3)

  (reused as-is: PhoneBridge.swift, ServerCommandListener.swift)
  (DELETED at migration (Phase 7): iPhoneView_v4.swift, AirPodsMotionManager.swift,
   WatchStreamerApp.swift's @main moved to ScrybeApp.swift)

watch_streamer/ScrybeTests/          NEW test target folder (Task 6)
  TimeFormattingTests.swift, DailyGoalProgressTests.swift,
  StreakCalculatorTests.swift, DataFlowEvaluatorTests.swift,
  FocusDTOTests.swift

src/server/routes/focus.py            MODIFIED — add /focus/history + _day_buckets (Task 1)
tests/test_focus.py                   MODIFIED — history tests (Task 1)
```

---

# PHASE 0 — Server endpoint (Python, fully runnable here)

### Task 1: `GET /focus/history?days=N` endpoint

**Files:**
- Modify: `src/server/routes/focus.py` (add `_day_buckets` helper; refactor `focus_week` to use it; add `focus_history`)
- Test: `tests/test_focus.py` (add history tests, reuse existing `client` / `isolated_log` / `_seed_log`)

**Interfaces:**
- Consumes (existing, verified present in `src/server/routes/focus.py`): `_read_log_rows() -> list[dict]`, `_local_iso_date(ts_ms: int) -> str`, `_stretches(rows: list[dict]) -> list[dict]`, module constant `_STRETCH_GAP_S = 2.5`, `INFERENCE_LOG_PATH` (imported from `..focus_log`).
- Produces: `GET /focus/history?days=N` returning the **same JSON shape as `/focus/week`** (`{days: [...], today, max_seconds}`) but with `N` day-buckets, `N` clamped to `[1, 365]`, default `7`. New helper `_day_buckets(rows: list[dict], n_days: int, now: datetime) -> tuple[list[dict], float]` returning `(days, max_seconds)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_focus.py` (after the existing week tests; reuse the module's existing imports `csv`, `datetime`, `timedelta`, fixtures `client`, `isolated_log`, helper `_seed_log`):

```python
def test_focus_history_default_is_seven_days(client, isolated_log):
    body = client.get("/focus/history").json()
    assert len(body["days"]) == 7
    assert body["days"][-1]["is_today"] is True


def test_focus_history_n_days_buckets(client, isolated_log):
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    ticks = []
    # 60 writing ticks today, 30 two days ago.
    for i in range(60):
        ticks.append((int(now.timestamp() * 1000) + i * 1000, True))
    two_days_ago = now - timedelta(days=2)
    for i in range(30):
        ticks.append((int(two_days_ago.timestamp() * 1000) + i * 1000, True))
    _seed_log(isolated_log, ticks)

    body = client.get("/focus/history?days=3").json()
    assert len(body["days"]) == 3
    today = next(d for d in body["days"] if d["is_today"])
    older = next(d for d in body["days"]
                 if d["date"] == two_days_ago.strftime("%Y-%m-%d"))
    assert today["writing_seconds"] > older["writing_seconds"] > 0


def test_focus_history_clamps_days(client, isolated_log):
    assert len(client.get("/focus/history?days=0").json()["days"]) == 1
    assert len(client.get("/focus/history?days=-5").json()["days"]) == 1
    assert len(client.get("/focus/history?days=9999").json()["days"]) == 365


def test_focus_week_unchanged_after_refactor(client, isolated_log):
    body = client.get("/focus/week").json()
    assert len(body["days"]) == 7
    assert body["days"][-1]["is_today"] is True
    assert body["days"][0]["is_today"] is False
    assert "max_seconds" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_focus.py -k "history or unchanged" -v`
Expected: the three `history` tests FAIL with `404 Not Found` / `KeyError` (endpoint missing); `test_focus_week_unchanged_after_refactor` PASSES (week already exists — it's the regression guard for the refactor).

- [ ] **Step 3: Add the `_day_buckets` helper and refactor `focus_week`**

In `src/server/routes/focus.py`, add this helper directly **above** `focus_week` (it factors out the bucket loop currently inline in `/focus/week`):

```python
def _day_buckets(rows: list[dict], n_days: int, now: datetime) -> tuple[list[dict], float]:
    """Sum writing-stretch seconds per local day for the last `n_days` days.

    Returns (days, max_seconds) where days is oldest -> newest, exactly
    `n_days` entries, today always last. Single source of truth shared by
    /focus/week and /focus/history.
    """
    today_iso = now.strftime("%Y-%m-%d")
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(_local_iso_date(r["ts_ms"]), []).append(r)

    days: list[dict] = []
    max_seconds = 0.0
    for i in range(n_days - 1, -1, -1):
        d = now - timedelta(days=i)
        day = d.strftime("%Y-%m-%d")
        secs = round(sum(s["duration_s"] for s in _stretches(by_day.get(day, []))), 1)
        max_seconds = max(max_seconds, secs)
        days.append({
            "date": day,
            "weekday": d.strftime("%a"),
            "writing_seconds": secs,
            "is_today": day == today_iso,
        })
    return days, max_seconds
```

Then replace the body of `focus_week` so it delegates to the helper (behavior identical):

```python
@router.get("/focus/week")
async def focus_week() -> dict:
    rows = _read_log_rows()
    now = datetime.now()
    days, max_seconds = _day_buckets(rows, 7, now)
    return {
        "days": days,
        "today": now.strftime("%Y-%m-%d"),
        "max_seconds": max_seconds,
    }
```

- [ ] **Step 4: Add the `focus_history` endpoint**

Add below `focus_week` in `src/server/routes/focus.py`:

```python
@router.get("/focus/history")
async def focus_history(days: int = 7) -> dict:
    days = max(1, min(days, 365))
    rows = _read_log_rows()
    now = datetime.now()
    buckets, max_seconds = _day_buckets(rows, days, now)
    return {
        "days": buckets,
        "today": now.strftime("%Y-%m-%d"),
        "max_seconds": max_seconds,
    }
```

(No change to `src/server/routes/__init__.py` — `focus.router` is already aggregated. No change to `src/server/focus_log.py`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_focus.py -v`
Expected: all focus tests PASS (the 4 new ones + every pre-existing focus test, confirming the `focus_week` refactor is behavior-preserving).

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `python -m pytest tests/ -q`
Expected: the whole suite passes (≈485+4 tests).

- [ ] **Step 7: Commit**

```bash
git add src/server/routes/focus.py tests/test_focus.py
git commit -m "feat(server): add GET /focus/history?days=N for Scrybe history + long streak

Factors the day-bucket loop out of /focus/week into a shared _day_buckets
helper; /focus/history returns the same shape over N (clamped 1..365) days.
Single source of truth for the Scrybe History page and >7-day streak.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE 1 — Foundation (theme, store extraction, test target)

> Phase 1 establishes the design system, makes the spec's "reused" stores real standalone files, and creates the first test target. The store extractions (Tasks 3–5) are **behavior-preserving moves** — after each, the legacy `iPhoneView_v4.swift` still references the same `X.shared` singleton, now declared in its own file. This is what lets Task 35 delete the legacy view cleanly.

### Task 2: `ScrybeTheme` design tokens + Environment

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/ScrybeTheme.swift`

**Interfaces:**
- Produces: `struct ScrybeTheme` with `let paperTop/paperBottom/ink/accent/sepia/success/warning/danger: Color`; `static let standard: ScrybeTheme`; a `Color(hex:)` initializer; `EnvironmentValues.scrybe: ScrybeTheme`; and `View.scrybeTheme(_:)` convenience. Consumed by every Scrybe/Admin view via `@Environment(\.scrybe) private var theme`.

- [ ] **Step 1: Create the theme file**

```swift
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
```

- [ ] **Step 2: Verify it builds (you)**

Run (you): `⌘B` in Xcode (target `WatchStreamer`).
Expected: builds clean. No view consumes it yet — this is a leaf type, so a compile is sufficient verification for this task.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/ScrybeTheme.swift"
git commit -m "feat(scrybe): add ScrybeTheme ink-and-paper design tokens + Environment

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 3: Extract `IMUDataStore` into its own file

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/IMUDataStore.swift`
- Modify: `watch_streamer/WatchStreamer/iPhoneView_v4.swift` (remove the `IMUDataStore` class declaration, currently ~lines 164–217)

**Interfaces:**
- Produces: `@MainActor final class IMUDataStore: ObservableObject` with `static let shared`, `@Published var accSamples: [Double]`, `@Published var gyroSamples: [Double]`, `func pushBatch(accValues: [Double], gyroValues: [Double])`, `func startStreaming()`, `func stopStreaming()`. Identical behavior — referenced by `PhoneBridge.swift` and (legacy) `IMUChart`.

- [ ] **Step 1: Cut the class out of `iPhoneView_v4.swift`**

Locate the `@MainActor final class IMUDataStore: ObservableObject { … }` block in `iPhoneView_v4.swift` (starts at the line `@MainActor` immediately above `final class IMUDataStore`, ends at its closing brace, ~line 217). **Cut** the entire class (including the `@MainActor` attribute line and any leading doc comment that belongs to it). Leave everything else in the file untouched.

- [ ] **Step 2: Paste it into the new file**

Create `watch_streamer/WatchStreamer/Stores/IMUDataStore.swift`:

```swift
import SwiftUI

// (paste the exact IMUDataStore class body cut from iPhoneView_v4.swift here,
//  unchanged — class declaration, @Published accSamples/gyroSamples,
//  pushBatch/startStreaming/stopStreaming, the private flush-timer plumbing)
```

Add `import SwiftUI` at the top (the class uses `ObservableObject`/`@Published`; if it also references `Combine` or `Foundation` types add those imports — match what the original block needed).

- [ ] **Step 3: Verify the move is behavior-preserving (you)**

Run (you): `⌘B`.
Expected: builds clean. `PhoneBridge.shared` still calls `IMUDataStore.shared.pushBatch(...)`; `IMUChart` (still in the legacy file) still observes `IMUDataStore.shared`. No reference changes because the singleton name is unchanged — only its file moved.

- [ ] **Step 4: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/IMUDataStore.swift" "watch_streamer/WatchStreamer/iPhoneView_v4.swift"
git commit -m "refactor(ios): extract IMUDataStore into Stores/ (behavior-preserving)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 4: Extract `RecordingHealthStore` into its own file

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/RecordingHealthStore.swift`
- Modify: `watch_streamer/WatchStreamer/iPhoneView_v4.swift` (remove the `RecordingHealthStore` class, ~lines 1375–1400)

**Interfaces:**
- Produces: `final class RecordingHealthStore: ObservableObject` with `static let shared`, `@Published private(set) var dataFlowing: Bool`. Same 1 Hz timer deriving `dataFlowing` from `PhoneBridge.shared.uploadedSampleCount` deltas (baseline-skip on first read). **Note:** a later Phase 3 task refactors this class's `tick()` to delegate to the pure `DataFlowEvaluator`; this task only moves it verbatim.

- [ ] **Step 1: Cut `RecordingHealthStore` from `iPhoneView_v4.swift`**

Locate `final class RecordingHealthStore: ObservableObject { … }` (~line 1375 to its closing brace ~line 1400). Cut the whole class. Do **not** cut `FTRecordingHealth` (the View just below it) — that stays in the legacy file and dies with it in Task 35.

- [ ] **Step 2: Paste into the new file**

Create `watch_streamer/WatchStreamer/Stores/RecordingHealthStore.swift`:

```swift
import SwiftUI

// (paste the exact RecordingHealthStore class cut from iPhoneView_v4.swift,
//  unchanged: static let shared, @Published private(set) var dataFlowing,
//  the private lastUploaded/lastProgressAt/timer, init() with the 1 Hz
//  RunLoop timer, and the tick() reading PhoneBridge.shared.uploadedSampleCount)
```

- [ ] **Step 3: Verify (you)**

Run (you): `⌘B`.
Expected: builds clean. `FTRecordingHealth` (legacy) still observes `RecordingHealthStore.shared`.

- [ ] **Step 4: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/RecordingHealthStore.swift" "watch_streamer/WatchStreamer/iPhoneView_v4.swift"
git commit -m "refactor(ios): extract RecordingHealthStore into Stores/ (behavior-preserving)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 5: Extract `FTLogStore` + `FTLogEntry` into `EventLogStore`

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/EventLogStore.swift`
- Modify: `watch_streamer/WatchStreamer/iPhoneView_v4.swift` (remove `FTLogEntry` struct ~line 136 and `FTLogStore` class ~lines 149–161)

**Interfaces:**
- Produces: `struct FTLogEntry` (unchanged fields) and `final class FTLogStore: ObservableObject` with `static let shared` and its existing append/published-entries API (60-entry cap). Names kept (`FTLogStore`, `FTLogEntry`) so the legacy `FTLogCard` and any `FTLogStore.shared.append(...)` call sites compile unchanged. Admin's `LogCard` (Phase 6) will consume `FTLogStore.shared`.

- [ ] **Step 1: Cut both declarations from `iPhoneView_v4.swift`**

Cut `struct FTLogEntry { … }` (~line 136) and `final class FTLogStore: ObservableObject { … }` (~line 149) — the entry struct and its store. Leave `FTLogCard` (the View) in the legacy file.

- [ ] **Step 2: Paste into the new file**

Create `watch_streamer/WatchStreamer/Stores/EventLogStore.swift`:

```swift
import SwiftUI

// (paste FTLogEntry struct + FTLogStore class verbatim from iPhoneView_v4.swift)
```

- [ ] **Step 3: Verify (you)**

Run (you): `⌘B`.
Expected: builds clean. All `FTLogStore.shared.append(...)` sites across the legacy file resolve to the moved class.

- [ ] **Step 4: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/EventLogStore.swift" "watch_streamer/WatchStreamer/iPhoneView_v4.swift"
git commit -m "refactor(ios): extract FTLogStore/FTLogEntry into Stores/EventLogStore (behavior-preserving)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 6: Create the `ScrybeTests` Swift Testing target (Xcode GUI step)

This is the **one** task that requires Xcode project surgery — a new native target cannot be created by dropping files on disk. It is a manual GUI operation; the plan documents it exactly.

**Files:**
- Create (via Xcode): a new unit-test target `ScrybeTests` rooted at `watch_streamer/ScrybeTests/`
- Create: `watch_streamer/ScrybeTests/SmokeTests.swift` (a trivial test proving the target runs + `@testable import` resolves)

**Interfaces:**
- Produces: a runnable test target where Phase 2 logic tests live; `@testable import WatchStreamer` resolves so pure-logic types in the app target are visible.

- [ ] **Step 1: Create the target (you, in Xcode)**

1. **File → New → Target…** → iOS tab → **Unit Testing Bundle** → Next.
2. Product Name: `ScrybeTests`. **Testing System: Swift Testing.** Team: None. **Target to be Tested / Host Application: `WatchStreamer`.** Finish.
3. Xcode creates a `ScrybeTests` group with a starter file. In the **File Inspector**, confirm the new target's files live under `watch_streamer/ScrybeTests/` on disk (move the folder there if Xcode placed it elsewhere, so it sits beside `WatchStreamer/`).
4. Select the `ScrybeTests` target → **Build Phases** → confirm it depends on `WatchStreamer`. Build Settings → confirm `IPHONEOS_DEPLOYMENT_TARGET = 16.0` (match the app).

- [ ] **Step 2: Replace the starter test with a smoke test**

Replace the auto-generated file contents at `watch_streamer/ScrybeTests/SmokeTests.swift`:

```swift
import Testing
@testable import WatchStreamer

@Suite("Scrybe test target smoke")
struct SmokeTests {
    @Test("target runs and app module imports")
    func targetRuns() {
        #expect(Bool(true))
    }
}
```

- [ ] **Step 3: Run the test target (you)**

Run (you): `⌘U` (scheme `WatchStreamer`), or
`xcodebuild test -scheme WatchStreamer -destination 'platform=iOS Simulator,name=iPhone 15' -only-testing:ScrybeTests`
Expected: 1 test passes. This confirms the target builds, runs, and `@testable import WatchStreamer` resolves. (The bodies are pure logic; Xcode still runs them on a simulator destination — "no simulator needed" in the spec means no UI interaction, not no destination.)

- [ ] **Step 4: Commit**

```bash
git add watch_streamer/WatchStreamer.xcodeproj/project.pbxproj "watch_streamer/ScrybeTests/SmokeTests.swift"
git commit -m "test(ios): add ScrybeTests Swift Testing target (first test target)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE 2 — Pure logic (Swift Testing, test-first)

> These are view-free value types in `Scrybe/Logic/`, each `@testable import`-ed by `ScrybeTests`. Written test-first; you run `⌘U` and report pass/fail. They carry the spec's §9 test surface.

### Task 7: `TimeFormatting` — `h:mm` and `"1h 47m"`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/TimeFormatting.swift`
- Test: `watch_streamer/ScrybeTests/TimeFormattingTests.swift`

**Interfaces:**
- Produces: `enum TimeFormatting` with `static func clock(seconds: Double) -> String` (→ `"1:47"`, hours:minutes, no zero-pad on hours) and `static func human(seconds: Double) -> String` (→ `"1h 47m"`; `"47m"` when under an hour; `"0m"` at zero). Minutes are floored. Consumed by `InkRing`, `TodayView`, `TrendsView`, `HistoryView`, `DayDetailView`.

- [ ] **Step 1: Write the failing tests**

```swift
import Testing
@testable import WatchStreamer

@Suite("TimeFormatting")
struct TimeFormattingTests {
    @Test("clock formats hours:minutes", arguments: [
        (6420.0, "1:47"), (0.0, "0:00"), (59.0, "0:00"), (3600.0, "1:00"),
    ])
    func clock(seconds: Double, expected: String) {
        #expect(TimeFormatting.clock(seconds: seconds) == expected)
    }

    @Test("human formats compactly", arguments: [
        (6420.0, "1h 47m"), (2820.0, "47m"), (0.0, "0m"), (7200.0, "2h 0m"),
    ])
    func human(seconds: Double, expected: String) {
        #expect(TimeFormatting.human(seconds: seconds) == expected)
    }
}
```

- [ ] **Step 2: Run to verify failure (you)**

Run (you): `⌘U` (or `xcodebuild test … -only-testing:ScrybeTests/TimeFormattingTests`).
Expected: FAIL to compile — `TimeFormatting` undefined.

- [ ] **Step 3: Implement**

```swift
import Foundation

enum TimeFormatting {
    static func clock(seconds: Double) -> String {
        let total = Int(max(0, seconds)) / 60
        return "\(total / 60):\(String(format: "%02d", total % 60))"
    }

    static func human(seconds: Double) -> String {
        let total = Int(max(0, seconds)) / 60
        let h = total / 60
        let m = total % 60
        return h > 0 ? "\(h)h \(m)m" : "\(m)m"
    }
}
```

- [ ] **Step 4: Run to verify pass (you)**

Run (you): `⌘U`.
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Logic/TimeFormatting.swift" "watch_streamer/ScrybeTests/TimeFormattingTests.swift"
git commit -m "feat(scrybe): TimeFormatting (clock + human) with tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 8: `DailyGoalProgress` — fraction, percent, isMet

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/DailyGoalProgress.swift`
- Test: `watch_streamer/ScrybeTests/DailyGoalProgressTests.swift`

**Interfaces:**
- Produces: `struct DailyGoalProgress { init(writingSeconds: Double, goalSeconds: Double) }` exposing `let fraction: Double` (clamped 0…1, for the ring), `let percent: Int` (rounded, **uncapped** so 120 % can be shown in text), `let isMet: Bool` (`writingSeconds >= goalSeconds`, goal > 0). Consumed by `InkRing`/`TodayView` (fraction + percent) and `StreakCalculator` callers.

- [ ] **Step 1: Write the failing tests**

```swift
import Testing
@testable import WatchStreamer

@Suite("DailyGoalProgress")
struct DailyGoalProgressTests {
    @Test("fraction clamps 0...1", arguments: [
        (3600.0, 7200.0, 0.5), (9000.0, 7200.0, 1.0), (0.0, 7200.0, 0.0),
    ])
    func fraction(writing: Double, goal: Double, expected: Double) {
        #expect(DailyGoalProgress(writingSeconds: writing, goalSeconds: goal).fraction == expected)
    }

    @Test("percent rounds, uncapped", arguments: [
        (5256.0, 7200.0, 73), (9000.0, 7200.0, 125),
    ])
    func percent(writing: Double, goal: Double, expected: Int) {
        #expect(DailyGoalProgress(writingSeconds: writing, goalSeconds: goal).percent == expected)
    }

    @Test("isMet at/above goal; zero goal never met")
    func met() {
        #expect(DailyGoalProgress(writingSeconds: 7200, goalSeconds: 7200).isMet)
        #expect(!DailyGoalProgress(writingSeconds: 7199, goalSeconds: 7200).isMet)
        let zero = DailyGoalProgress(writingSeconds: 100, goalSeconds: 0)
        #expect(!zero.isMet)
        #expect(zero.fraction == 0.0)
    }
}
```

- [ ] **Step 2: Run to verify failure (you)**

Run (you): `⌘U`.
Expected: FAIL — `DailyGoalProgress` undefined.

- [ ] **Step 3: Implement**

```swift
import Foundation

struct DailyGoalProgress {
    let fraction: Double
    let percent: Int
    let isMet: Bool

    init(writingSeconds: Double, goalSeconds: Double) {
        guard goalSeconds > 0 else {
            fraction = 0
            percent = 0
            isMet = false
            return
        }
        let raw = writingSeconds / goalSeconds
        fraction = min(1.0, max(0.0, raw))
        percent = Int((raw * 100).rounded())
        isMet = writingSeconds >= goalSeconds
    }
}
```

- [ ] **Step 4: Run to verify pass (you)**

Run (you): `⌘U`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Logic/DailyGoalProgress.swift" "watch_streamer/ScrybeTests/DailyGoalProgressTests.swift"
git commit -m "feat(scrybe): DailyGoalProgress (fraction/percent/isMet) with tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 9: `StreakCalculator` — goal-met consecutive days

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/StreakCalculator.swift`
- Test: `watch_streamer/ScrybeTests/StreakCalculatorTests.swift`

**Interfaces:**
- Consumes: `DailyGoalProgress` (Task 8) for the `isMet` rule.
- Produces: `struct DayWriting { let date: String; let writingSeconds: Double }` (date = `"YYYY-MM-DD"`, matching the `/focus` DTO day shape) and `enum StreakCalculator { static func currentStreak(days: [DayWriting], goalSeconds: Double, todayISO: String) -> Int }`. Rule: count consecutive goal-met days ending at today; if **today** is not met it is "pending" (skipped, not breaking) and counting starts at yesterday; the first non-met day before that stops the count. Consumed by `TodayView` (streak chip) and `StreakCalendar`.

- [ ] **Step 1: Write the failing tests**

```swift
import Testing
@testable import WatchStreamer

@Suite("StreakCalculator")
struct StreakCalculatorTests {
    // Helper: build N consecutive ISO dates ending at `today`, oldest first.
    private func days(_ secs: [Double], endingAt today: String) -> [DayWriting] {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = .current
        let end = fmt.date(from: today)!
        return secs.enumerated().map { i, s in
            let d = Calendar.current.date(byAdding: .day,
                        value: -(secs.count - 1 - i), to: end)!
            return DayWriting(date: fmt.string(from: d), writingSeconds: s)
        }
    }

    @Test("counts consecutive goal-met days including today")
    func includesToday() {
        let d = days([8000, 8000, 8000], endingAt: "2026-06-22")
        #expect(StreakCalculator.currentStreak(days: d, goalSeconds: 7200, todayISO: "2026-06-22") == 3)
    }

    @Test("today pending does not break a streak through yesterday")
    func todayPending() {
        let d = days([8000, 8000, 100], endingAt: "2026-06-22")  // today under goal
        #expect(StreakCalculator.currentStreak(days: d, goalSeconds: 7200, todayISO: "2026-06-22") == 2)
    }

    @Test("a missed prior day breaks the streak")
    func brokenByMiss() {
        let d = days([8000, 100, 8000], endingAt: "2026-06-22")  // yesterday missed
        #expect(StreakCalculator.currentStreak(days: d, goalSeconds: 7200, todayISO: "2026-06-22") == 1)
    }

    @Test("no data is zero")
    func empty() {
        #expect(StreakCalculator.currentStreak(days: [], goalSeconds: 7200, todayISO: "2026-06-22") == 0)
    }
}
```

- [ ] **Step 2: Run to verify failure (you)**

Run (you): `⌘U`.
Expected: FAIL — `DayWriting` / `StreakCalculator` undefined.

- [ ] **Step 3: Implement**

```swift
import Foundation

struct DayWriting: Sendable {
    let date: String          // "YYYY-MM-DD"
    let writingSeconds: Double
}

enum StreakCalculator {
    static func currentStreak(days: [DayWriting], goalSeconds: Double, todayISO: String) -> Int {
        guard goalSeconds > 0, !days.isEmpty else { return 0 }
        let met = Dictionary(uniqueKeysWithValues: days.map {
            ($0.date, DailyGoalProgress(writingSeconds: $0.writingSeconds, goalSeconds: goalSeconds).isMet)
        })

        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = .current
        guard let today = fmt.date(from: todayISO) else { return 0 }

        var streak = 0
        var cursor = today
        var isFirst = true
        while true {
            let iso = fmt.string(from: cursor)
            let dayMet = met[iso] ?? false
            if dayMet {
                streak += 1
            } else if isFirst {
                // Today pending: skip without breaking, then require met days.
            } else {
                break
            }
            isFirst = false
            guard let prev = Calendar.current.date(byAdding: .day, value: -1, to: cursor) else { break }
            cursor = prev
            // Stop once we run past the available data window.
            if met[fmt.string(from: cursor)] == nil && fmt.string(from: cursor) < (days.first?.date ?? iso) {
                break
            }
        }
        return streak
    }
}
```

- [ ] **Step 4: Run to verify pass (you)**

Run (you): `⌘U`.
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Logic/StreakCalculator.swift" "watch_streamer/ScrybeTests/StreakCalculatorTests.swift"
git commit -m "feat(scrybe): StreakCalculator (goal-met consecutive days, today pending) with tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 10: `DataFlowEvaluator` — counter delta + baseline-skip

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Logic/DataFlowEvaluator.swift`
- Test: `watch_streamer/ScrybeTests/DataFlowEvaluatorTests.swift`

**Interfaces:**
- Produces: `struct DataFlowEvaluator` with `mutating func update(count: Int, now: Date) -> Bool`. Returns whether the upload counter has advanced within the last `window` seconds (default 5). **Baseline-skip:** the first `update` records the baseline and returns `false` (no progress yet) even if `count > 0`. Mirrors the existing `RecordingHealthStore.tick()` logic so the Phase 3 refactor can delegate to it. Consumed by `RecordingHealthStore` (Phase 3 refactor).

- [ ] **Step 1: Write the failing tests**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("DataFlowEvaluator")
struct DataFlowEvaluatorTests {
    @Test("first observation is baseline, not flow")
    func baselineSkip() {
        var e = DataFlowEvaluator()
        #expect(e.update(count: 1000, now: Date()) == false)
    }

    @Test("counter increase within window is flowing")
    func flows() {
        var e = DataFlowEvaluator()
        let t0 = Date()
        _ = e.update(count: 1000, now: t0)
        #expect(e.update(count: 1010, now: t0.addingTimeInterval(1)) == true)
    }

    @Test("stale: no increase past window is not flowing")
    func stale() {
        var e = DataFlowEvaluator()
        let t0 = Date()
        _ = e.update(count: 1000, now: t0)
        _ = e.update(count: 1010, now: t0.addingTimeInterval(1))
        #expect(e.update(count: 1010, now: t0.addingTimeInterval(7)) == false)
    }
}
```

- [ ] **Step 2: Run to verify failure (you)**

Run (you): `⌘U`.
Expected: FAIL — `DataFlowEvaluator` undefined.

- [ ] **Step 3: Implement**

```swift
import Foundation

struct DataFlowEvaluator {
    var window: TimeInterval = 5.0

    private var lastCount: Int?
    private var lastProgressAt: Date = .distantPast

    mutating func update(count: Int, now: Date) -> Bool {
        // Why: skip the first observation — only a real increase counts as
        // progress, otherwise the baseline read registers as flow on launch.
        if let last = lastCount, count > last {
            lastProgressAt = now
        }
        lastCount = count
        return now.timeIntervalSince(lastProgressAt) < window
    }
}
```

- [ ] **Step 4: Run to verify pass (you)**

Run (you): `⌘U`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Logic/DataFlowEvaluator.swift" "watch_streamer/ScrybeTests/DataFlowEvaluatorTests.swift"
git commit -m "feat(scrybe): DataFlowEvaluator (counter delta + baseline-skip) with tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE 3 — Networking + Stores

### Task 11: Focus DTOs + decode tests

**Files:**
- Create: `watch_streamer/WatchStreamer/Networking/FocusDTO.swift`
- Test: `watch_streamer/ScrybeTests/FocusDTOTests.swift`

**Interfaces:**
- Produces: `FocusStretchDTO` (`startMs/endMs/durationS`, `Identifiable`), `FocusTodayDTO` (`date`, `totalWritingSeconds`, `stretches: [FocusStretchDTO]`, `tickCount`, `dayStartMs`, `dayEndMs`, `nowMs`), `FocusDayDTO` (`date`, `weekday`, `writingSeconds`, `isToday`, `Identifiable` by `date`), and `FocusRangeDTO` (`days: [FocusDayDTO]`, `today`, `maxSeconds`) — shared by `/focus/week` **and** `/focus/history` (identical shapes). All `Decodable`. Field names map the server's snake_case via `CodingKeys`. Consumed by `FocusAPI` (Task 12) and `FocusStore` (Task 15).

- [ ] **Step 1: Write the failing decode tests**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("Focus DTO decoding")
struct FocusDTOTests {
    @Test("today decodes snake_case")
    func today() throws {
        let json = """
        {"date":"2026-06-22","day_start_ms":1,"day_end_ms":2,"now_ms":1,
         "total_writing_seconds":6420.0,"tick_count":42,
         "stretches":[{"start_ms":10,"end_ms":20,"duration_s":10.0}]}
        """.data(using: .utf8)!
        let dto = try JSONDecoder().decode(FocusTodayDTO.self, from: json)
        #expect(dto.totalWritingSeconds == 6420.0)
        #expect(dto.tickCount == 42)
        let first = try #require(dto.stretches.first)
        #expect(first.durationS == 10.0)
    }

    @Test("range (week/history) decodes")
    func range() throws {
        let json = """
        {"today":"2026-06-22","max_seconds":9000.0,
         "days":[{"date":"2026-06-21","weekday":"Sun","writing_seconds":3600.0,"is_today":false},
                 {"date":"2026-06-22","weekday":"Mon","writing_seconds":9000.0,"is_today":true}]}
        """.data(using: .utf8)!
        let dto = try JSONDecoder().decode(FocusRangeDTO.self, from: json)
        #expect(dto.days.count == 2)
        #expect(dto.days.last?.isToday == true)
        #expect(dto.maxSeconds == 9000.0)
    }
}
```

- [ ] **Step 2: Run to verify failure (you)**

Run (you): `⌘U`. Expected: FAIL — DTO types undefined.

- [ ] **Step 3: Implement the DTOs**

```swift
import Foundation

struct FocusStretchDTO: Decodable, Identifiable, Sendable {
    let startMs: Int
    let endMs: Int
    let durationS: Double
    var id: Int { startMs }

    enum CodingKeys: String, CodingKey {
        case startMs = "start_ms"
        case endMs = "end_ms"
        case durationS = "duration_s"
    }
}

struct FocusTodayDTO: Decodable, Sendable {
    let date: String
    let totalWritingSeconds: Double
    let stretches: [FocusStretchDTO]
    let tickCount: Int
    let dayStartMs: Int
    let dayEndMs: Int
    let nowMs: Int

    enum CodingKeys: String, CodingKey {
        case date, stretches
        case totalWritingSeconds = "total_writing_seconds"
        case tickCount = "tick_count"
        case dayStartMs = "day_start_ms"
        case dayEndMs = "day_end_ms"
        case nowMs = "now_ms"
    }
}

struct FocusDayDTO: Decodable, Identifiable, Sendable {
    let date: String
    let weekday: String
    let writingSeconds: Double
    let isToday: Bool
    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date, weekday
        case writingSeconds = "writing_seconds"
        case isToday = "is_today"
    }
}

struct FocusRangeDTO: Decodable, Sendable {
    let days: [FocusDayDTO]
    let today: String
    let maxSeconds: Double

    enum CodingKeys: String, CodingKey {
        case days, today
        case maxSeconds = "max_seconds"
    }
}
```

- [ ] **Step 4: Run to verify pass (you)**

Run (you): `⌘U`. Expected: both decode tests PASS.

- [ ] **Step 5: Commit**

```bash
git add "watch_streamer/WatchStreamer/Networking/FocusDTO.swift" "watch_streamer/ScrybeTests/FocusDTOTests.swift"
git commit -m "feat(scrybe): Focus DTOs (today/range) with decode tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 12: `FocusAPI` HTTP client

**Files:**
- Create: `watch_streamer/WatchStreamer/Networking/FocusAPI.swift`

**Interfaces:**
- Consumes: `PhoneBridge.serverBaseURL` (existing static), the DTOs from Task 11.
- Produces: `struct FocusAPI` with `func today() async throws -> FocusTodayDTO`, `func week() async throws -> FocusRangeDTO`, `func history(days: Int) async throws -> FocusRangeDTO`. Mirrors the existing `LiveQualityStore` HTTP pattern (6 s timeout, status-code guard). Consumed by `FocusStore` (Task 15).

- [ ] **Step 1: Implement the client**

```swift
import Foundation

struct FocusAPI {
    // No stored closure (would be non-Sendable). Reads the base URL inline.
    func today() async throws -> FocusTodayDTO { try await get("/focus/today") }
    func week() async throws -> FocusRangeDTO { try await get("/focus/week") }
    func history(days: Int) async throws -> FocusRangeDTO {
        try await get("/focus/history?days=\(days)")
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let url = URL(string: PhoneBridge.serverBaseURL + path) else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        req.timeoutInterval = 6
        let (data, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
```

- [ ] **Step 2: Verify it builds (you)**

Run (you): `⌘B`. Expected: builds clean. (No automated network test — it's exercised live in Task 15's manual smoke.)

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Networking/FocusAPI.swift"
git commit -m "feat(scrybe): FocusAPI client for /focus/{today,week,history}

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 13: `LiveInferencePayload` decode + wire into `ServerCommandListener`

**Files:**
- Create: `watch_streamer/WatchStreamer/Networking/LiveInferencePayload.swift`
- Modify: `watch_streamer/WatchStreamer/ServerCommandListener.swift` (add `@Published var liveInference` + extract `live_inference` from the WS frame)
- Test: `watch_streamer/ScrybeTests/LiveInferenceTests.swift`

**Interfaces:**
- Produces: `struct LiveInferencePayload: Decodable` (fields per the server's three tick shapes — `writing`, `proba`, `fsHz`, `todayWritingSeconds` always present; `modelId`, `personId`, `windowSamples`, `rateMismatch`, `trainedFsHz`, `missingChannels` optional). Adds `@Published var liveInference: LiveInferencePayload?` to `ServerCommandListener`, updated each WS status frame. Consumed by `LiveChip` (Phase 4), `TodayView`/`FocusStore` (Phase 3/5), `RecordingHealthCard` (Phase 6).

- [ ] **Step 1: Write the failing decode test**

```swift
import Testing
import Foundation
@testable import WatchStreamer

@Suite("LiveInferencePayload decoding")
struct LiveInferenceTests {
    @Test("normal tick decodes; optional fields absent")
    func normal() throws {
        let json = """
        {"writing":true,"proba":0.91,"model_id":"rf_noah","person_id":"noah",
         "fs_hz":100.0,"window_samples":100,"today_writing_seconds":6420.0}
        """.data(using: .utf8)!
        let p = try JSONDecoder().decode(LiveInferencePayload.self, from: json)
        #expect(p.writing == true)
        #expect(p.proba == 0.91)
        #expect(p.todayWritingSeconds == 6420.0)
        #expect(p.rateMismatch == nil)
    }

    @Test("rate-mismatch tick decodes with null model_id")
    func mismatch() throws {
        let json = """
        {"writing":false,"proba":0.0,"model_id":null,"person_id":null,
         "fs_hz":40.0,"trained_fs_hz":100.0,"rate_mismatch":true,
         "today_writing_seconds":12.0}
        """.data(using: .utf8)!
        let p = try JSONDecoder().decode(LiveInferencePayload.self, from: json)
        #expect(p.rateMismatch == true)
        #expect(p.modelId == nil)
        #expect(p.writing == false)
    }
}
```

- [ ] **Step 2: Run to verify failure (you)**

Run (you): `⌘U`. Expected: FAIL — `LiveInferencePayload` undefined.

- [ ] **Step 3: Implement the payload type**

```swift
import Foundation

struct LiveInferencePayload: Decodable, Equatable, Sendable {
    let writing: Bool
    let proba: Double
    let fsHz: Double
    let todayWritingSeconds: Double
    let modelId: String?
    let personId: String?
    let windowSamples: Int?
    let rateMismatch: Bool?
    let trainedFsHz: Double?
    let missingChannels: Bool?

    enum CodingKeys: String, CodingKey {
        case writing, proba
        case fsHz = "fs_hz"
        case todayWritingSeconds = "today_writing_seconds"
        case modelId = "model_id"
        case personId = "person_id"
        case windowSamples = "window_samples"
        case rateMismatch = "rate_mismatch"
        case trainedFsHz = "trained_fs_hz"
        case missingChannels = "missing_channels"
    }
}
```

- [ ] **Step 4: Run to verify pass (you)**

Run (you): `⌘U`. Expected: both decode tests PASS.

- [ ] **Step 5: Wire it into `ServerCommandListener`**

In `ServerCommandListener.swift`:

(a) Add the published property next to the other `@Published` declarations (near the top of the class, by `currentSessionId`):

```swift
@Published var liveInference: LiveInferencePayload?
```

(b) Add this private helper method to the class:

```swift
// Live-Inference rides on the 1 Hz status broadcast as a nested object.
// A missing/null live_inference (predict() returned None this tick) keeps
// the last value rather than flickering the UI off.
private func updateLiveInference(from json: [String: Any]) {
    guard let dict = json["live_inference"] as? [String: Any],
          let data = try? JSONSerialization.data(withJSONObject: dict),
          let payload = try? JSONDecoder().decode(LiveInferencePayload.self, from: data) else {
        return
    }
    DispatchQueue.main.async { self.liveInference = payload }
}
```

(c) Call it where the incoming WS frame has been parsed to a `[String: Any]`. In `handle(...)` the frame is already available as a dictionary (the method that does `JSONSerialization.jsonObject(...) as? [String: Any]` before switching on `type`). Add, immediately after that dictionary is obtained and before/after the `type` switch:

```swift
updateLiveInference(from: json)
```

(Use the actual local variable name the file uses for the parsed dictionary — it is the same object the `type` is read from.)

- [ ] **Step 6: Verify build + live smoke (you)**

Run (you): `⌘B`, then run the app against a live server that is streaming inference. Confirm (via a temporary `print` or the Phase 4 `LiveChip`) that `ServerCommandListener.shared.liveInference` becomes non-nil and `writing` toggles. Expected: builds; payload populates ~1 Hz.

- [ ] **Step 7: Commit**

```bash
git add "watch_streamer/WatchStreamer/Networking/LiveInferencePayload.swift" "watch_streamer/WatchStreamer/ServerCommandListener.swift" "watch_streamer/ScrybeTests/LiveInferenceTests.swift"
git commit -m "feat(scrybe): decode status.live_inference + publish on ServerCommandListener

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 14: `ScrybeSettings` (daily goal + admin PIN)

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/ScrybeSettings.swift`

**Interfaces:**
- Produces: `enum ScrybeSettings` with `static let goalKey`, `static let defaultGoalSeconds: Double` (= `2 * 3600`), `static let pinKey`, `static let defaultPIN` (= `"0000"`), and computed `static var goalSeconds: Double` / `static var adminPIN: String` reading `UserDefaults`. Views bind via `@AppStorage(ScrybeSettings.goalKey)`; `FocusStore` and `StreakCalculator` callers read `ScrybeSettings.goalSeconds`; `AdminGateView` reads `adminPIN`. **Default PIN `0000`, changeable in Admin → Settings (Task 32).**

- [ ] **Step 1: Implement**

```swift
import Foundation

enum ScrybeSettings {
    // Daily writing goal in seconds; default 2 h.
    static let goalKey = "scrybe.dailyGoalSeconds"
    static let defaultGoalSeconds: Double = 2 * 3600

    // Local admin PIN — a lock against accidental opens, not a security feature.
    static let pinKey = "scrybe.adminPIN"
    static let defaultPIN = "0000"

    static var goalSeconds: Double {
        let v = UserDefaults.standard.double(forKey: goalKey)
        return v > 0 ? v : defaultGoalSeconds
    }

    static var adminPIN: String {
        let v = UserDefaults.standard.string(forKey: pinKey)
        return (v?.isEmpty == false) ? v! : defaultPIN
    }
}
```

- [ ] **Step 2: Verify build (you)**

Run (you): `⌘B`. Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/ScrybeSettings.swift"
git commit -m "feat(scrybe): ScrybeSettings (daily goal + admin PIN keys/defaults)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 15: `FocusStore` (load `/focus/*`, derive streak/goal, offline)

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/FocusStore.swift`

**Interfaces:**
- Consumes: `FocusAPI` (Task 12), DTOs (Task 11), `ScrybeSettings` (Task 14), `DailyGoalProgress`/`StreakCalculator`/`DayWriting` (Phase 2), `ServerCommandListener.shared.liveInference` (Task 13).
- Produces: `@MainActor final class FocusStore: ObservableObject` singleton with `@Published private(set) today/week/history/isOffline/lastUpdated`, `func start()/stop()/refresh() async`, and non-published derivations `goalProgress`, `streak`, `todayWritingSecondsPolled`. **Re-render note:** views that must update live (ring seconds, chip) observe `ServerCommandListener.shared` directly and combine with `FocusStore`'s polled values — `FocusStore` does not republish the 1 Hz WS counter (spec §7: don't pull high-frequency counters into views that needn't react). Consumed by `TodayView`/`TrendsView`/`HistoryView` (Phase 5).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

@MainActor
final class FocusStore: ObservableObject {
    static let shared = FocusStore()

    @Published private(set) var today: FocusTodayDTO?
    @Published private(set) var week: FocusRangeDTO?
    @Published private(set) var history: FocusRangeDTO?
    @Published private(set) var isOffline = false
    @Published private(set) var lastUpdated: Date?

    private let api = FocusAPI()
    private var pollTask: Task<Void, Never>?
    private let historyDays = 90

    private init() {}

    func start() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    func refresh() async {
        do {
            async let t = api.today()
            async let w = api.week()
            async let h = api.history(days: historyDays)
            let (td, wk, hi) = try await (t, w, h)
            today = td
            week = wk
            history = hi
            isOffline = false
            lastUpdated = Date()
        } catch is CancellationError {
            // poll cancelled — keep state
        } catch {
            isOffline = true   // keep last good values
        }
    }

    // Polled-only today seconds (does not include the live WS counter).
    var todayWritingSecondsPolled: Double { today?.totalWritingSeconds ?? 0 }

    var goalProgress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: todayWritingSecondsPolled,
                          goalSeconds: ScrybeSettings.goalSeconds)
    }

    var streak: Int {
        let days = (history?.days ?? []).map {
            DayWriting(date: $0.date, writingSeconds: $0.writingSeconds)
        }
        let todayISO = history?.today ?? today?.date ?? ""
        return StreakCalculator.currentStreak(
            days: days, goalSeconds: ScrybeSettings.goalSeconds, todayISO: todayISO)
    }

    /// True writing-now: prefers the live WS value, else last poll.
    var hasData: Bool { today != nil || history != nil }
}
```

- [ ] **Step 2: Verify build + live smoke (you)**

Run (you): `⌘B`, then run against a live server. Add a temporary `.onAppear { FocusStore.shared.start() }` in any visible view (the real wiring lands in Phase 5) and confirm `FocusStore.shared.today` populates and `isOffline` flips when the server is stopped. Expected: builds; poll populates; offline toggles without hanging.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/FocusStore.swift"
git commit -m "feat(scrybe): FocusStore (poll /focus/*, derive streak/goal, offline-tolerant)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 16: Refactor `RecordingHealthStore` to use `DataFlowEvaluator`

**Files:**
- Modify: `watch_streamer/WatchStreamer/Stores/RecordingHealthStore.swift` (the file extracted in Task 4)

**Interfaces:**
- Consumes: `DataFlowEvaluator` (Task 10).
- Produces: same public surface (`static let shared`, `@Published private(set) var dataFlowing: Bool`) but the decision now delegates to the tested `DataFlowEvaluator`, removing the duplicated inline logic. No consumer changes.

- [ ] **Step 1: Replace the store body**

Replace the contents of `watch_streamer/WatchStreamer/Stores/RecordingHealthStore.swift`:

```swift
import SwiftUI

final class RecordingHealthStore: ObservableObject {
    static let shared = RecordingHealthStore()
    @Published private(set) var dataFlowing = false

    private var evaluator = DataFlowEvaluator()
    private var timer: Timer?

    private init() {
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    @MainActor
    private func tick() {
        let flowing = evaluator.update(count: PhoneBridge.shared.uploadedSampleCount, now: Date())
        if flowing != dataFlowing { dataFlowing = flowing }
    }
}
```

- [ ] **Step 2: Verify build (you)**

Run (you): `⌘B`, then `⌘U` (the `DataFlowEvaluatorTests` from Task 10 now cover this store's logic). Expected: builds; tests pass. The legacy `FTRecordingHealth` and the Phase 6 `RecordingHealthCard` see identical `dataFlowing` behavior.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/RecordingHealthStore.swift"
git commit -m "refactor(scrybe): RecordingHealthStore delegates to tested DataFlowEvaluator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE 4 — Signature components

> Pure SwiftUI leaves. No unit tests — each ends with a `#Preview`, a `⌘B`, a screenshot against the confirmed mockups, and a quality-skill review. They consume `ScrybeTheme` via `@Environment(\.scrybe)` and the Phase 2/3 logic + DTOs.

### Task 17: `InkRing`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/InkRing.swift`

**Interfaces:**
- Consumes: `@Environment(\.scrybe)`.
- Produces: `struct InkRing: View` with `let fraction: Double`, `let lineWidth: CGFloat`, `var centerText: String?`, `var subtitle: String?`. The hero progress ring (round cap, indigo accent on a faint ink track). Consumed by `TodayView` (Task 22).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct InkRing: View {
    let fraction: Double
    var lineWidth: CGFloat = 16
    var centerText: String? = nil
    var subtitle: String? = nil

    @Environment(\.scrybe) private var theme

    var body: some View {
        ZStack {
            Circle().stroke(theme.ink.opacity(0.10), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: max(0.001, min(1, fraction)))
                .stroke(theme.accent,
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.easeInOut(duration: 0.6), value: fraction)
            VStack(spacing: 4) {
                if let centerText {
                    Text(centerText)
                        .font(.system(.largeTitle, design: .serif).weight(.semibold))
                        .foregroundStyle(theme.ink)
                        .monospacedDigit()
                }
                if let subtitle {
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(theme.sepia)
                        .multilineTextAlignment(.center)
                }
            }
            .padding(lineWidth * 2)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Schreibzeit heute")
        .accessibilityValue("\(centerText ?? ""), \(subtitle ?? "")")
    }
}

#Preview {
    InkRing(fraction: 0.73, centerText: "1:47", subtitle: "73 % · Ziel 2 h")
        .frame(width: 240, height: 240)
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; open the Preview canvas; send a screenshot. Compare against the confirmed "Heute" mockup. Then (Claude, after restart) review with `swiftui-pro` + `swiftui-design-principles` + `swiftui-accessibility-auditor`. Expected: ring matches the mockup (round cap, indigo on faint track, serif center number); no skill blockers.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Components/InkRing.swift"
git commit -m "feat(scrybe): InkRing progress ring component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 18: `WeekStrip`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/WeekStrip.swift`

**Interfaces:**
- Consumes: `[FocusDayDTO]`, `maxSeconds: Double`, `@Environment(\.scrybe)`.
- Produces: `struct WeekStrip: View` with `let days: [FocusDayDTO]`, `let maxSeconds: Double`. Seven capsule bars, today highlighted in accent. Consumed by `TodayView` (Task 22) + `TrendsView` (Task 23).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct WeekStrip: View {
    let days: [FocusDayDTO]
    let maxSeconds: Double
    var maxBarHeight: CGFloat = 70

    @Environment(\.scrybe) private var theme

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ForEach(days) { day in
                VStack(spacing: 6) {
                    Capsule()
                        .fill(day.isToday ? theme.accent : theme.ink.opacity(0.18))
                        .frame(width: 10, height: barHeight(day.writingSeconds))
                    Text(String(day.weekday.prefix(2)))
                        .font(.caption2)
                        .foregroundStyle(day.isToday ? theme.ink : theme.sepia.opacity(0.7))
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(day.weekday)
                .accessibilityValue(TimeFormatting.human(seconds: day.writingSeconds))
            }
        }
        .frame(height: maxBarHeight + 20, alignment: .bottom)
    }

    private func barHeight(_ s: Double) -> CGFloat {
        guard maxSeconds > 0 else { return 4 }
        return max(4, CGFloat(s / maxSeconds) * maxBarHeight)
    }
}

#Preview {
    WeekStrip(
        days: (0..<7).map { i in
            FocusDayDTO(date: "2026-06-\(16 + i)",
                        weekday: ["Tue","Wed","Thu","Fri","Sat","Sun","Mon"][i],
                        writingSeconds: Double([3600,5400,1200,7200,0,4800,6420][i]),
                        isToday: i == 6)
        },
        maxSeconds: 7200
    )
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
```

(Note: `FocusDayDTO` is `Decodable`; the Preview constructs it via its memberwise initializer — synthesized because all stored properties are non-private. If the compiler rejects the memberwise init due to the custom `CodingKeys`, add an explicit `init(date:weekday:writingSeconds:isToday:)` to `FocusDayDTO` in Task 11. Verify in this step.)

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot the Preview; compare to the WeekStrip mockup. Claude reviews with the SwiftUI skills. Expected: 7 bars, today accented, heights proportional.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Components/WeekStrip.swift"
git commit -m "feat(scrybe): WeekStrip seven-bar week component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 19: `StreakCalendar`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/StreakCalendar.swift`

**Interfaces:**
- Consumes: `[FocusDayDTO]`, `goalSeconds: Double`, `DailyGoalProgress` (Task 8), `@Environment(\.scrybe)`.
- Produces: `struct StreakCalendar: View` with `let days: [FocusDayDTO]`, `let goalSeconds: Double`. A habit dot grid (7 columns), goal-met days in ink-green, today ringed. Consumed by `TrendsView` (Task 23).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct StreakCalendar: View {
    let days: [FocusDayDTO]
    let goalSeconds: Double

    @Environment(\.scrybe) private var theme
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 8), count: 7)

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            ForEach(days) { day in
                Circle()
                    .fill(met(day) ? theme.success : theme.ink.opacity(0.12))
                    .frame(height: 16)
                    .overlay(Circle().stroke(theme.accent, lineWidth: day.isToday ? 2 : 0))
                    .accessibilityLabel(day.date)
                    .accessibilityValue(met(day) ? "Ziel erreicht" : "Ziel nicht erreicht")
            }
        }
    }

    private func met(_ day: FocusDayDTO) -> Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }
}

#Preview {
    StreakCalendar(
        days: (0..<28).map { i in
            FocusDayDTO(date: "2026-06-\(String(format: "%02d", i + 1))",
                        weekday: "x",
                        writingSeconds: Double(i % 4 == 0 ? 1000 : 8000),
                        isToday: i == 27)
        },
        goalSeconds: 7200
    )
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot; compare to the Streak-Kalender mockup. Claude reviews with SwiftUI skills. Expected: dot grid, met days green, today ringed.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Components/StreakCalendar.swift"
git commit -m "feat(scrybe): StreakCalendar habit dot grid component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 20: `LiveChip`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/LiveChip.swift`

**Interfaces:**
- Consumes: `@Environment(\.scrybe)`.
- Produces: `struct LiveChip: View` with `let isWriting: Bool`. Pill with a pulsing dot; "schreibt gerade" when active, "Pause" otherwise. Consumed by `TodayView` (Task 22) — driven by `ServerCommandListener.shared.liveInference?.writing`.

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct LiveChip: View {
    let isWriting: Bool

    @Environment(\.scrybe) private var theme
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(isWriting ? theme.success : theme.ink.opacity(0.25))
                .frame(width: 8, height: 8)
                .scaleEffect(isWriting && pulse ? 1.4 : 1.0)
            Text(isWriting ? "schreibt gerade" : "Pause")
                .font(.footnote.weight(.medium))
                .foregroundStyle(isWriting ? theme.ink : theme.sepia)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Capsule().fill(theme.ink.opacity(0.05)))
        .onAppear {
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                pulse = true
            }
        }
        .accessibilityLabel(isWriting ? "schreibt gerade" : "keine Schreibaktivität")
    }
}

#Preview {
    VStack(spacing: 16) {
        LiveChip(isWriting: true)
        LiveChip(isWriting: false)
    }
    .padding(40)
    .background(ScrybeTheme.standard.paper)
    .scrybeTheme()
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot both states; compare to mockup. Claude reviews with SwiftUI skills (check the repeating animation doesn't violate Reduce Motion — auditor will flag). Expected: pill matches; dot pulses only when writing.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Components/LiveChip.swift"
git commit -m "feat(scrybe): LiveChip writing-now pill component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 21: `OfflineBanner`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/Components/OfflineBanner.swift`

**Interfaces:**
- Consumes: `@Environment(\.scrybe)`.
- Produces: `struct OfflineBanner: View` (no params). A subtle warning-toned strip shown above content when `FocusStore.isOffline`. Consumed by all three Scrybe screens (Phase 5).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct OfflineBanner: View {
    @Environment(\.scrybe) private var theme

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "wifi.slash")
            Text("Offline — zuletzt bekannte Werte")
        }
        .font(.caption)
        .foregroundStyle(theme.warning)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Capsule().fill(theme.warning.opacity(0.10)))
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    OfflineBanner()
        .padding(40)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot; confirm it reads as a quiet hint, not an alarm. Claude reviews with SwiftUI skills. Expected: subtle warning strip.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/Components/OfflineBanner.swift"
git commit -m "feat(scrybe): OfflineBanner subtle offline hint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE 5 — Scrybe screens

> The pager **header (wordmark + page label + long-press→Admin)** is owned by `RootPagerView` (Phase 7). These page views render **content only**. Each observes `FocusStore.shared` (polled aggregates) and, where live updates matter, `ServerCommandListener.shared` (the 1 Hz WS counter). View tasks end with build + screenshot vs. mockup + SwiftUI-skill review.

### Task 22: `TodayView` (hero)

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/TodayView.swift`

**Interfaces:**
- Consumes: `FocusStore.shared`, `ServerCommandListener.shared.liveInference`, `InkRing`, `LiveChip`, `WeekStrip`, `OnboardingView`, `OfflineBanner`, `DailyGoalProgress`, `TimeFormatting`, `@AppStorage(ScrybeSettings.goalKey)`.
- Produces: `struct TodayView: View`. Hero ring (today's writing time, live), streak chip + live chip, week strip; empty state → `OnboardingView`. The displayed seconds = `max(polled total, live today_writing_seconds)` so the ring advances ~1 Hz from the WS counter.

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct TodayView: View {
    @ObservedObject private var focus = FocusStore.shared
    @ObservedObject private var server = ServerCommandListener.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var liveSeconds: Double {
        max(focus.todayWritingSecondsPolled, server.liveInference?.todayWritingSeconds ?? 0)
    }
    private var progress: DailyGoalProgress {
        DailyGoalProgress(writingSeconds: liveSeconds, goalSeconds: goalSeconds)
    }
    private var isWriting: Bool { server.liveInference?.writing ?? false }
    private var isEmpty: Bool {
        liveSeconds == 0 && focus.streak == 0 && (focus.week?.maxSeconds ?? 0) == 0
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                if focus.isOffline { OfflineBanner() }

                if isEmpty {
                    OnboardingView().padding(.top, 40)
                } else {
                    InkRing(
                        fraction: progress.fraction,
                        centerText: TimeFormatting.clock(seconds: liveSeconds),
                        subtitle: "\(progress.percent) % · Ziel \(TimeFormatting.human(seconds: goalSeconds))"
                    )
                    .frame(width: 240, height: 240)
                    .padding(.top, 8)

                    HStack(spacing: 12) {
                        Label("\(focus.streak) Tage", systemImage: "flame")
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(theme.sepia)
                        LiveChip(isWriting: isWriting)
                    }

                    if let week = focus.week {
                        WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
                            .padding(.horizontal)
                    }
                }
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
        .background(theme.paper.ignoresSafeArea())
    }
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; run on simulator against a live server (or use a Preview with a seeded `FocusStore`); screenshot; compare to the "Heute" mockup. Claude reviews with `swiftui-pro` + `swiftui-design-principles` + `swiftui-accessibility-auditor` + `swiftui-performance-audit`. Expected: ring + streak + live chip + week strip match the mockup; empty state shows onboarding.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/TodayView.swift"
git commit -m "feat(scrybe): TodayView hero (ink ring, streak, live chip, week strip)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 23: `TrendsView`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/TrendsView.swift`

**Interfaces:**
- Consumes: `FocusStore.shared` (`week` for the chart, `history` for the prior-week comparison + calendar), `WeekStrip`, `StreakCalendar`, `TimeFormatting`, `OfflineBanner`, `@AppStorage(ScrybeSettings.goalKey)`.
- Produces: `struct TrendsView: View`. This-week total + delta vs. last week (▲/▼), the 7-bar chart, the streak calendar (last 35 days).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct TrendsView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var thisWeek: Double {
        (focus.week?.days ?? []).reduce(0) { $0 + $1.writingSeconds }
    }
    // history days are oldest -> newest; suffix(14).prefix(7) is the prior week.
    private var lastWeek: Double? {
        guard let days = focus.history?.days, days.count >= 14 else { return nil }
        return days.suffix(14).prefix(7).reduce(0) { $0 + $1.writingSeconds }
    }
    private var calendarDays: [FocusDayDTO] {
        Array((focus.history?.days ?? []).suffix(35))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if focus.isOffline { OfflineBanner() }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Diese Woche").font(.headline).foregroundStyle(theme.ink)
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(TimeFormatting.human(seconds: thisWeek))
                            .font(.system(.largeTitle, design: .serif).weight(.semibold))
                            .foregroundStyle(theme.ink)
                        comparison
                    }
                }

                if let week = focus.week {
                    WeekStrip(days: week.days, maxSeconds: week.maxSeconds)
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("Streak").font(.headline).foregroundStyle(theme.ink)
                    StreakCalendar(days: calendarDays, goalSeconds: goalSeconds)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(theme.paper.ignoresSafeArea())
    }

    @ViewBuilder private var comparison: some View {
        if let last = lastWeek {
            let delta = thisWeek - last
            let up = delta >= 0
            Label(TimeFormatting.human(seconds: abs(delta)),
                  systemImage: up ? "arrowtriangle.up.fill" : "arrowtriangle.down.fill")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(up ? theme.success : theme.danger)
        }
    }
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot; compare to the "Trends" mockup. Claude reviews with the SwiftUI skills. Expected: week sum + delta + bar chart + streak calendar.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/TrendsView.swift"
git commit -m "feat(scrybe): TrendsView (week sum + delta, bar chart, streak calendar)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 24: `HistoryView`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/HistoryView.swift`

**Interfaces:**
- Consumes: `FocusStore.shared.history`, `DailyGoalProgress`, `TimeFormatting`, `OfflineBanner`, `@AppStorage(ScrybeSettings.goalKey)`.
- Produces: `struct HistoryView: View` — a `NavigationStack` listing past days newest-first; each row navigates (by `date` string) to `DayDetailView`. Private `HistoryRow` helper.

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct HistoryView: View {
    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    var body: some View {
        NavigationStack {
            List {
                if focus.isOffline {
                    OfflineBanner().listRowBackground(Color.clear)
                }
                ForEach((focus.history?.days ?? []).reversed()) { day in
                    NavigationLink(value: day.date) {
                        HistoryRow(day: day, goalSeconds: goalSeconds)
                    }
                    .listRowBackground(theme.paperTop)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(theme.paper.ignoresSafeArea())
            .navigationDestination(for: String.self) { date in
                DayDetailView(date: date)
            }
        }
    }
}

private struct HistoryRow: View {
    let day: FocusDayDTO
    let goalSeconds: Double
    @Environment(\.scrybe) private var theme

    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day.writingSeconds, goalSeconds: goalSeconds).isMet
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(day.date).font(.subheadline).foregroundStyle(theme.ink)
                Text(day.weekday).font(.caption).foregroundStyle(theme.sepia)
            }
            Spacer()
            Text(TimeFormatting.human(seconds: day.writingSeconds))
                .font(.body.weight(.medium))
                .foregroundStyle(isMet ? theme.success : theme.ink)
        }
        .padding(.vertical, 4)
    }
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot the list + a tapped detail; compare to the "Verlauf" mockup. Claude reviews with the SwiftUI skills. Expected: chronological list, goal-met days tinted, tap navigates.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/HistoryView.swift"
git commit -m "feat(scrybe): HistoryView chronological day list

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 25: `DayDetailView`

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/DayDetailView.swift`

**Interfaces:**
- Consumes: `FocusStore.shared` (`history` for the day's total, `today.stretches` for today's timeline), `DailyGoalProgress`, `TimeFormatting`, `@AppStorage(ScrybeSettings.goalKey)`.
- Produces: `struct DayDetailView: View` with `let date: String`. Shows the day's total + goal-met badge; **for today**, the full stretch timeline (from `/focus/today`). **First-cut scope note:** past-day per-stretch detail needs a `/focus/day?date=` endpoint not authorized by spec §6 — see the **Optional follow-up** task at the end of Phase 5. Past days show the summary + a one-line note.

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct DayDetailView: View {
    let date: String

    @ObservedObject private var focus = FocusStore.shared
    @AppStorage(ScrybeSettings.goalKey) private var goalSeconds: Double = ScrybeSettings.defaultGoalSeconds
    @Environment(\.scrybe) private var theme

    private var day: FocusDayDTO? { focus.history?.days.first { $0.date == date } }
    private var isToday: Bool { day?.isToday == true }
    private var stretches: [FocusStretchDTO] { isToday ? (focus.today?.stretches ?? []) : [] }
    private var isMet: Bool {
        DailyGoalProgress(writingSeconds: day?.writingSeconds ?? 0, goalSeconds: goalSeconds).isMet
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(TimeFormatting.human(seconds: day?.writingSeconds ?? 0))
                    .font(.system(.largeTitle, design: .serif).weight(.semibold))
                    .foregroundStyle(theme.ink)

                if isMet {
                    Label("Tagesziel erreicht", systemImage: "checkmark.seal")
                        .font(.subheadline).foregroundStyle(theme.success)
                }

                if !stretches.isEmpty {
                    Text("Schreibphasen").font(.headline).foregroundStyle(theme.ink)
                    ForEach(stretches) { s in
                        HStack {
                            Text(clock(s.startMs)).monospacedDigit()
                            Text("–")
                            Text(clock(s.endMs)).monospacedDigit()
                            Spacer()
                            Text(TimeFormatting.human(seconds: s.durationS))
                                .foregroundStyle(theme.sepia)
                        }
                        .font(.callout).foregroundStyle(theme.ink)
                    }
                } else if !isToday {
                    Text("Schreibphasen im Detail sind für den aktuellen Tag verfügbar.")
                        .font(.footnote).foregroundStyle(theme.sepia)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(theme.paper.ignoresSafeArea())
        .navigationTitle(date)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func clock(_ ms: Int) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot today's detail (with stretches) + a past day (summary); Claude reviews with SwiftUI skills. Expected: today shows the phase timeline; past day shows total + note.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/DayDetailView.swift"
git commit -m "feat(scrybe): DayDetailView (today stretch timeline; past-day summary)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 26: `OnboardingView` (empty state)

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/OnboardingView.swift`

**Interfaces:**
- Consumes: `@Environment(\.scrybe)`.
- Produces: `struct OnboardingView: View` (no params). Calm first-run state. Consumed by `TodayView` (Task 22).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct OnboardingView: View {
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "applewatch")
                .font(.system(size: 44))
                .foregroundStyle(theme.accent)
            Text("Trag die Watch und fang an zu schreiben")
                .font(.system(.title3, design: .serif))
                .foregroundStyle(theme.ink)
                .multilineTextAlignment(.center)
            Text("Deine Schreibzeit erscheint hier, sobald die erste Aufnahme läuft.")
                .font(.subheadline)
                .foregroundStyle(theme.sepia)
                .multilineTextAlignment(.center)
        }
        .padding(32)
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    OnboardingView()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(ScrybeTheme.standard.paper)
        .scrybeTheme()
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot; compare to the empty-state mockup. Claude reviews with SwiftUI skills. Expected: calm, centered, on-brand.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/OnboardingView.swift"
git commit -m "feat(scrybe): OnboardingView empty/first-run state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 27 (OPTIONAL, deferred): `GET /focus/day?date=` + past-day stretch timeline

**Decide before starting Phase 6.** This task is **out of the spec's §6 authorized scope** (only `/focus/history` was sanctioned) and is listed so the past-day timeline gap (Task 25) is tracked, not silently dropped. Implement only if you want full past-day stretch detail in the first release.

**Files:**
- Modify: `src/server/routes/focus.py` (add `focus_day`, reusing `_local_day_bounds` for an arbitrary date + `_stretches`)
- Test: `tests/test_focus.py`
- Modify: `watch_streamer/WatchStreamer/Networking/FocusAPI.swift` (add `func day(date: String) async throws -> FocusTodayDTO`)
- Modify: `watch_streamer/WatchStreamer/Scrybe/DayDetailView.swift` (fetch the day's stretches for any date)

**Interfaces:**
- Produces: `GET /focus/day?date=YYYY-MM-DD` returning the `/focus/today` shape for the requested local day.

- [ ] **Step 1 (server, runnable here):** add the endpoint:

```python
@router.get("/focus/day")
async def focus_day(date: str) -> dict:
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    day_start_ms, day_end_ms = _local_day_bounds(d)
    rows = [r for r in _read_log_rows() if day_start_ms <= r["ts_ms"] < day_end_ms]
    stretches = _stretches(rows)
    return {
        "date": date,
        "day_start_ms": day_start_ms,
        "day_end_ms": day_end_ms,
        "now_ms": int(datetime.now().timestamp() * 1000),
        "total_writing_seconds": round(sum(s["duration_s"] for s in stretches), 1),
        "stretches": [
            {"start_ms": s["start_ms"], "end_ms": s["end_ms"], "duration_s": round(s["duration_s"], 1)}
            for s in stretches
        ],
        "tick_count": len(rows),
    }
```

- [ ] **Step 2 (server test, runnable here):**

```python
def test_focus_day_returns_that_days_stretches(client, isolated_log):
    target = (datetime.now() - timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    t0 = int(target.timestamp() * 1000)
    _seed_log(isolated_log, [(t0 + i * 1000, True) for i in range(20)])
    body = client.get(f"/focus/day?date={target.strftime('%Y-%m-%d')}").json()
    assert body["tick_count"] == 20
    assert len(body["stretches"]) == 1
```

Run: `python -m pytest tests/test_focus.py -k day -v` → PASS; `python -m pytest tests/ -q` → green.

- [ ] **Step 3 (iOS):** add `func day(date:)` to `FocusAPI` (mirrors `today()` with `"/focus/day?date=\(date)"` → `FocusTodayDTO`), and in `DayDetailView` replace the `isToday ? today.stretches : []` logic with a `.task(id: date)` that fetches `FocusAPI().day(date: date)` into local `@State var detail: FocusTodayDTO?`, rendering `detail?.stretches`. Build + screenshot a past day with stretches.

- [ ] **Step 4: Commit** (`feat(focus): GET /focus/day + past-day stretch timeline`).

---

# PHASE 6 — Admin (hidden, PIN-gated)

> Admin reuses the existing singletons (`PhoneBridge`, `ServerCommandListener`, `RecordingHealthStore`, `FTLogStore`) — **no new server calls** except the one sanctioned `POST /session/stop` (existing endpoint) for the STOP button. **No AirPods anywhere.** All cards use `ScrybeTheme` tokens + the grid. View tasks end with build + screenshot + skill review.

### Task 28: `AdminGateView` (PIN gate)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/AdminGateView.swift`

**Interfaces:**
- Consumes: `ScrybeSettings.adminPIN` (Task 14), `@Environment(\.scrybe)`.
- Produces: `struct AdminGateView: View` with `var onUnlock: () -> Void`. Paper-look PIN pad (4 digits, ink keypad, lock glyph, "geöffnet durch langes Drücken" hint); calls `onUnlock()` on the correct PIN, shakes + clears on a wrong one. Private `PinKeypad` + `Shake` helpers in the same file. Consumed by `RootPagerView` (Phase 7).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct AdminGateView: View {
    var onUnlock: () -> Void

    @Environment(\.scrybe) private var theme
    @State private var entry = ""
    @State private var error = false
    private let pinLength = 4

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "lock")
                .font(.system(size: 40))
                .foregroundStyle(theme.accent)
            Text("Admin")
                .font(.system(.title2, design: .serif))
                .foregroundStyle(theme.ink)
            Text("Geöffnet durch langes Drücken.")
                .font(.footnote)
                .foregroundStyle(theme.sepia)

            HStack(spacing: 16) {
                ForEach(0..<pinLength, id: \.self) { i in
                    Circle()
                        .fill(i < entry.count ? theme.ink : theme.mutedInk)
                        .frame(width: 14, height: 14)
                }
            }
            .modifier(Shake(animatableData: error ? 1 : 0))

            PinKeypad(onDigit: append, onDelete: { entry = String(entry.dropLast()) })
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.paper.ignoresSafeArea())
    }

    private func append(_ d: String) {
        guard entry.count < pinLength else { return }
        entry += d
        if entry.count == pinLength { verify() }
    }

    private func verify() {
        if entry == ScrybeSettings.adminPIN {
            onUnlock()
        } else {
            withAnimation(.default) { error = true }
            entry = ""
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { error = false }
        }
    }
}

private struct PinKeypad: View {
    var onDigit: (String) -> Void
    var onDelete: () -> Void

    @Environment(\.scrybe) private var theme
    private let rows = [["1","2","3"], ["4","5","6"], ["7","8","9"], ["","0","⌫"]]

    var body: some View {
        VStack(spacing: 16) {
            ForEach(rows, id: \.self) { row in
                HStack(spacing: 24) {
                    ForEach(row, id: \.self) { key in keyButton(key) }
                }
            }
        }
    }

    @ViewBuilder private func keyButton(_ key: String) -> some View {
        if key.isEmpty {
            Color.clear.frame(width: 64, height: 64)
        } else if key == "⌫" {
            Button(action: onDelete) { Image(systemName: "delete.left").font(.title2) }
                .frame(width: 64, height: 64)
                .foregroundStyle(theme.ink)
        } else {
            Button { onDigit(key) } label: {
                Text(key).font(.system(.title, design: .serif))
            }
            .frame(width: 64, height: 64)
            .background(Circle().fill(theme.track))
            .foregroundStyle(theme.ink)
        }
    }
}

private struct Shake: GeometryEffect {
    var animatableData: CGFloat
    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 8 * sin(animatableData * .pi * 4), y: 0))
    }
}

#Preview {
    AdminGateView(onUnlock: {}).scrybeTheme()
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`; screenshot; enter the default PIN `0000` and a wrong PIN; confirm unlock fires + wrong-PIN shake. Claude reviews with `swiftui-pro` + `swiftui-design-principles` + `swiftui-accessibility-auditor` (VoiceOver on the keypad). Expected: paper-look gate, shake on error.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/AdminGateView.swift"
git commit -m "feat(admin): PIN gate (paper keypad, shake on error)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 29: `AdminPanelView` shell + `AdminCard` chrome

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/AdminPanelView.swift`

**Interfaces:**
- Consumes: the section cards (Tasks 30–36), `@Environment(\.scrybe)`.
- Produces: `struct AdminPanelView: View` with `var onExit: () -> Void` (the "‹ Scrybe" back action) and the reusable `struct AdminCard<Content: View>` chrome (title + paper card, 14 pt radius, hairline stroke). Consumed by `RootPagerView` (Phase 7).

- [ ] **Step 1: Implement (cards referenced here are built in Tasks 30–36)**

```swift
import SwiftUI

struct AdminPanelView: View {
    var onExit: () -> Void
    @Environment(\.scrybe) private var theme

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                header
                RecordingHealthCard()
                DataflowCard()
                ConnectionsCard()
                SessionCard()
                RepairCard()
                LogCard()
                SettingsCard()
            }
            .padding(16)
        }
        .background(theme.paper.ignoresSafeArea())
    }

    private var header: some View {
        HStack {
            Button(action: onExit) {
                Label("Scrybe", systemImage: "chevron.left")
                    .font(.subheadline.weight(.medium))
            }
            .foregroundStyle(theme.accent)
            Spacer()
            Text("Admin").font(.headline).foregroundStyle(theme.ink)
            Spacer()
            Color.clear.frame(width: 64, height: 1)   // balances the back button
        }
    }
}

struct AdminCard<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title.uppercased())
                .font(.caption.weight(.semibold))
                .tracking(1.5)
                .foregroundStyle(theme.sepia)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.cardFill))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(theme.hairline))
    }
}
```

- [ ] **Step 2: Build note**

This file references `RecordingHealthCard`…`SettingsCard` which don't exist until Tasks 30–36. **Build verification for Task 29 happens after Task 36.** For now, confirm the file is syntactically complete; the project will not compile until the seven cards exist (expected). Commit anyway — the cards land next.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/AdminPanelView.swift"
git commit -m "feat(admin): AdminPanelView shell + AdminCard chrome

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 30: `RecordingHealthCard`

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/RecordingHealthCard.swift`

**Interfaces:**
- Consumes: `ServerCommandListener.shared` (`currentSessionId`, `watchPolling`, `isConnected`), `RecordingHealthStore.shared.dataFlowing`, `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct RecordingHealthCard: View`. Re-derives the verdict (`Gesund` / `Upload staut sich` / `Fehler`) — **green = `hasSession && dataFlowing && pollFresh`** (the legacy `Health` enum is `private` to a View, so this re-derives from the three public sources). WS shown as a flag but **not** a green condition.

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct RecordingHealthCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var health = RecordingHealthStore.shared
    @Environment(\.scrybe) private var theme

    private var hasSession: Bool { server.currentSessionId != nil }
    private var pollFresh: Bool { server.watchPolling }
    private var dataFlowing: Bool { health.dataFlowing }
    private var wsUp: Bool { server.isConnected }

    private enum Verdict { case idle, healthy, warning, error }
    private var verdict: Verdict {
        guard hasSession else { return .idle }
        if dataFlowing && pollFresh { return .healthy }   // Why: green = data over HTTP + fresh watch poll; WS is command-only
        if !dataFlowing && !pollFresh && !wsUp { return .error }
        return .warning
    }

    var body: some View {
        AdminCard(title: "Recording-Health") {
            HStack(spacing: 8) {
                Circle().fill(color).frame(width: 12, height: 12)
                Text(label).font(.headline).foregroundStyle(theme.ink)
            }
            HStack(spacing: 8) {
                flag("WS", wsUp)
                flag("DATA", dataFlowing)
                flag("WATCH", pollFresh)
            }
        }
    }

    private var label: String {
        switch verdict {
        case .idle: return "Keine Aufnahme"
        case .healthy: return "Gesund"
        case .warning: return "Upload staut sich"
        case .error: return "Fehler"
        }
    }
    private var color: Color {
        switch verdict {
        case .idle: return theme.mutedInk
        case .healthy: return theme.success
        case .warning: return theme.warning
        case .error: return theme.danger
        }
    }
    @ViewBuilder private func flag(_ name: String, _ on: Bool) -> some View {
        Text(name)
            .font(.caption2.weight(.bold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill((on ? theme.success : theme.ink).opacity(0.12)))
            .foregroundStyle(on ? theme.success : theme.sepia)
    }
}
```

- [ ] **Step 2 / 3: Build (deferred to Task 36) + Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/RecordingHealthCard.swift"
git commit -m "feat(admin): RecordingHealthCard (green = dataFlowing && pollFresh)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 31: `DataflowCard` (+ `Sparkline`)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/DataflowCard.swift`

**Interfaces:**
- Consumes: `PhoneBridge.shared` (`queuedBatchCount`, `uploadedSampleCount`, `droppedBatchCount`), `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct DataflowCard: View` (In Queue / Hochgeladen / Verworfen + 60-point backlog sparkline; queue > 0 → warning tone, dropped > 0 → danger + ⚠ "Daten verloren") and `struct Sparkline: View`. The 1 Hz backlog timer lives **only** in this Admin-only card (spec §7 re-render discipline).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct DataflowCard: View {
    @ObservedObject private var bridge = PhoneBridge.shared
    @Environment(\.scrybe) private var theme
    @State private var backlog: [Int] = []

    private var tone: Color {
        if bridge.droppedBatchCount > 0 { return theme.danger }
        if bridge.queuedBatchCount > 0 { return theme.warning }
        return theme.success
    }

    var body: some View {
        AdminCard(title: "Datenfluss") {
            HStack {
                stat("In Queue", bridge.queuedBatchCount, tone)
                Spacer()
                stat("Hochgeladen", bridge.uploadedSampleCount, theme.ink)
                Spacer()
                stat("Verworfen", bridge.droppedBatchCount, bridge.droppedBatchCount > 0 ? theme.danger : theme.ink)
            }
            if bridge.droppedBatchCount > 0 {
                Label("Daten verloren", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(theme.danger)
            }
            Sparkline(values: backlog, color: tone).frame(height: 28)
        }
        .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { _ in
            backlog.append(bridge.queuedBatchCount)
            if backlog.count > 60 { backlog.removeFirst(backlog.count - 60) }
        }
    }

    @ViewBuilder private func stat(_ title: String, _ value: Int, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(value)")
                .font(.title3.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(color)
            Text(title).font(.caption2).foregroundStyle(theme.sepia)
        }
    }
}

struct Sparkline: View {
    let values: [Int]
    let color: Color

    var body: some View {
        GeometryReader { geo in
            let maxV = max(values.max() ?? 1, 1)
            Path { p in
                guard values.count > 1 else { return }
                let stepX = geo.size.width / CGFloat(values.count - 1)
                for (i, v) in values.enumerated() {
                    let x = CGFloat(i) * stepX
                    let y = geo.size.height * (1 - CGFloat(v) / CGFloat(maxV))
                    if i == 0 { p.move(to: CGPoint(x: x, y: y)) }
                    else { p.addLine(to: CGPoint(x: x, y: y)) }
                }
            }
            .stroke(color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        }
        .accessibilityHidden(true)
    }
}
```

- [ ] **Step 2 / 3: Build (deferred to Task 36) + Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/DataflowCard.swift"
git commit -m "feat(admin): DataflowCard (queue/uploaded/dropped + backlog sparkline)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 32: `ConnectionsCard` (no AirPods)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/ConnectionsCard.swift`

**Interfaces:**
- Consumes: `ServerCommandListener.shared` (`isConnected`, `watchRunning`), `PhoneBridge.shared` (`isConnected`), `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct ConnectionsCard: View` — three status rows (Server · iPhone-Bridge · Watch). **No AirPods row.**

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct ConnectionsCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @ObservedObject private var bridge = PhoneBridge.shared
    @Environment(\.scrybe) private var theme

    var body: some View {
        AdminCard(title: "Verbindungen") {
            row("Server", server.isConnected, server.isConnected ? "verbunden" : "getrennt")
            row("iPhone-Bridge", bridge.isConnected, bridge.isConnected ? "aktiv" : "inaktiv")
            row("Watch", server.watchRunning, server.watchRunning ? "läuft" : "bereit")
        }
    }

    @ViewBuilder private func row(_ name: String, _ ok: Bool, _ detail: String) -> some View {
        HStack(spacing: 8) {
            Circle().fill(ok ? theme.success : theme.mutedInk).frame(width: 10, height: 10)
            Text(name).foregroundStyle(theme.ink)
            Spacer()
            Text(detail).font(.caption).foregroundStyle(theme.sepia)
        }
        .accessibilityElement(children: .combine)
    }
}
```

- [ ] **Step 2 / 3: Build (deferred to Task 36) + Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/ConnectionsCard.swift"
git commit -m "feat(admin): ConnectionsCard (Server/Bridge/Watch, no AirPods)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 33: `SessionCard` (status + STOP)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/SessionCard.swift`

**Interfaces:**
- Consumes: `ServerCommandListener.shared` (`currentSessionId`, `currentPersonId`), `PhoneBridge.serverBaseURL`, `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct SessionCard: View`. Running session (ID · Person · elapsed mm:ss) + **STOP** button (ink-red) that `POST`s the existing `/session/stop` (parameterless; the server then broadcasts `stop` over WS → `currentSessionId` clears → card updates reactively). Idle state shows a "Session im Dashboard starten" hint (START stays on the dashboard, per the chosen scope). Elapsed counter mirrors the legacy `SessionTab` (per-second counter, reset on session-id change).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct SessionCard: View {
    @ObservedObject private var server = ServerCommandListener.shared
    @Environment(\.scrybe) private var theme
    @State private var elapsed = 0
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var hasSession: Bool { server.currentSessionId != nil }

    var body: some View {
        AdminCard(title: "Session") {
            if hasSession, let sid = server.currentSessionId {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(sid).font(.headline).foregroundStyle(theme.ink)
                        Text(server.currentPersonId ?? "Anonymous")
                            .font(.caption).foregroundStyle(theme.sepia)
                    }
                    Spacer()
                    Text(String(format: "%02d:%02d", elapsed / 60, elapsed % 60))
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                        .foregroundStyle(theme.ink)
                }
                Button(role: .destructive, action: stopSession) {
                    Text("STOP")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(RoundedRectangle(cornerRadius: 12).fill(theme.danger))
                        .foregroundStyle(.white)
                }
            } else {
                Text("Keine aktive Session")
                    .font(.subheadline).foregroundStyle(theme.ink)
                Text("Session im Dashboard starten.")
                    .font(.caption).foregroundStyle(theme.sepia)
            }
        }
        .onReceive(timer) { _ in if hasSession { elapsed += 1 } }
        .onChange(of: server.currentSessionId) { sid in if sid == nil { elapsed = 0 } }
    }

    private func stopSession() {
        guard let url = URL(string: PhoneBridge.serverBaseURL + "/session/stop") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 6
        // The server broadcasts {type:"stop"} over WS → ServerCommandListener
        // clears currentSessionId, so the card updates reactively.
        Task { _ = try? await URLSession.shared.data(for: req) }
    }
}
```

- [ ] **Step 2 / 3: Build (deferred to Task 36) + Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/SessionCard.swift"
git commit -m "feat(admin): SessionCard (status + STOP via existing /session/stop)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 34: `RepairCard` (drain / clear watch spill)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/RepairCard.swift`

**Interfaces:**
- Consumes: `ServerCommandListener.shared.drainWatchSpill()` / `clearWatchSpill()` (existing), `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct RepairCard: View` — "Gepufferte Daten senden" (drain) + "Puffer verwerfen" (clear, destructive → confirmation dialog).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct RepairCard: View {
    @Environment(\.scrybe) private var theme
    @State private var confirmClear = false

    var body: some View {
        AdminCard(title: "Reparatur") {
            Button { ServerCommandListener.shared.drainWatchSpill() } label: {
                Label("Gepufferte Daten senden", systemImage: "tray.and.arrow.up")
                    .font(.subheadline)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            }
            .foregroundStyle(theme.accent)

            Button(role: .destructive) { confirmClear = true } label: {
                Label("Puffer verwerfen", systemImage: "trash")
                    .font(.subheadline)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            }
            .foregroundStyle(theme.danger)
            .confirmationDialog("Puffer verwerfen?", isPresented: $confirmClear, titleVisibility: .visible) {
                Button("Verwerfen", role: .destructive) { ServerCommandListener.shared.clearWatchSpill() }
                Button("Abbrechen", role: .cancel) {}
            } message: {
                Text("Gepufferte, noch nicht gesendete Watch-Daten werden gelöscht.")
            }
        }
    }
}
```

- [ ] **Step 2 / 3: Build (deferred to Task 36) + Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/RepairCard.swift"
git commit -m "feat(admin): RepairCard (drain/clear watch spill)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 35: `LogCard` (event log)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/LogCard.swift`

**Interfaces:**
- Consumes: `FTLogStore.shared` (extracted to `Stores/EventLogStore.swift` in Task 5) — `@Published private(set) var entries: [FTLogEntry]`; `FTLogEntry` fields `timeString: String`, `tag: String`, `tagColor: Color`, `message: String`. `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct LogCard: View` — renders the last 8 entries (time · colored tag pill · message). Populated by `OperationsLogger` (Phase 7).

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct LogCard: View {
    @ObservedObject private var store = FTLogStore.shared
    @Environment(\.scrybe) private var theme
    private let maxEntries = 8

    var body: some View {
        AdminCard(title: "Protokoll") {
            if store.entries.isEmpty {
                Text("Noch keine Ereignisse.")
                    .font(.caption).foregroundStyle(theme.sepia)
            } else {
                ForEach(store.entries.prefix(maxEntries)) { entry in
                    HStack(alignment: .top, spacing: 8) {
                        Text(entry.timeString)
                            .font(.caption2).monospacedDigit()
                            .foregroundStyle(theme.sepia)
                            .frame(width: 56, alignment: .leading)
                        Text(entry.tag)
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 4)
                            .background(entry.tagColor.opacity(0.12))
                            .foregroundStyle(entry.tagColor)
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                        Text(entry.message)
                            .font(.caption2).foregroundStyle(theme.ink)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 2 / 3: Build (deferred to Task 36) + Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/LogCard.swift"
git commit -m "feat(admin): LogCard (event log via FTLogStore)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 36: `SettingsCard` (server IP, motion config, admin PIN)

**Files:**
- Create: `watch_streamer/WatchStreamer/Admin/Sections/SettingsCard.swift`

**Interfaces:**
- Consumes: `@AppStorage("serverIP")` (default `ServerConfig.defaultIP`), `@AppStorage("requestedHz")` (default `50.0`), `@AppStorage("batchSize")` (default `10`), `@AppStorage(ScrybeSettings.pinKey)`, `PhoneBridge.shared.syncServerIP(_:)`, `AdminCard`, `@Environment(\.scrybe)`.
- Produces: `struct SettingsCard: View` — server-IP field (commits via `syncServerIP`), motion config (Hz + batch), and the admin-PIN field. **This is the last Admin task — it makes `AdminPanelView` (Task 29) compile, so the whole Admin surface builds here.**

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct SettingsCard: View {
    @AppStorage("serverIP") private var serverIP = ServerConfig.defaultIP
    @AppStorage("requestedHz") private var requestedHz = 50.0
    @AppStorage("batchSize") private var batchSize = 10
    @AppStorage(ScrybeSettings.pinKey) private var adminPIN = ScrybeSettings.defaultPIN
    @Environment(\.scrybe) private var theme

    var body: some View {
        AdminCard(title: "Einstellungen") {
            field("Server-IP", text: $serverIP) {
                PhoneBridge.shared.syncServerIP(serverIP)
            }
            HStack {
                Text("Rate").foregroundStyle(theme.ink)
                Spacer()
                Picker("", selection: $requestedHz) {
                    Text("50 Hz").tag(50.0)
                    Text("100 Hz").tag(100.0)
                }.pickerStyle(.segmented).frame(width: 160)
            }
            Stepper("Batch \(batchSize)", value: $batchSize, in: 1...50)
                .foregroundStyle(theme.ink)
            field("Admin-PIN", text: $adminPIN) {}
        }
    }

    @ViewBuilder private func field(_ label: String, text: Binding<String>, onCommit: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(theme.sepia)
            TextField(label, text: text, onCommit: onCommit)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
        }
    }
}
```

- [ ] **Step 2: Build the whole Admin surface + screenshot + skill review (you + Claude)**

Run (you): `⌘B` — **the project now compiles** (all seven cards exist, so `AdminPanelView` resolves). Screenshot each card; compare to the Admin mockups. Claude reviews `AdminGateView` + all section cards with `swiftui-pro` + `swiftui-design-principles` + `swiftui-accessibility-auditor` + `swiftui-performance-audit` (watch the `DataflowCard` 1 Hz timer for the perf auditor). Expected: full Admin panel renders; STOP, drain/clear, settings commit all work against a live server.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Admin/Sections/SettingsCard.swift"
git commit -m "feat(admin): SettingsCard (server IP, motion config, admin PIN)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# PHASE 7 — Migration (parallel → switch root → delete legacy)

> The app stays runnable throughout. Task 37 adds the event-log population; Task 38 builds the pager; Task 39 switches the `@main` root to Scrybe (app now shows Scrybe, legacy view dead but present); Task 40 deletes the legacy view + AirPods. Each step is a `⌘B` + smoke gate on your side.

### Task 37: `OperationsLogger` (event-log population)

**Files:**
- Create: `watch_streamer/WatchStreamer/Stores/OperationsLogger.swift`

**Interfaces:**
- Consumes: `ServerCommandListener.shared` (`$isConnected`, `$currentSessionId`, `$watchPolling`), `PhoneBridge.shared` (`$droppedBatchCount`), `FTLogStore.shared.add(_:_:color:)`, `ScrybeTheme.standard`.
- Produces: `@MainActor final class OperationsLogger` singleton that subscribes (Combine) to the managers and appends a log entry on each **transition** (`removeDuplicates().dropFirst()` → no startup spam, matches spec §5.4.6 "nur bei Zustandswechsel"). Replaces the legacy `iPhoneView` `.onReceive` logging so the Admin `LogCard` stays populated after the legacy view is deleted. Instantiated in `ScrybeApp.init` (Task 39).

- [ ] **Step 1: Implement**

```swift
import Combine
import SwiftUI

@MainActor
final class OperationsLogger {
    static let shared = OperationsLogger()
    private var bag = Set<AnyCancellable>()
    private let log = FTLogStore.shared
    private let palette = ScrybeTheme.standard

    private init() {
        let server = ServerCommandListener.shared
        let bridge = PhoneBridge.shared

        server.$isConnected.removeDuplicates().dropFirst().sink { [palette, log] up in
            log.add("WS", up ? "Server verbunden" : "Server getrennt",
                    color: up ? palette.success : palette.danger)
        }.store(in: &bag)

        server.$currentSessionId.removeDuplicates().dropFirst().sink { [palette, log] sid in
            if let sid { log.add("SESSION", "Start \(sid)", color: palette.accent) }
            else { log.add("SESSION", "Stop", color: palette.sepia) }
        }.store(in: &bag)

        server.$watchPolling.removeDuplicates().dropFirst().sink { [palette, log] fresh in
            log.add("WATCH", fresh ? "Watch-Poll frisch" : "Watch-Poll veraltet",
                    color: fresh ? palette.success : palette.warning)
        }.store(in: &bag)

        bridge.$droppedBatchCount.removeDuplicates().dropFirst().sink { [palette, log] n in
            if n > 0 { log.add("DATA", "Verworfen: \(n) Batches", color: palette.danger) }
        }.store(in: &bag)
    }
}
```

- [ ] **Step 2: Verify build (you)**

Run (you): `⌘B`. Expected: builds. (Wiring into launch happens in Task 39; for a quick check you can temporarily add `_ = OperationsLogger.shared` to any `onAppear` and watch the `LogCard` fill on connect/disconnect.)

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Stores/OperationsLogger.swift"
git commit -m "feat(scrybe): OperationsLogger — populate event log from manager transitions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 38: `RootPagerView` (pager + header + Admin cover)

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift`

**Interfaces:**
- Consumes: `TodayView`, `TrendsView`, `HistoryView`, `AdminGateView`, `AdminPanelView`, `FocusStore.shared`, `@Environment(\.scrybe)`.
- Produces: `struct RootPagerView: View` — the persistent header (`ScrybeHeader`: wordmark + hairline + page label, **2 s long-press → Admin**), the `TabView(.page)` over Today/Trends/History, and the `fullScreenCover` that shows `AdminGateView` until unlocked then `AdminPanelView`. Starts/stops `FocusStore` polling on appear/disappear. Private `ScrybeHeader`.

- [ ] **Step 1: Implement**

```swift
import SwiftUI

struct RootPagerView: View {
    @State private var selection = 0
    @State private var adminPresented = false
    @State private var adminUnlocked = false
    @Environment(\.scrybe) private var theme

    private let labels = ["Heute", "Trends", "Verlauf"]

    var body: some View {
        VStack(spacing: 12) {
            ScrybeHeader(label: labels[selection]) { adminPresented = true }
            TabView(selection: $selection) {
                TodayView().tag(0)
                TrendsView().tag(1)
                HistoryView().tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .interactive))
        }
        .background(theme.paper.ignoresSafeArea())
        .fullScreenCover(isPresented: $adminPresented, onDismiss: { adminUnlocked = false }) {
            if adminUnlocked {
                AdminPanelView(onExit: { adminPresented = false }).scrybeTheme()
            } else {
                AdminGateView(onUnlock: { adminUnlocked = true }).scrybeTheme()
            }
        }
        .onAppear { FocusStore.shared.start() }
        .onDisappear { FocusStore.shared.stop() }
    }
}

private struct ScrybeHeader: View {
    let label: String
    var onAdmin: () -> Void
    @Environment(\.scrybe) private var theme

    var body: some View {
        VStack(spacing: 4) {
            Text("Scrybe")
                .font(.system(.title, design: .serif).weight(.semibold))
                .foregroundStyle(theme.ink)
                .onLongPressGesture(minimumDuration: 2.0) { onAdmin() }
            Rectangle().fill(theme.hairline).frame(width: 40, height: 1)
            Text(label.uppercased())
                .font(.caption.weight(.medium))
                .tracking(1.5)
                .foregroundStyle(theme.sepia)
        }
        .padding(.top, 8)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
        .accessibilityHint("Lang drücken öffnet den Admin-Bereich")
    }
}
```

- [ ] **Step 2: Build + screenshot + skill review (you + Claude)**

Run (you): `⌘B`. Because `WatchStreamerApp` still shows `iPhoneView()`, temporarily preview `RootPagerView()` (add `#Preview { RootPagerView().scrybeTheme() }` at the file end, or point a scheme at it). Screenshot the pager + the long-press→gate flow. Claude reviews with the SwiftUI skills (check `swift-focusengine-pro`/accessibility for the page-dots + long-press discoverability). Expected: three-page pager, header label tracks the page, long-press opens the PIN gate, correct PIN reveals the panel.

- [ ] **Step 3: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift"
git commit -m "feat(scrybe): RootPagerView (Today/Trends/History pager + long-press Admin gate)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 39: `ScrybeApp` — switch the `@main` root

**Files:**
- Create: `watch_streamer/WatchStreamer/Scrybe/ScrybeApp.swift`
- Delete: `watch_streamer/WatchStreamer/WatchStreamerApp.swift` (its `@main` is replaced — exactly one `@main` per target)

**Interfaces:**
- Produces: the new `@main struct ScrybeApp: App` showing `RootPagerView()`, preserving the eager singleton activation and adding `OperationsLogger`. After this task the app **boots into Scrybe**; `iPhoneView_v4.swift` + `AirPodsMotionManager.swift` remain on disk (dead, deleted in Task 40), so the build still succeeds.

- [ ] **Step 1: Create `ScrybeApp.swift`**

```swift
import SwiftUI

@main
struct ScrybeApp: App {
    init() {
        // Eagerly activate WCSession + WS before any view (preserved from WatchStreamerApp).
        _ = PhoneBridge.shared
        _ = ServerCommandListener.shared
        _ = OperationsLogger.shared
    }

    var body: some Scene {
        WindowGroup {
            RootPagerView().scrybeTheme()
        }
    }
}
```

- [ ] **Step 2: Delete the legacy `@main`**

Delete `watch_streamer/WatchStreamer/WatchStreamerApp.swift` (the iPhone one — **not** the Watch target's `WatchStreamer Watch App/WatchStreamerApp.swift`). With filesystem-synchronized groups, removing it from disk removes it from the build; no `project.pbxproj` edit.

```bash
git rm "watch_streamer/WatchStreamer/WatchStreamerApp.swift"
```

- [ ] **Step 3: Build + boot smoke (you)**

Run (you): `⌘B`, run on simulator/device against a live server. Expected: the app boots into the Scrybe pager (not the old tab UI); Today populates; long-press opens Admin; STOP/drain/clear work. `iPhoneView_v4.swift` is now unreferenced.

- [ ] **Step 4: Commit**

```bash
git add "watch_streamer/WatchStreamer/Scrybe/ScrybeApp.swift"
git commit -m "feat(scrybe): switch @main root to ScrybeApp/RootPagerView

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 40: Delete legacy view + AirPods; final verification

**Files:**
- Delete: `watch_streamer/WatchStreamer/iPhoneView_v4.swift`
- Delete: `watch_streamer/WatchStreamer/AirPodsMotionManager.swift`
- Modify: `watch_streamer/WatchStreamer/ServerCommandListener.swift` (remove the AirPods calls + `airpods_start`/`airpods_stop` WS branches)

**Interfaces:**
- Produces: a clean Scrybe-only iPhone target with **no AirPods anywhere**. `ServerCommandListener` no longer references `AirPodsMotionManager`.

- [ ] **Step 1: Strip AirPods from `ServerCommandListener`**

In `ServerCommandListener.swift`'s `handle(...)` (the WS message switch), delete:
- the `AirPodsMotionManager.shared.start()` line inside the `type == "start"` branch,
- the `AirPodsMotionManager.shared.stop()` line inside the `type == "stop"` branch,
- the entire `else if type == "airpods_start" { … }` and `else if type == "airpods_stop" { … }` branches.

Then confirm no AirPods references remain in the iPhone target:

```bash
grep -rn "AirPods" "watch_streamer/WatchStreamer/" --include=*.swift
```
Expected after edits: only `AirPodsMotionManager.swift` itself matches (deleted next). If any other file matches, remove that reference too.

- [ ] **Step 2: Delete the legacy files**

```bash
git rm "watch_streamer/WatchStreamer/iPhoneView_v4.swift" "watch_streamer/WatchStreamer/AirPodsMotionManager.swift"
```

- [ ] **Step 3: Full build + test + smoke (you)**

Run (you):
- `⌘B` — the iPhone target builds with no references to the deleted symbols.
- `⌘U` — the whole `ScrybeTests` suite passes (TimeFormatting, DailyGoalProgress, StreakCalculator, DataFlowEvaluator, Focus DTO, LiveInference).
- `python -m pytest tests/ -q` — server suite still green (the `/focus/history` change from Task 1).
- Run the app end-to-end against a live server: Today ring advances live, Trends + History populate, long-press → PIN `0000` → Admin; STOP / drain / clear / settings all work; no AirPods anywhere.

- [ ] **Step 4: Final review + commit**

Claude runs a final pass with `swiftui-pro` + `swiftui-design-principles` + `swiftui-accessibility-auditor` + `swiftui-performance-audit` across the new `Scrybe/` + `Admin/` trees, and `swift-concurrency-expert` over `Stores/` + `Networking/`. Address findings, then:

```bash
git add -A
git commit -m "refactor(ios): delete legacy iPhoneView + AirPods — Scrybe is the app

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Plan self-review (spec → task coverage)

Checked against the spec with fresh eyes:

- **§5.1 Heute** → header T38 (wordmark + hairline + label), InkRing T17 + TodayView T22 (time, goal %, ziel), streak + LiveChip T22, WeekStrip T18. ✓
- **§5.2 Trends** → TrendsView T23 (week sum + prior-week delta), WeekStrip bar chart, StreakCalendar T19. ✓
- **§5.3 Verlauf** → HistoryView T24 + DayDetailView T25; >7-day data via `/focus/history` T1 + FocusStore T15. **Known first-cut limitation:** past-day *stretch* timeline needs `/focus/day` (deferred optional **T27**) — today shows the full timeline, past days a summary. ✓ (documented)
- **§5.4 Admin** → gate T28, panel T29, health T30, dataflow T31, connections T32, session T33 (STOP only, per chosen scope), repair T34, log T35, settings T36. ✓
- **§6 Datenquellen** → today/week/history T15+T1, live WS T13, goal AppStorage T14, Admin via existing managers Phase 6 (only new call: existing `/session/stop`). ✓
- **§7 Architektur** → File Structure section; stores `@MainActor`; re-render discipline (1 Hz timer only in the Admin-only `DataflowCard`). ✓
- **§8 leer/offline/Fehler** → OnboardingView T26 (empty), OfflineBanner T21 + FocusStore last-good values T15 (offline, no hang), `rate_mismatch`→`writing=false` server-side → LiveChip inactive T20/T22. **Note:** offline cache is in-memory (survives backgrounding, not a cold restart) — the SwiftData persistent cache is explicitly deferred by the spec. ✓
- **§9 Tests** → streak T9, goal % T8, data-flowing + baseline-skip T10, time format T7; **week-aggregation is tested server-side** in T1 (`_day_buckets`) because the iOS side only renders the pre-aggregated DTO. Test target T6. ✓
- **§10 Verifikation** → Verification Model section (3 modalities). ✓
- **§11 Entschieden** → history endpoint T1, streak = goal-met days T9, parallel→switch migration Phase 7, live chip at `writing==true` T20. ✓

**Type-consistency pass:** `FocusStore` members (`today/week/history/isOffline/streak/goalProgress/todayWritingSecondsPolled`), `ServerCommandListener.liveInference`, component signatures (`InkRing(fraction:centerText:subtitle:)`, `WeekStrip(days:maxSeconds:)`, `StreakCalendar(days:goalSeconds:)`, `LiveChip(isWriting:)`, `AdminCard(title:){}`), pure-logic APIs (`TimeFormatting.clock/.human`, `DailyGoalProgress(writingSeconds:goalSeconds:)`, `StreakCalculator.currentStreak(days:goalSeconds:todayISO:)`, `DataFlowEvaluator.update(count:now:)`), and `FTLogStore.add(_:_:color:)` are used consistently across producers and consumers. No dangling names found.

**Open decisions captured (not blocking):**
1. Admin PIN default `0000`, changeable in Admin → Settings (T36).
2. History/streak fetch `days = 90` (T15).
3. Past-day stretch timeline deferred to optional T27.
4. Offline cache in-memory; SwiftData persistent cache deferred (spec §6/§11).

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-06-22-scrybe-iphone-redesign.md`. 40 tasks across 8 phases (1 server + iOS foundation/logic/networking/components/screens/admin/migration).

Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, with review between tasks. Fast iteration; each Swift task pauses for your `⌘B`/`⌘U`/screenshot before the next. Best fit here because the SwiftUI tasks need your on-device verification anyway.
2. **Inline Execution** — execute tasks in this session with batch checkpoints (executing-plans).

**Caveat unique to this plan:** only Phase 0 (the Python endpoint) is verifiable in this environment. Every Swift task's "run" step is **yours** (Xcode build/test/screenshot); I write the code and review it with the Swift skills, you confirm it builds and looks right before we advance.

Which approach?




