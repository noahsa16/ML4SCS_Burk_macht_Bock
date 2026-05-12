# Sessions Tab Redesign — Design Spec

**Date:** 2026-05-11
**Author:** Noah (with Claude, via superpowers:brainstorming)
**Status:** Draft — awaiting review

## Problem

The current Sessions tab is overloaded:

- The table has **14 columns** per session (Watch Samples, Pen Dots,
  AirPods Samples, Watch Hz, Signals, ML Ready, Recording, Diagnostics,
  Status, Report, …). Hard to scan.
- Filtering is weak — only a free-text search. No way to ask "show me
  only sessions with strong alignment" or "only ML-ready ones". Filter
  state does not persist across reloads.
- Clicking a session expands an inline detail row that dumps
  *everything* at once: validation metrics, timeline, drift grid, issue
  list, and the Pen ↔ Watch alignment section with two large canvas
  charts plus explainer text. The user is hit with the full firehose
  the moment they want to look at one session.
- Three different "actions" per row (Diagnostics button, Status pill,
  Report download) add visual noise.

Net effect: the tab is *loud*. Triage ("which sessions are usable?")
and inspection ("what's wrong with this one?") are tangled into one
view.

## Goals

1. **Split triage from inspection.** The Sessions tab becomes a calm
   list optimised for filtering and scanning. Inspecting a single
   session moves to its own page.
2. **Make the list filterable in the ways that matter for ML work** —
   especially "only alignment-trainable sessions". Filter state
   persists across reloads.
3. **Apply progressive disclosure on the detail page.** Show a single
   verdict at the top; everything else is collapsible and starts
   collapsed.

## Non-Goals

- No cross-session comparison view (deferred to a future Evaluate tab —
  same place we'll eventually put cross-subject evaluation).
- No URL-shareable filter state (localStorage is enough for now;
  shareable links arrive with the Evaluate tab).
- No new backend endpoints — all data already exists.
- No re-skin of the Recording page or other tabs.

## Architecture

### Sessions tab — triage list

**Quality summary card** (unchanged): Total / ML Ready / Warnings /
Blocked, plus a Refresh button. It is already calm and informative.

**Filter bar** — persisted to `localStorage` under
`sessionsFilter.v1`:

- Search input (matches Session ID, Person, Description)
- Select **ML Status**: All · Ready · Warn · Blocked
- Select **Alignment**: All · `σ ≤ −3` (trainable) · `σ ≤ −2` (ok) ·
  failed · no pen
- Toggle **≥ 5 min duration**
- "Reset" link clears all four

**Table — 4 columns**:

| Session                                           | Start · Duration        | ML Status | Alignment σ |
|---------------------------------------------------|-------------------------|-----------|-------------|
| **S029** · P01<br><small>"2 min writing, 2 min pause"</small> | 11.05. 14:32 · 7m 12s | ✓ Ready   | −5.27 ✓     |

- Whole row is clickable → opens the Session Detail page.
- No inline expand. No `Diagnostics` / `Report` / per-row buttons.
- Hover highlights the row to signal it's a link.

Everything else from the old 14-column layout (Watch Samples, Pen Dots,
AirPods Samples, Watch Hz, Signals, Recording severity, Diagnostics
button, Report button) moves to the detail page.

### Session Detail — its own page

Routed via hash: `#session/<id>`. Lives as a sibling `<div class="page"
id="page-session-detail">` to the existing pages. While visible, the
Sessions sidebar entry stays marked active (the user is still
conceptually "in Sessions").

**Header — always visible:**

```
←  S029 · P01                                     [⤓ MD-Report]
   "2 min writing, 2 min pause" · 11.05. 14:32 · 7 min 12 s

   ┌─────────────────────────┐
   │      TRAINABLE          │   ← single big verdict
   └─────────────────────────┘
   ML ✓ Ready   Rec ✓   Align σ=−5.27 ✓   ← three small status pills
```

The "←" links back to the Sessions list, restoring its filter state.

**Verdict logic** (`computeVerdict`):

- **Trainable** (green): `ml_readiness == "ok"` ∧ `alignment.sigma ≤ −3`
  ∧ `duration ≥ 5 min`
- **Skip** (red): `ml_readiness == "bad"` *or* any of these issue
  codes are present: `sync_failed`, `streams_do_not_overlap`
- **Usable** (yellow): everything else — fine as raw data, not safe
  for direct training without manual review

Thresholds match the existing ML calibration in CLAUDE.md (σ ≤ −3 for
training, ≥ 5 min for within-session split).

**Four collapsible sections below the header**, all start collapsed.
Each section's open/closed state persists to `localStorage` under
`sessionDetail.section.<name>.open`:

1. **Streams & Samples** — Watch / Pen / AirPods counts, actual Hz,
   coverage %, sample-rate target check.
2. **Timeline & Drift** — the existing timeline visualisation + the
   four drift boxes (Watch / Pen / Relative / Clock offset).
3. **Pen ↔ Watch Alignment** — σ / δ / strokes / quietness factor,
   plus the two canvas charts (variance search curve, strokes on
   watch movement) with their explainer text.
4. **Issues** *(N)* — the issue list with codes, rationale, and
   severity colours. Section title shows the count as a badge.

The detail page only fetches data when it opens (`/sessions/{id}/
validation` and `/sessions/{id}/report?format=json`). Sections render
from the same payload — no per-section round trips.

## Implementation Notes

**Frontend only.** No backend changes. Files touched:

- `dashboard.html` — replace the inner content of
  `<div class="page" id="page-sessions">` (lines 995–1103). Add a new
  `<div class="page" id="page-session-detail">` sibling.
- `static/dashboard.js`:
  - New `renderSessionsList()` driving the 4-column table.
  - New `applyFilters(rows)` — pure function over the cached
    `/sessions/quality` payload.
  - New `loadAndPersistFilters()` / `saveFilters()` for localStorage.
  - New `openSessionDetail(id)` — sets `location.hash`, switches the
    visible page, loads validation + report JSON, populates header +
    sections.
  - New `computeVerdict(quality)` returning
    `{level: "trainable"|"usable"|"skip", label}`.
  - Hash-router extension: on load and on `hashchange`, if hash matches
    `#session/<id>` open the detail page; otherwise show the list.
  - Remove inline-row-expand logic (`detail-row`, `validation-panel.active`
    toggling on row click).
- CSS in `dashboard.html`'s `<style>` block:
  - Add `.verdict-badge.trainable | .usable | .skip`.
  - Add `.session-detail-section` using native `<details>` /
    `<summary>` for collapse behaviour — minimal JS, accessible by
    default.
  - Simplify the existing `.sessions-table` rules (fewer columns).
  - Remove `.detail-row`, `.sessions-table tr.detail-row .validation-
    panel` and the inline-detail rules.

**State management.** No framework introduced — keep the project's
current "vanilla JS + module-scoped state" style. Two new module-level
caches: `_sessionsCache` (last `/sessions/quality` response) and
`_detailCache[id]`. Filters and section-open state live in localStorage.

**Accessibility.** Rows must be reachable by keyboard (use `<a>` or
`role="link" tabindex="0"` + Enter handler). Collapsible sections use
native `<details>` so screen readers and keyboard work out of the box.

## Testing

No new pytest tests are required — this is a frontend-only change and
the existing endpoint tests already cover the data paths the new UI
consumes. Manual smoke checklist:

- Sessions list renders with 4 columns; no inline expand on click.
- Each filter persists across reload (test: pick "σ ≤ −3", reload,
  filter still applied).
- Reset link clears all filters.
- Clicking a row navigates to `#session/<id>`; pressing Back returns
  to the list with filters intact.
- Detail page header shows correct verdict for known sessions
  (S029 → Trainable, S027 → Usable or Skip, S011 → Skip).
- All four sections start collapsed; opening one and reloading the
  page restores it open.
- Old sessions without alignment data (legacy pen CSV) show
  "no pen" in the Alignment filter and "—" in the table.

## Migration / Risks

- The route `#session/<id>` is new. No existing bookmarks rely on
  anything we're removing.
- The old inline-detail behaviour disappears completely — anyone who
  has muscle memory for "click row → see panel under the table" will
  see a page transition instead. Acceptable trade-off; that pattern
  is exactly what we're trying to escape.
- localStorage keys (`sessionsFilter.v1`, `sessionDetail.section.*.open`)
  are versioned (`v1`) so we can break the schema later if filter
  semantics change.

## Open Questions

None at design time. Verdict thresholds (especially the σ boundary
between Trainable and Usable) may need tuning once we look at more
sessions; the constants live in one place (`computeVerdict`) so it's
a one-line change.
