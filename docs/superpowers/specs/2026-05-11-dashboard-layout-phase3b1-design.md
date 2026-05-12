# Dashboard Layout Overhaul — Phase 3b-1 (Recording focus)

**Date:** 2026-05-11
**Author:** Noah Samel (with Claude)
**Status:** Draft — awaiting approval before implementation planning
**Target branch:** `feature/dashboard-layout-phase3b1` off `feature/adapt-web-ui`
**Phase:** 3b-1 of 3 (3b-2 = Connections / info-page consolidation, deferred)

## Goal

Restructure the Recording page from a 3-column "dashboard of everything" into a focused live-recording surface: a session-control strip across the top, the live IMU chart + handwriting preview as the visual centerpiece, a compact session-health row, and the live log collapsed by default. Move per-device technical details off Recording entirely — connection status lives in the topbar status-cluster (gains a 4th dot for AirPods + a hover detail card). Bump the IMU chart aggregation from 1 Hz to 5 Hz so motion dynamics are visible.

## Non-goals

- Layout changes to Sessions / Session Detail / Connections / System pages. Phase 3b-2 if needed.
- Per-axis chart (x/y/z separation). Cut after consideration — too noisy. Magnitudes only (`acc_mag` + `gyro_mag`) at higher refresh.
- New input controls on Recording. Same `personId` / `description` / `START` / `STOP` only.
- Mobile / responsive treatment.
- Tests for new JS chart logic. The HTTP-asset smoke remains the only frontend test.
- New tabs in the topbar. The 4 page-tabs (Recording / Sessions / Connections / System) stay.

## Approach

Six discrete commits, each independently bisectable:

1. **Server: 5 Hz chart aggregator.** A second asyncio task running parallel to the existing `_status_loop` (which stays at 1 Hz for everything else). The new loop aggregates per-axis IMU sample windows into magnitude means every 200 ms, appends to `state.chart_buffer`, trims to 100 entries (= 20 s rolling window). The existing 1 Hz broadcast pushes the latest 100 chart points in every WS payload, same shape as today (just more frequent additions on the server side). `acc_mag` / `gyro_mag` keys preserved exactly.

2. **Frontend: chart visual polish.** `_initChart` in `pages/recording.js` gains Chart.js `tension: 0.3` for smoother curves, `fill: true` with low-alpha gradient under each line. `updateChart(chartPts)` reads the buffer same as today but renders 100 points instead of 60. Existing magnitude logic unchanged.

3. **Frontend: Recording page restructure.** `views/recording.html` rewritten for 4-section layout:
   - `.session-strip` (full-width horizontal flex) — Person ID input, Description textarea, START button, Timer + label, live stats (Watch samples · Pen dots · Sample rate).
   - `.recording-main-grid` (60 / 40 columns) — `.chart-card` left, `.handwriting-card` right (with `.notebook-canvas` class).
   - `.session-health` (compact info row) — gyro stream · clock align · sequence gaps · pen clock status. Replaces the currently-collapsed health-grid.
   - `<details class="recording-log-details">` collapsed by default — contains sample-log + event-log panels.
   - The 3 device-cards (Pen / Watch / AirPods on the right column today) are removed entirely. Their connection state surfaces via topbar dots.

4. **Frontend: notebook-look on handwriting.** `static/css/recording.css` gets a `.notebook-canvas` modifier — `repeating-linear-gradient` for horizontal ruled lines (~20 px spacing), off-white background using `color-mix(in oklch, var(--accent) 4%, var(--surface))`. Pen stroke rendering on the canvas is unchanged.

5. **Topbar: AirPods 4. dot + hover-card.** `dashboard.html` adds the 4th `<span class="status-dot">` inside `.status-cluster-dots`. `topbar.css` gets `.status-hover-card` (positioned absolute below the cluster, hidden by default, shown on `.status-cluster:hover .status-hover-card`, `pointer-events: none` so click still works). `core/status_cluster.js` adds `_renderStatusHoverCard(s)` called from `handleStatus`, populating 4 rows (Pen / Watch / AirPods / Server) with status text + Hz + last-seen. Reuses existing field predicates (mirror `_updateDeviceEmpty` from Phase 2a).

6. **Audit + PR.**

## Architecture

### Server change (Task 1)

**`src/server/state.py`** — add ring buffer or just rely on existing `chart_buffer` with max length raised from 60 to 100.

**`src/server/broadcast.py`** — refactor:

```
existing _status_loop (1 Hz):
  - broadcasts full status payload (incl. chart buffer)
  - clears per-tick state (no change here)

new _chart_aggregator_loop (5 Hz):
  - reads per-axis sample windows (existing chart_window_acc_mags / _gyro_mags
    OR new aggregation fields if those lists are reset per-second today)
  - computes mean → appends 1 chart point to chart_buffer
  - trims chart_buffer to last 100 entries
  - does NOT broadcast (broadcast stays at 1 Hz)
```

The per-sample append site (in `routes/watch.py` where each watch batch is received and `state.chart_window_acc_mags.append(...)` runs) does not need to change — same per-axis aggregation, just consumed 5× more often.

**Critical detail**: today the `_status_loop` clears `chart_window_acc_mags` after each broadcast. With a separate 5 Hz aggregator, the clear has to move into the aggregator loop (every 200 ms) so each chart point uses only the samples from its 200 ms window. Otherwise samples leak between buckets.

Tests: extend `tests/test_quality.py` or add `tests/test_chart_aggregation.py` with a synthetic case — feed 50 samples into a state object, run the aggregator once, assert the chart buffer gains one new entry with the right mean.

### Frontend changes (Tasks 2–5)

**Task 2 (Chart polish)** — only `pages/recording.js` `_initChart`'s `options.elements.line` config + dataset's `fill` property + the existing dataset definitions get `tension`. No new datasets.

**Task 3 (Page restructure)** — touches `views/recording.html`, `static/css/recording.css`, `static/js/pages/recording.js`. The JS changes are mostly deletions:
- Remove `_updateDeviceEmpty` calls (3 of them: pen / watch / airpods).
- Remove references to `#penDeviceEmpty`, `#watchDeviceEmpty`, `#airpodsDeviceEmpty`, and the corresponding `*DeviceRows` IDs (the elements no longer exist).
- Keep all chart / handwriting / timer / log logic unchanged.
- Welcome-card from Phase 3a stays in place above the new `.session-strip`.
- Existing `_updateWelcomeCard` predicate continues to use the same field names (mirrors removed `_updateDeviceEmpty` predicates, which is fine since the predicate semantics live in the welcome-card helper independently).

The session-health row reads the same fields the toggle-able health-grid reads today (`watchHz` / `penHz` / `gyroHealth` / `clockHealth`). The element IDs (`#watchHz` etc.) move from inside the toggle-able panel to the new `.session-health` row — same IDs, new location.

**Task 4 (Notebook look)** — pure CSS. No JS, no HTML changes beyond the class addition done in Task 3.

**Task 5 (Topbar hover-card)** — touches `dashboard.html` (1 new `<span>` for 4th dot + new `<div class="status-hover-card">` block inside the cluster), `topbar.css` (hover-card styles, `.status-cluster-dots` width adjustment for 4 dots), `core/status_cluster.js` (gains 4th node update in `setNetworkNode` callers AND new `_renderStatusHoverCard(s)`).

The hover-card markup:

```html
<div class="status-hover-card" aria-hidden="true">
  <div class="status-hover-row" data-device="pen">
    <span class="status-hover-dot"></span>
    <span class="status-hover-label">Pen</span>
    <span class="status-hover-state">offline</span>
    <span class="status-hover-meta">— Hz · — ago</span>
  </div>
  <!-- Watch, AirPods, Server: same shape -->
</div>
```

`_renderStatusHoverCard(s)` rewrites the 4 rows' `state` + `meta` textContent on each WS tick. Uses the same predicates as the existing dot-state setter for the cluster.

## In scope

- `src/server/state.py` — `chart_buffer` max length 100.
- `src/server/broadcast.py` — new `_chart_aggregator_loop` task; aggregation logic split between this loop and `_status_loop`.
- `tests/test_chart_aggregation.py` (or extension to existing test file) — synthetic test for the new aggregator.
- `static/views/recording.html` — full restructure.
- `static/css/recording.css` — new section classes + notebook look.
- `static/js/pages/recording.js` — chart polish + dead device-card calls removed.
- `dashboard.html` — 4th status-dot + hover-card markup.
- `static/css/topbar.css` — hover-card styles, dot-cluster width.
- `static/js/core/status_cluster.js` — `_renderStatusHoverCard(s)` + 4th dot wiring.

## Out of scope

- Per-axis chart (cut after consideration).
- Other pages' layouts (3b-2).
- New session-control fields.
- Mobile.
- New JS tests for chart logic.
- Connections-page network-map changes.
- Any backwards-incompatible WS payload change. `acc_mag` / `gyro_mag` keys retained exactly.

## Success criteria

1. Recording page renders the 4-section layout in both light + dark themes.
2. Live IMU chart shows updates every 200 ms (5 Hz) instead of 1 Hz today. Same 2 magnitude lines, smoother visual treatment.
3. Chart buffer holds 100 points = 20 s rolling window.
4. Handwriting canvas has ruled-paper background.
5. Topbar shows 4 status dots (Pen · Watch · AirPods · Server).
6. Hovering the topbar status-cluster reveals a 4-row detail card with status + Hz + last-seen per device.
7. Recording page no longer contains individual Pen/Watch/AirPods device cards.
8. Live Log collapsed by default; click expands.
9. WS payload retains `acc_mag` / `gyro_mag` keys per chart entry (no consumer breakage).
10. `pytest tests/` green (existing 70 plus any new aggregator tests).
11. No JS changes outside `pages/recording.js` and `core/status_cluster.js`.

## Risk register

| Risk | Mitigation |
|---|---|
| 5 Hz aggregator broadcast load too high | Aggregator does NOT broadcast — only mutates `state.chart_buffer`. The 1 Hz broadcast carries the whole buffer. Network overhead unchanged. |
| Sample-buckets leak between 200 ms windows | Aggregator clears `chart_window_acc_mags` / `chart_window_gyro_mags` (or whatever the accumulator state is named) every tick. Test fixture verifies bucket isolation. |
| Per-sample append in `routes/watch.py` runs concurrently with aggregator's clear → race | Python's GIL makes individual list operations atomic; the aggregator reads-and-clears with a single bound variable, samples appended in-between go into the next bucket. Acceptable. If asyncio later moves to threaded handlers, this would need a lock. |
| Hover-card overlaps content underneath | `pointer-events: none` so it doesn't capture clicks. Positioned absolute, z-index above content but below other modals (which don't exist here). Same pattern as `.brand-tooltip`. |
| Removed device-cards leave dangling `getElementById` calls returning null | All such calls in `pages/recording.js` already use `if (el)` guards (Phase 2a discipline). Audit grep before commit. |
| Welcome card from Phase 3a renders above the new session-strip and looks misaligned | Both are full-width flex blocks stacked vertically. Welcome-card's `margin-bottom: var(--space-5)` provides separation. Visual smoke confirms. |
| Existing chart consumers (debug-package export) get 100-entry buffer instead of 60 | Debug-package serialises `state.chart_buffer` as-is. Consumer code (if any) reads JSON; a longer array is backwards-compatible. |
| AirPods badge field names differ from current status-cluster wiring | Read `core/status_cluster.js` existing `setStatusCluster` body to identify the 3 current device fields. AirPods adds a 4th using the same predicate pattern (`airpodsUiOnline` derived from `s.airpods_connected || s.airpods_paired || s.airpods_streaming` per Phase 3a precedent). |

## Open questions

None blocking. Possible future:

- Per-axis chart as a debug overlay toggle (out of scope for 3b-1; could revisit if motion-analysis becomes a workflow).
- Tab structure refactor (the brief mentioned "small tabs at top" — current 4-page-tabs serve the purpose; revisit only if Phase 3b-2 needs it).
- Sticky session-strip on scroll (out of scope for now — would need fixed positioning + width math).
