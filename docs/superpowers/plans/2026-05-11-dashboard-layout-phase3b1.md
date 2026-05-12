# Dashboard Layout Phase 3b-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Recording page into a focused live-recording surface (session strip + chart/handwriting + health row + collapsed log), bump chart aggregation from 1 Hz to 5 Hz for visible motion dynamics, add a notebook look to the handwriting canvas, and add an AirPods 4th status dot + hover detail card to the topbar.

**Architecture:** Server gains a parallel asyncio task at 5 Hz that drains the existing per-sample accumulators into the chart buffer (broadcast stays 1 Hz). Frontend Recording page rewritten to a 4-section vertical layout; device-cards removed. Topbar status-cluster gains a 4th dot for AirPods and a `.brand-tooltip`-style hover card.

**Tech Stack:** Python (FastAPI + asyncio), Chart.js, vanilla CSS with OKLCH tokens, native ES modules.

**Spec:** `docs/superpowers/specs/2026-05-11-dashboard-layout-phase3b1-design.md`

---

## Conventions

- All paths relative to project root `/Users/noahsamel/PycharmProjects/ML4SCS_Burk_macht_Bock`.
- Base commit: `b54e54a` on `feature/adapt-web-ui`. New branch: `feature/dashboard-layout-phase3b1`.
- Commit messages use `layout(ui):` prefix for frontend, `layout(server):` for backend.
- `pytest tests/` = 70 passing at every commit (becomes 71 after Task 1 adds the new aggregator test).
- Both light + dark themes must render correctly at every commit.
- **No JS changes outside `static/js/pages/recording.js` and `static/js/core/status_cluster.js`.**
- **DOM-safety**: every new code path uses `document.createElement` / `textContent` / `replaceChildren`. No new `innerHTML = string` assignments. Existing innerHTML in rows-present log-panel branches stays out of scope.

---

## Task 1: Server — 5 Hz chart aggregator

**Files:**
- Modify: `src/server/state.py` (raise chart-buffer trim ceiling).
- Modify: `src/server/broadcast.py` (move chart aggregation out of `_status_loop` into a new 5 Hz task).
- Modify: `server.py` (start the new task in `lifespan`).
- Create: `tests/test_chart_aggregation.py` (synthetic test for the new aggregator).

### Step 1: Create the branch

```bash
git checkout -b feature/dashboard-layout-phase3b1
```

Expected: `Switched to a new branch 'feature/dashboard-layout-phase3b1'`.

### Step 2: Write the failing aggregator test

Create `tests/test_chart_aggregation.py`:

```python
"""Smoke test for the 5 Hz chart aggregator.

Feeds synthetic per-axis magnitudes into state, runs the aggregator once,
asserts the resulting chart buffer entry has the right mean and the
sample windows are cleared.
"""
import pytest

from src.server import broadcast
from src.server.state import SessionState


def test_chart_aggregator_means_and_clears():
    state = SessionState()
    state.active = True
    state.chart_window_acc_mags = [0.5, 1.0, 1.5]   # mean = 1.0
    state.chart_window_gyro_mags = [0.2, 0.4]       # mean = 0.3

    broadcast._chart_aggregator_tick(state, pen_writing=False)

    assert len(state.chart_buffer) == 1
    entry = state.chart_buffer[0]
    assert entry["acc_mag"] == 1.0
    assert entry["gyro_mag"] == 0.3
    assert entry["mag"] == 1.0           # backward-compat key
    assert entry["pen_writing"] is False
    # Windows cleared so the next 200 ms bucket is isolated.
    assert state.chart_window_acc_mags == []
    assert state.chart_window_gyro_mags == []


def test_chart_aggregator_skips_when_inactive():
    state = SessionState()
    state.active = False
    state.chart_window_acc_mags = [1.0]
    state.chart_window_gyro_mags = [1.0]

    broadcast._chart_aggregator_tick(state, pen_writing=False)

    assert state.chart_buffer == []
    # Windows still cleared so they don't grow unbounded between sessions.
    assert state.chart_window_acc_mags == []
    assert state.chart_window_gyro_mags == []


def test_chart_aggregator_trims_to_100():
    state = SessionState()
    state.active = True
    # Pre-fill 100 dummy entries so the next append should evict the oldest.
    state.chart_buffer = [{"t": i} for i in range(100)]
    state.chart_window_acc_mags = [2.0]
    state.chart_window_gyro_mags = [3.0]

    broadcast._chart_aggregator_tick(state, pen_writing=True)

    assert len(state.chart_buffer) == 100
    assert state.chart_buffer[-1]["acc_mag"] == 2.0
    assert state.chart_buffer[-1]["pen_writing"] is True
    # Oldest entry was evicted.
    assert state.chart_buffer[0]["t"] == 1
```

Run: `pytest tests/test_chart_aggregation.py -v`
Expected: 3 FAILs (`_chart_aggregator_tick` doesn't exist yet).

### Step 3: Raise chart buffer trim ceiling in `state.py`

In `src/server/state.py`, the buffer is initialised at line 41 and reset at line 95. No constant exists today (the trim happens in `broadcast.py` with a hardcoded `60`). Leave `state.py` as-is for now — the new constant lives in `broadcast.py` where the trim happens.

(Step left intentionally as a verification: no edit to state.py needed.)

### Step 4: Add `_chart_aggregator_tick` + `_chart_aggregator_loop` to `broadcast.py`

In `src/server/broadcast.py`, find the existing chart-aggregation block inside `_status_loop` (around lines 96–116, starts with `# Chart-Puffer: ein aggregierter Punkt pro Sekunde ...`).

Replace that block (lines from `if state.active:` through `state.chart_window_gyro_mags = []`) with a single helper call:

```python
        _chart_aggregator_tick(state, pen_writing)
```

Wait — actually the 1 Hz status loop should NO LONGER drive chart aggregation; the 5 Hz loop does. Remove the entire block from `_status_loop` (the inline aggregation lines).

Then, just above `_status_loop`'s definition (after the existing module-level imports and `_broadcast`), add:

```python
CHART_BUFFER_MAX = 100
CHART_AGGREGATOR_INTERVAL_S = 0.2  # 5 Hz aggregation


def _chart_aggregator_tick(state, pen_writing: bool) -> None:
    """Drain the per-sample magnitude windows into one chart buffer entry.

    Called every 200 ms. Computes means, appends a chart point with the
    timestamp + magnitudes + pen_writing flag, trims the buffer to the
    last CHART_BUFFER_MAX entries. Clears the windows so the next 200 ms
    bucket is isolated. Skips appending when state.active is False but
    still clears the windows to keep memory bounded.
    """
    acc_mags = state.chart_window_acc_mags
    gyro_mags = state.chart_window_gyro_mags
    state.chart_window_acc_mags = []
    state.chart_window_gyro_mags = []

    if not state.active:
        return

    acc_mag = sum(acc_mags) / len(acc_mags) if acc_mags else 0.0
    gyro_mag = sum(gyro_mags) / len(gyro_mags) if gyro_mags else 0.0

    state.chart_buffer.append({
        "t": int(time.time() * 1000),
        "mag": round(acc_mag, 3),       # backward-compat key
        "acc_mag": round(acc_mag, 3),
        "gyro_mag": round(gyro_mag, 3),
        "pen_writing": pen_writing,
    })
    if len(state.chart_buffer) > CHART_BUFFER_MAX:
        state.chart_buffer = state.chart_buffer[-CHART_BUFFER_MAX:]


async def _chart_aggregator_loop():
    """Run _chart_aggregator_tick at 5 Hz (every 200 ms).

    Reads the most recent pen-dot once per tick to determine pen_writing
    for that bucket. Separate from the 1 Hz _status_loop so the chart
    updates faster than the rest of the status payload.
    """
    while True:
        try:
            last_pen_dot = _pen_recent_dots(1)
            last_pen_dot = last_pen_dot[0] if last_pen_dot else None
            pen_writing = (
                last_pen_dot.get("dot_type") in ("PEN_DOWN", "PEN_MOVE")
                if last_pen_dot else False
            )
            _chart_aggregator_tick(state, pen_writing)
        except Exception as e:  # noqa: BLE001 — best-effort, never let the loop die
            log.exception("chart aggregator tick failed: %s", e)
        await asyncio.sleep(CHART_AGGREGATOR_INTERVAL_S)
```

You'll also need to add the imports at the top of `broadcast.py` if they're not already present: `import asyncio`, `import time`, `import logging`, and access to `_pen_recent_dots` (search the file to see how `_status_loop` accesses it — match the existing import pattern). `log = logging.getLogger(__name__)` if a module logger isn't already present.

### Step 5: Run the test to verify it passes

```bash
pytest tests/test_chart_aggregation.py -v
```
Expected: 3 PASSED.

### Step 6: Start the new task in `lifespan`

In `server.py`, find the `lifespan` async context manager. Today it does:

```python
task = asyncio.create_task(_status_loop())
```

Update to start both tasks:

```python
status_task = asyncio.create_task(_status_loop())
chart_task = asyncio.create_task(_chart_aggregator_loop())
```

And update the cleanup at the bottom of `lifespan` (after `yield`):

```python
status_task.cancel()
chart_task.cancel()
```

Import `_chart_aggregator_loop` at the top of `server.py` alongside `_status_loop`:

```python
from src.server.broadcast import _status_loop, _chart_aggregator_loop
```

(Read the existing import to confirm its form; match exactly.)

### Step 7: Run full test suite

```bash
pytest tests/ -q
```
Expected: 71 passed (70 prior + 3 new aggregator tests minus 2 — wait, just count: previous was 70, +3 = 73). Actual expected: **73 passed**.

### Step 8: Manual sanity (you can't run a browser, but verify by reading)

- `grep -nE "chart_window_acc_mags|chart_window_gyro_mags" src/server/broadcast.py` — should show: 1× read inside `_chart_aggregator_tick`, 1× clear inside `_chart_aggregator_tick`. The previous block inside `_status_loop` should be GONE.
- `grep -n "_chart_aggregator_loop\|_chart_aggregator_tick" src/server/broadcast.py server.py` — confirms both names exist in broadcast.py, and `_chart_aggregator_loop` is imported + started in server.py.
- `grep -n "CHART_BUFFER_MAX\|CHART_AGGREGATOR_INTERVAL_S" src/server/broadcast.py` — confirms constants exist.

### Step 9: Commit

```bash
git add tests/test_chart_aggregation.py src/server/broadcast.py server.py
git commit -m "layout(server): 5 Hz chart aggregator (separate asyncio task, 100-entry buffer)"
```

---

## Task 2: Frontend chart visual polish (tension + area fill)

**Files:**
- Modify: `static/js/pages/recording.js` — `_initChart` Chart.js options.

### Step 1: Locate `_initChart`

`grep -n "_initChart\b\|new Chart" static/js/pages/recording.js` finds the chart-construction function. Read its body to understand the current 2-dataset configuration.

### Step 2: Apply visual polish

The two datasets (accel-magnitude and gyro-magnitude lines) get:
- `tension: 0.3` on each dataset for smoother curves.
- `fill: 'origin'` with a low-alpha background colour to add subtle area fill below each line. Use `color-mix`-style alpha by writing a `rgba(...)` value derived from the line stroke — Chart.js accepts these. Match the line stroke colour with ~12% alpha for the fill.

Locate the dataset definitions inside `_initChart` (Chart.js `data.datasets` array). For each dataset, add:

```js
tension: 0.3,
fill: 'origin',
backgroundColor: /* line colour with ~12% alpha — e.g. 'rgba(229, 126, 60, 0.12)' for the accel orange */,
pointRadius: 0,
```

`pointRadius: 0` removes per-point dots so the line reads as a continuous curve (5 Hz updates would otherwise create visible per-point markers).

The "writing" overlay (currently a green band) keeps its existing rendering — find it via `grep -n "writing\|Writing" static/js/pages/recording.js` inside `_initChart` to confirm its dataset config; do not touch.

### Step 3: Run tests

```bash
pytest tests/ -q
```
Expected: 73 passed.

### Step 4: Manual smoke

You can't run a browser. Verify by reading: each dataset has `tension`, `fill: 'origin'`, `backgroundColor` with alpha, `pointRadius: 0`. No other dataset modifications.

### Step 5: Commit

```bash
git add static/js/pages/recording.js
git commit -m "layout(ui): chart visual polish — smooth tension + area fill + no points"
```

---

## Task 3: Frontend — Recording page restructure (markup + CSS + dead-code prune)

**Files:**
- Modify: `static/views/recording.html` — full restructure.
- Modify: `static/css/recording.css` — new section classes.
- Modify: `static/js/pages/recording.js` — remove `_updateDeviceEmpty` calls for removed cards.

### Step 1: Rewrite `static/views/recording.html`

Replace the current 3-column rec-grid layout with this 4-section vertical layout. The Welcome card from Phase 3a stays at the top (do not modify it). The new layout is everything BELOW the welcome card.

Full structure of `recording.html`:

```html
<!-- existing welcome-card from Phase 3a, untouched -->
<div class="welcome-card" id="welcomeCard" style="display:none">
  <!-- ... existing welcome-card content from Phase 3a ... -->
</div>

<!-- Session strip — full-width band with controls + timer + live counters -->
<section class="session-strip">
  <div class="session-strip-controls">
    <div class="session-strip-field">
      <label class="label" for="personId">Person</label>
      <input type="text" id="personId" placeholder="P01" value="P01">
    </div>
    <div class="session-strip-field session-strip-field--wide">
      <label class="label" for="sessionDescription">Description</label>
      <input type="text" id="sessionDescription" placeholder="e.g. 2 min writing, 2 min pause">
    </div>
    <button class="btn btn-primary" id="sessionBtn" onclick="toggleSession()">START</button>
  </div>
  <div class="session-strip-meta">
    <div class="session-strip-timer">
      <div class="timer" id="timer">00:00:00</div>
      <div class="timer-label" id="timerLabel">Ready for a new recording</div>
    </div>
    <div class="session-strip-stats">
      <div class="session-strip-stat">
        <div class="session-strip-stat-label">Watch</div>
        <div class="session-strip-stat-val accent skel-loading" id="watchCount" data-skel>0</div>
      </div>
      <div class="session-strip-stat">
        <div class="session-strip-stat-label">Pen</div>
        <div class="session-strip-stat-val green skel-loading" id="penCount" data-skel>0</div>
      </div>
      <div class="session-strip-stat">
        <div class="session-strip-stat-label">Session</div>
        <div class="session-strip-stat-val stat-val--id" id="sessionIdDisp">—</div>
      </div>
      <div class="session-strip-stat">
        <div class="session-strip-stat-label">Rate</div>
        <div class="session-strip-stat-val stat-val--id skel-loading" id="watchRateMain" data-skel>– Hz</div>
      </div>
    </div>
  </div>
</section>

<!-- Main grid: chart left (60%) + handwriting right (40%) -->
<section class="recording-main-grid">
  <div class="card chart-card" id="liveRecordingHero">
    <div class="chart-meta">
      <div class="card-title">
        Live IMU Signal<span>Accelerometer + Gyroscope Magnitudes</span>
        <span class="live-indicator" id="liveIndicator">Live</span>
      </div>
      <div class="chart-legend">
        <span><span class="leg-dot leg-dot--accel"></span> Accel |a|</span>
        <span><span class="leg-dot leg-dot--gyro"></span> Gyro |r|</span>
        <span><span class="leg-dot leg-dot--writing"></span> Writing</span>
        <span><span class="leg-dot leg-dot--idle"></span> Idle</span>
      </div>
    </div>
    <div class="chart-canvas-wrap" id="chartCanvasWrap">
      <canvas id="imuChart" height="200"></canvas>
      <div class="chart-canvas-empty" data-state-mode="overlay">
        <div class="empty-state">
          <div class="empty-state-glyph">/</div>
          <div class="empty-state-title">Waiting for IMU stream</div>
          <div class="empty-state-hint">Start a session and accelerometer + gyroscope magnitudes will draw here in real time.</div>
        </div>
      </div>
    </div>
    <div class="chart-stats">
      <div class="chart-stat"><div class="val" id="statMag">–</div><div class="lbl">Current |a|</div></div>
      <div class="chart-stat"><div class="val" id="statGyro">–</div><div class="lbl">Current |r|</div></div>
      <div class="chart-stat"><div class="val" id="statWritePct">–</div><div class="lbl">Writing %</div></div>
    </div>
  </div>

  <div class="card handwriting-card">
    <div class="chart-meta">
      <div class="card-title">Live Handwriting Preview<span>Ncode pen path · last 200 dots</span></div>
      <button class="btn btn-sm btn-outline" onclick="clearPenPreview()">Clear</button>
    </div>
    <div class="notebook-canvas pen-canvas-wrap" id="penCanvasWrap">
      <canvas id="penCanvas" height="240"></canvas>
      <div class="pen-canvas-empty" id="penCanvasEmpty" data-state-mode="overlay">
        <div class="empty-state">
          <div class="empty-state-glyph">/</div>
          <div class="empty-state-title">Waiting for pen strokes</div>
          <div class="empty-state-hint">Connect the Smart Pen, start a session, and write — strokes will appear here in real time.</div>
        </div>
      </div>
    </div>
    <div class="pen-canvas-meta">
      <span class="pen-canvas-info" id="penCanvasInfo">No pen data · connect pen and start a session</span>
    </div>
  </div>
</section>

<!-- Session health row — always visible -->
<section class="session-health">
  <div class="session-health-row">
    <div class="session-health-cell"><span class="session-health-key">Watch Hz</span><span class="session-health-val" id="watchHz">–</span></div>
    <div class="session-health-cell"><span class="session-health-key">Pen Hz</span><span class="session-health-val" id="penHz">–</span></div>
    <div class="session-health-cell"><span class="session-health-key">Gyro stream</span><span class="session-health-val" id="gyroHealth">–</span></div>
    <div class="session-health-cell"><span class="session-health-key">Clock align</span><span class="session-health-val" id="clockHealth">–</span></div>
  </div>
</section>

<!-- Live log — collapsed by default -->
<details class="recording-log-details">
  <summary>Live log <span class="recording-log-summary-hint">recent samples + server/device events</span></summary>
  <div class="recording-log-body">
    <div class="log-split">
      <div>
        <div class="label">Sample output</div>
        <div class="log-panel" id="sampleLog"></div>
      </div>
      <div>
        <div class="label">System events</div>
        <div class="log-panel" id="eventLog"></div>
      </div>
    </div>
    <div class="recording-log-actions">
      <button class="btn btn-sm btn-outline" onclick="clearVisualLogs()">Clear view</button>
    </div>
  </div>
</details>
```

**Removed entirely**: the right-column device-cards (`.device-col` and its 3 child cards), the toggle-able health-grid (now exposed as `.session-health`), the `.rec-grid` 3-column wrapper, the `.wide-card` styling on the previous log card. The 3 `_updateDeviceEmpty`-target slot IDs (`penDeviceEmpty` / `penDeviceRows`, watch, airpods) and their wrappers all go.

### Step 2: Add the new CSS in `static/css/recording.css`

Append at the end of the file (or replace any existing `.rec-grid` block — that block is no longer used):

```css
/* ─── Phase 3b-1 Recording layout ────────────────────────────────── */

.session-strip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-5);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-5);
  align-items: center;
}
.session-strip-controls {
  display: flex; align-items: end; gap: var(--space-4);
}
.session-strip-field { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.session-strip-field--wide { flex: 1; min-width: 220px; }
.session-strip-field input[type="text"] {
  /* match existing textarea/input styles from earlier in recording.css */
  width: 100%;
}
.session-strip-meta {
  display: flex; align-items: center; gap: var(--space-5);
}
.session-strip-timer { display: flex; flex-direction: column; gap: var(--space-1); }
.session-strip-stats {
  display: grid; grid-template-columns: repeat(4, auto); gap: var(--space-4);
}
.session-strip-stat {
  display: flex; flex-direction: column; gap: var(--space-1);
}
.session-strip-stat-label {
  font-size: var(--text-xs); text-transform: uppercase; letter-spacing: 0.06em; color: var(--text3);
}
.session-strip-stat-val {
  font-family: var(--mono); font-size: var(--text-md); font-weight: 600; color: var(--text);
  line-height: 1;
}
.session-strip-stat-val.accent { color: var(--accent); }
.session-strip-stat-val.green { color: var(--green); }

.recording-main-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: var(--space-5);
  margin-bottom: var(--space-5);
}

/* Notebook look on the handwriting canvas wrap */
.notebook-canvas {
  background-color: color-mix(in oklch, var(--accent) 4%, var(--surface));
  background-image: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent 19px,
    color-mix(in oklch, var(--border) 50%, transparent) 20px
  );
  border-radius: var(--radius-sm);
  box-shadow: inset 0 0 0 1px var(--border);
}
.notebook-canvas canvas { display: block; width: 100% !important; }

/* Session health row */
.session-health {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-5);
  margin-bottom: var(--space-5);
}
.session-health-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-4);
}
.session-health-cell {
  display: flex; flex-direction: column; gap: var(--space-1);
}
.session-health-key {
  font-size: var(--text-xs); text-transform: uppercase; letter-spacing: 0.06em; color: var(--text3);
}
.session-health-val {
  font-family: var(--mono); font-size: var(--text-base); font-weight: 600; color: var(--text);
}
.session-health-val.ok { color: var(--green); }
.session-health-val.warn { color: var(--yellow); }
.session-health-val.err { color: var(--red); }

/* Collapsed log block */
.recording-log-details {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-5);
  overflow: hidden;
}
.recording-log-details > summary {
  list-style: none;
  cursor: pointer; user-select: none;
  padding: var(--space-3) var(--space-5);
  display: flex; align-items: center; gap: var(--space-2);
  font-size: var(--text-base); font-weight: 600; color: var(--text);
}
.recording-log-details > summary::-webkit-details-marker { display: none; }
.recording-log-details > summary::before {
  content: '▸'; color: var(--text3); font-size: var(--text-xs);
  transition: transform var(--dur-fast) var(--ease-default);
}
.recording-log-details[open] > summary::before { transform: rotate(90deg); }
.recording-log-summary-hint {
  font-weight: 400; font-size: var(--text-sm); color: var(--text3);
  margin-left: var(--space-2);
}
.recording-log-body { padding: var(--space-3) var(--space-5) var(--space-5); }
.recording-log-actions { display: flex; justify-content: flex-end; margin-top: var(--space-3); }

@media (max-width: 1100px) {
  .recording-main-grid { grid-template-columns: 1fr; }
  .session-strip { grid-template-columns: 1fr; }
  .session-strip-stats { grid-template-columns: repeat(2, auto); }
}
```

**Remove from `recording.css`**: any existing `.rec-grid`, `.device-col`, `.device-empty-slot`, `.device-rows`, `.health-grid`, `.health-box` rules that were specific to the Recording-page right column. Use `grep -n ".rec-grid\|.device-col\|.device-empty-slot" static/css/recording.css` to find them and delete.

`.health-grid` and `.health-box` are used elsewhere (Phase 1 Sessions / Connections) — DO NOT delete those rules from `recording.css` unless they are scoped to Recording's prior layout. Check carefully: the rules in `recording.css` for `.health-grid` were dropped of chrome in earlier polish work; if they're generic, leave them. If they're Recording-only (e.g. `#page-recording .health-grid`), delete.

### Step 3: Prune dead JS in `pages/recording.js`

Remove the 3 `_updateDeviceEmpty` calls in `onStatus(s)` (search for `_updateDeviceEmpty`). The function `_updateDeviceEmpty` itself can be deleted since nothing else calls it.

Search the file for any references to the removed IDs and delete each:
- `penDeviceEmpty`, `penDeviceRows`
- `watchDeviceEmpty`, `watchDeviceRows`
- `airpodsDeviceEmpty`, `airpodsDeviceRows`
- `penBadge`, `watchBadge`, `airpodsBadge` (the badges-on-cards; the topbar dots are separate)
- `penConnBtn`, `penDiscBtn` (device-card buttons)
- `penLastXY`, `dotType`, `penRateSide`, `watchRateSide`, `watchGyroSide`, `watchLastTs`, `airpodsRateSide`, `airpodsAccSide`, `airpodsLastTs`, `penBleStatus` — anything that wrote to those elements

Use `grep -nE "penDeviceEmpty|watchDeviceEmpty|airpodsDeviceEmpty|penBadge|watchBadge|airpodsBadge|penLastXY|dotType|penRateSide|watchRateSide|watchGyroSide|watchLastTs|airpodsRateSide|airpodsAccSide|airpodsLastTs|penBleStatus|penConnBtn|penDiscBtn" static/js/pages/recording.js` to find every reference. For each line that ONLY writes to one of these dead IDs, delete the line. For lines that compute a value AND write it (e.g. `el.textContent = fmt(s.x); if (el) ...`), delete the whole `if (el)` block.

**Note**: `setBadge` calls that target `'penBadge'`, `'watchBadge'`, `'airpodsBadge'` — those are dead. Delete the calls.

### Step 4: Run tests

```bash
pytest tests/ -q
```
Expected: 73 passed (no changes affecting tests).

### Step 5: Commit

```bash
git add static/views/recording.html static/css/recording.css static/js/pages/recording.js
git commit -m "layout(ui): Recording page restructure (session strip + chart/handwriting grid + collapsed log)"
```

---

## Task 4: Notebook look on handwriting canvas

The notebook-canvas styling was added in Task 3 (the `.notebook-canvas` rules). This task is intentionally folded into Task 3 — the class is applied to `.pen-canvas-wrap` in the new markup, and the CSS lives alongside the other recording.css rules.

**Skip this task as a separate commit** — verify via `grep -n "notebook-canvas" static/views/recording.html static/css/recording.css` that the class is applied to the pen-canvas wrap and the CSS rule exists.

---

## Task 5: Topbar — AirPods 4. dot + hover-card

**Files:**
- Modify: `dashboard.html` — 4th status-dot + hover-card markup.
- Modify: `static/css/topbar.css` — hover-card styles, 4-dot cluster width.
- Modify: `static/js/core/status_cluster.js` — `_renderStatusHoverCard(s)` + 4th dot wiring.

### Step 1: Markup — add 4th status-dot + hover-card in `dashboard.html`

In `dashboard.html`, find the existing `<button type="button" class="status-cluster" id="statusCluster" ...>` block. Update it to:

```html
<button type="button" class="status-cluster" id="statusCluster"
        title="Hover for device details">
  <span class="status-cluster-dots">
    <span class="status-dot" id="clusterDotPen"     aria-label="Pen"></span>
    <span class="status-dot" id="clusterDotWatch"   aria-label="Watch"></span>
    <span class="status-dot" id="clusterDotAirpods" aria-label="AirPods"></span>
    <span class="status-dot" id="clusterDotServer"  aria-label="Server"></span>
  </span>
  <span class="status-cluster-label" id="statusClusterLabel">connecting…</span>
  <span class="status-cluster-meta" id="statusClusterMeta"></span>

  <span class="status-hover-card" aria-hidden="true">
    <span class="status-hover-row" data-device="pen">
      <span class="status-hover-dot"></span>
      <span class="status-hover-label">Pen</span>
      <span class="status-hover-state" id="hoverPenState">offline</span>
      <span class="status-hover-meta"  id="hoverPenMeta">— Hz · —</span>
    </span>
    <span class="status-hover-row" data-device="watch">
      <span class="status-hover-dot"></span>
      <span class="status-hover-label">Watch</span>
      <span class="status-hover-state" id="hoverWatchState">offline</span>
      <span class="status-hover-meta"  id="hoverWatchMeta">— Hz · —</span>
    </span>
    <span class="status-hover-row" data-device="airpods">
      <span class="status-hover-dot"></span>
      <span class="status-hover-label">AirPods</span>
      <span class="status-hover-state" id="hoverAirpodsState">offline</span>
      <span class="status-hover-meta"  id="hoverAirpodsMeta">— Hz · —</span>
    </span>
    <span class="status-hover-row" data-device="server">
      <span class="status-hover-dot"></span>
      <span class="status-hover-label">Server</span>
      <span class="status-hover-state" id="hoverServerState">connecting</span>
      <span class="status-hover-meta"  id="hoverServerMeta">—</span>
    </span>
  </span>
</button>
```

### Step 2: CSS in `static/css/topbar.css`

Find the existing `.status-cluster-dots` rule and add styling for the new hover card. Append at end of file:

```css
/* Hover-card on the topbar status cluster — same drop-pattern as .brand-tooltip. */
.status-cluster { position: relative; }

.status-hover-card {
  position: absolute;
  top: calc(100% + var(--space-2));
  right: 0;
  display: none;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-3) var(--space-4);
  box-shadow: 0 4px 16px color-mix(in oklch, var(--sidebar) 20%, transparent);
  min-width: 260px;
  text-align: left;
  pointer-events: none;
  z-index: 50;
}
.status-cluster:hover .status-hover-card,
.status-cluster:focus-visible .status-hover-card {
  display: flex;
}

.status-hover-row {
  display: grid;
  grid-template-columns: 14px 70px 1fr;
  align-items: baseline;
  gap: var(--space-2);
  font-family: var(--sans);
  font-size: var(--text-xs);
}
.status-hover-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--text3);
  align-self: center;
}
.status-hover-row[data-device-ok] .status-hover-dot { background: var(--green); }
.status-hover-row[data-device-warn] .status-hover-dot { background: var(--yellow); }
.status-hover-row[data-device-err] .status-hover-dot { background: var(--red); }
.status-hover-label {
  color: var(--text2); font-weight: 600;
}
.status-hover-state {
  color: var(--text); font-weight: 500;
}
.status-hover-meta {
  color: var(--text3); font-family: var(--mono); font-size: var(--text-xs);
  grid-column: 2 / span 2;
}
```

The `data-device-ok` / `-warn` / `-err` attribute will be set by the JS update function based on per-device status.

### Step 3: JS — `_renderStatusHoverCard(s)` in `core/status_cluster.js`

In `static/js/core/status_cluster.js`, locate the existing `setStatusCluster(s)` function and the 3-dot update logic (search for `clusterDotPen` / `clusterDotWatch` / `clusterDotServer`).

Add a 4th dot update for AirPods alongside the existing 3. Mirror the existing per-device predicate (use `airpodsUiOnline` from `s.airpods_connected || s.airpods_paired || s.airpods_streaming` — same as the welcome-card predicate from Phase 3a).

Then add a new helper near `setStatusCluster`:

```js
function _renderStatusHoverCard(s) {
  _hoverRow('pen', _penStatusFromS(s));
  _hoverRow('watch', _watchStatusFromS(s));
  _hoverRow('airpods', _airpodsStatusFromS(s));
  _hoverRow('server', _serverStatusFromS(s));
}

function _hoverRow(device, info) {
  const row = document.querySelector(`.status-hover-row[data-device="${device}"]`);
  if (!row) return;
  const stateEl = row.querySelector('.status-hover-state');
  const metaEl = row.querySelector('.status-hover-meta');
  if (stateEl) stateEl.textContent = info.state;
  if (metaEl) metaEl.textContent = info.meta;
  row.removeAttribute('data-device-ok');
  row.removeAttribute('data-device-warn');
  row.removeAttribute('data-device-err');
  if (info.cls === 'ok') row.setAttribute('data-device-ok', '');
  else if (info.cls === 'warn') row.setAttribute('data-device-warn', '');
  else if (info.cls === 'err') row.setAttribute('data-device-err', '');
}
```

And the 4 per-device info computers — these read from `S.lastStatus` and other state fields. The exact shape depends on what's currently available. Implement them with the SAME predicates already used in `setStatusCluster` for dot-state colour. Pseudo-template:

```js
function _penStatusFromS(s) {
  if (!s) return { cls: 'err', state: 'offline', meta: '— Hz · —' };
  const ok = !!s.pen_connected;
  const hz = s.pen_rate_hz != null ? fmtHz(s.pen_rate_hz) : '—';
  const ago = s.pen_last_seen_ms != null ? fmtAgo(s.pen_last_seen_ms) : '—';
  return {
    cls: ok ? 'ok' : 'err',
    state: ok ? 'connected' : 'offline',
    meta: `${hz} · last ${ago}`,
  };
}
```

Repeat for watch / airpods / server with their respective field names. **Read the existing `setStatusCluster` body** to find the actual field names used today — those are the same ones to use here. If a field doesn't exist for AirPods (e.g. no `airpods_last_seen_ms`), use what's available (`s.airpods_connected ? 'connected' : 'offline'`, no meta).

Wire the call:

In `handleStatus(s, prevSessionId)` (the existing function in `status_cluster.js`), AFTER the existing `setStatusCluster(s)` call, add:

```js
_renderStatusHoverCard(s);
```

### Step 4: Run tests

```bash
pytest tests/ -q
```
Expected: 73 passed.

### Step 5: Commit

```bash
git add dashboard.html static/css/topbar.css static/js/core/status_cluster.js
git commit -m "layout(ui): topbar 4th status dot (AirPods) + hover detail card"
```

---

## Task 6: Audit + PR

**Files:** none necessarily; small fixes only if audit surfaces an issue.

### Step 1: Self-audit

```bash
echo "=== JS scope verification (only recording.js + status_cluster.js allowed under js/) ==="
git diff b54e54a..HEAD --name-only | grep "^static/js/"
echo ""
echo "=== Dead device-card references (should be zero in pages/recording.js) ==="
grep -nE "penDeviceEmpty|watchDeviceEmpty|airpodsDeviceEmpty|penBadge|watchBadge|airpodsBadge|penConnBtn|penDiscBtn|penBleStatus|penLastXY|dotType" static/js/pages/recording.js || echo "(none — good)"
echo ""
echo "=== Recording markup IDs that JS still targets ==="
grep -nE "sessionBtn|timer|imuChart|penCanvas|sampleLog|eventLog|watchCount|penCount|sessionIdDisp|watchRateMain|watchHz|penHz|gyroHealth|clockHealth" static/views/recording.html
echo ""
echo "=== Chart aggregator wiring ==="
grep -n "_chart_aggregator_loop\|_chart_aggregator_tick" src/server/broadcast.py server.py
echo ""
echo "=== AirPods 4th dot ==="
grep -n "clusterDotAirpods" dashboard.html static/js/core/status_cluster.js
echo ""
echo "=== Hover-card rendering ==="
grep -n "status-hover-card\|_renderStatusHoverCard" dashboard.html static/css/topbar.css static/js/core/status_cluster.js
echo ""
echo "=== Tests ==="
pytest tests/ -q | tail -3
```

For any dangling reference returned by the dead-ID grep, decide: delete the line (most common) or update to a still-existing ID. Re-run audit.

### Step 2: Push + open PR

```bash
git push -u origin feature/dashboard-layout-phase3b1
gh pr create --base feature/adapt-web-ui \
  --title "Dashboard layout phase 3b-1 (Recording restructure + 5 Hz chart + hover card)" \
  --body "$(cat <<'EOF'
## Summary

Phase 3b-1 of the dashboard-polish trilogy. Recording page restructured into a focused live-recording surface; per-device cards removed in favour of topbar status dots with a hover detail card; chart aggregation bumped from 1 Hz to 5 Hz for visible motion dynamics.

## What changed

**Server**
- `src/server/broadcast.py`: chart aggregation extracted into `_chart_aggregator_tick(state, pen_writing)` (pure function, easy to test) and a new `_chart_aggregator_loop` asyncio task running at 5 Hz. The 1 Hz `_status_loop` keeps broadcasting; only the aggregation cadence changes.
- `server.py lifespan`: starts both tasks.
- New `tests/test_chart_aggregation.py` (3 cases): mean + buffer trim + active-flag gating.
- `acc_mag` / `gyro_mag` / `mag` keys retained in every chart entry — no consumer breakage.

**Recording page restructure**
- 4 sections: session strip (top, full-width) → main grid (chart 60% + handwriting 40%) → session health row → collapsed log details.
- Device-cards (Pen / Watch / AirPods) removed entirely from Recording.
- Welcome card from Phase 3a stays at the top.

**Chart visual polish**
- Smooth lines (`tension: 0.3`), area fill under each line (low-alpha), no per-point markers.

**Notebook look**
- Handwriting canvas gets `.notebook-canvas` modifier: ruled-paper background via `repeating-linear-gradient`, off-white paper tint via `color-mix`.

**Topbar**
- 4th status dot for AirPods.
- Hover detail card (same drop-pattern as the `.brand-tooltip`): 4 rows with status + Hz + last-seen per device.

## Spec & plan
- `docs/superpowers/specs/2026-05-11-dashboard-layout-phase3b1-design.md`
- `docs/superpowers/plans/2026-05-11-dashboard-layout-phase3b1.md`

## Success criteria conformance
- [x] Recording page renders 4-section layout in both themes.
- [x] Chart updates every 200 ms (5 Hz) — 100-entry buffer = 20 s rolling window.
- [x] Handwriting canvas has ruled-paper background.
- [x] Topbar shows 4 status dots; hover reveals 4-row detail card.
- [x] Device-cards removed; per-device detail lives on Connections page (unchanged) + topbar hover.
- [x] Live Log collapsed by default.
- [x] WS payload keeps `acc_mag` / `gyro_mag` keys.
- [x] `pytest tests/` = 73 passes.
- [x] No JS changes outside `pages/recording.js` and `core/status_cluster.js`.

## Test plan
- [x] `pytest tests/` green at every commit.
- [ ] **You**: start a session — chart updates feel responsive (motion visible within seconds). Walk pen across paper — strokes appear on the notebook-look canvas. Hover the topbar dot-cluster — 4-row detail card appears with current status. Collapse / expand the live-log section. Walk all 5 pages — Recording is the only one with visible changes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:**
- Server 5 Hz aggregator → Task 1.
- Chart polish → Task 2.
- Recording restructure (markup + CSS + dead-code prune) → Task 3.
- Notebook look → folded into Task 3 (documented in Task 4 entry).
- Topbar 4. dot + hover-card → Task 5.
- Audit + PR → Task 6.
- All 11 success criteria from the spec covered.

**Placeholder scan:** No "TBD", no "implement later", no "appropriate error handling", no "similar to Task N". A few intentional notes like "search the file for the actual field name" — these are read-the-existing-code instructions, not placeholders. The `_penStatusFromS` template is a pseudo-template explicitly marked as "Pseudo-template" — the engineer fills in real field names by reading existing code.

**Type/name consistency:** `_chart_aggregator_tick(state, pen_writing)` signature consistent between Task 1 step 4 and the test in step 2. `CHART_BUFFER_MAX = 100` constant referenced exactly. Element IDs (`clusterDotAirpods`, `hoverPenState`, etc.) consistent between HTML in Task 5 step 1 and JS in Task 5 step 3. `_renderStatusHoverCard(s)` signature consistent. `.notebook-canvas` class consistent between markup in Task 3 step 1 and CSS in Task 3 step 2.

No gaps requiring patches.
