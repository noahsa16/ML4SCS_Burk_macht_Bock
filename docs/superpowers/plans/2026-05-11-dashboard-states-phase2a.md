# Dashboard States Phase 2a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the existing `.empty-state` editorial pattern systematically to every dashboard component that can currently appear blank or half-finished. Add section-level loading indicators where the user currently sees a flash of nothing before data arrives. Output: no page reads as "half-built" in any reachable state.

**Architecture:** One small `core/states.js` helper exporting `renderState(slot, kind, opts)`. Two state classes (`loading`, `empty`) plus a `clear` operation. 5 existing inline empty-states migrated; 10+ new empty-state sites added; 3 section-level loading sites added. No layout changes, no error states (deferred to 2b), no JS changes outside the helper and page modules.

**Tech Stack:** Vanilla CSS with OKLCH tokens, native ES modules, DOMParser injection (no inline string-to-markup assignment), FastAPI `StaticFiles`.

**Spec:** `docs/superpowers/specs/2026-05-11-dashboard-states-phase2a-design.md`

---

## Conventions

- All paths relative to project root `/Users/noahsamel/PycharmProjects/ML4SCS_Burk_macht_Bock`.
- Base commit: `c43542d` on `feature/adapt-web-ui` (spec commit). New branch: `feature/dashboard-states-phase2a`.
- After each task, dashboard must still render. `pytest tests/` = 68 passing at every commit (becomes 69 after Task 1 adds the new asset row).
- Commit messages use `states(ui):` prefix.
- Both light and dark theme must remain visually plausible (the empty-state CSS is theme-aware already).
- **No JS changes outside `core/states.js` and `pages/*.js`.** No edits to `core/api.js`, `core/ws.js`, `core/router.js`, or `core/status_cluster.js` are required by this plan; if you reach for one, you're out of scope.
- **DOM-safety convention.** Wherever the existing page modules assign HTML strings into `.innerHTML`, the migration replaces that with either (a) `renderState(...)` calls into a slot — the helper internally uses `DOMParser` + `replaceChildren` — or (b) direct `document.createElement` + `appendChild` / `replaceChildren` constructions. The plan **never introduces new** string-into-markup assignments. Existing assignments outside this PR's scope are not touched.

---

## Task 1: Create branch + core/states.js helper + loading CSS

**Files:**
- Create: `static/js/core/states.js`
- Modify: `static/css/base.css` (add `.empty-state--loading` modifier + inline variant)
- Modify: `tests/test_dashboard_static.py` (add parametrise row)

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feature/dashboard-states-phase2a
```

Expected: `Switched to a new branch 'feature/dashboard-states-phase2a'`.

- [ ] **Step 2: Add parametrise row to the static-asset smoke test**

In `tests/test_dashboard_static.py`, find the parametrise list and add `"/static/js/core/states.js"` in alphabetical order (between `router.js` and `status_cluster.js`).

Run: `pytest tests/test_dashboard_static.py -v`
Expected: the new case FAILS with 404.

- [ ] **Step 3: Create `static/js/core/states.js`**

The helper renders one of two state kinds (`loading`, `empty`) into a slot. A third kind (`clear`) transitions the slot back to data-showing mode.

The slot has one of two modes, declared via `data-state-mode` on the slot element:

- **replace** (default, no attribute or `data-state-mode="replace"`): the slot's children get replaced with a freshly-built empty-state block. Use for table cells, info-block wrappers, page containers — anywhere the data view IS the normal content.
- **overlay** (`data-state-mode="overlay"`): the slot is treated as a positioned overlay sibling whose visibility is controlled by toggling a `.has-data` class on the parent. The slot's empty-state markup is already in the static HTML; the helper only rewrites `.empty-state-title` and `.empty-state-hint` via `textContent`, and toggles the loading modifier class.

Use this exact module body:

```js
/**
 * Render an empty / loading state into a slot. See plan task 1 for the slot-
 * mode contract.
 *
 * @param {HTMLElement} slot
 * @param {'loading' | 'empty' | 'clear'} kind
 * @param {object} [opts]
 * @param {string} [opts.title]   - first line, required for loading/empty
 * @param {string} [opts.hint]    - second line, optional
 * @param {string} [opts.glyph]   - override the default '/' glyph
 * @param {{ label: string, onClick: () => void }} [opts.action] - empty only
 * @param {boolean} [opts.inline] - compact one-line variant (replace mode only)
 */
export function renderState(slot, kind, opts = {}) {
  if (!slot) return;
  const mode = slot.dataset.stateMode === 'overlay' ? 'overlay' : 'replace';
  if (mode === 'overlay') {
    _overlay(slot, kind, opts);
  } else {
    _replace(slot, kind, opts);
  }
}

function _overlay(slot, kind, opts) {
  const wrap = slot.parentElement;
  if (kind === 'clear') {
    if (wrap) wrap.classList.add('has-data');
    return;
  }
  if (wrap) wrap.classList.remove('has-data');
  const titleEl = slot.querySelector('.empty-state-title');
  const hintEl = slot.querySelector('.empty-state-hint');
  if (titleEl && opts.title != null) titleEl.textContent = opts.title;
  if (hintEl && opts.hint != null) hintEl.textContent = opts.hint;
  // toggle loading-pulse class on the inner block
  const block = slot.querySelector('.empty-state');
  if (block) block.classList.toggle('empty-state--loading', kind === 'loading');
}

function _replace(slot, kind, opts) {
  if (kind === 'clear') {
    const child = slot.querySelector(':scope > .empty-state');
    if (child) child.remove();
    return;
  }
  const block = _buildBlock(kind, opts);
  slot.replaceChildren(block);
  if (kind === 'empty' && opts.action) {
    const btn = block.querySelector('.empty-state-action');
    if (btn) btn.addEventListener('click', opts.action.onClick);
  }
}

function _buildBlock(kind, opts) {
  const inline = opts.inline === true;
  const tag = inline ? 'span' : 'div';
  const root = document.createElement(tag);
  root.className = 'empty-state'
    + (kind === 'loading' ? ' empty-state--loading' : '')
    + (inline ? ' empty-state--inline' : '');

  const glyph = document.createElement(inline ? 'span' : 'div');
  glyph.className = 'empty-state-glyph';
  glyph.textContent = opts.glyph || '/';
  root.appendChild(glyph);

  const title = document.createElement(inline ? 'span' : 'div');
  title.className = 'empty-state-title';
  title.textContent = opts.title || '';
  root.appendChild(title);

  if (!inline && opts.hint) {
    const hint = document.createElement('div');
    hint.className = 'empty-state-hint';
    hint.textContent = opts.hint;
    root.appendChild(hint);
  }

  if (!inline && kind === 'empty' && opts.action) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'empty-state-action';
    btn.textContent = opts.action.label;
    root.appendChild(btn);
  }

  return root;
}
```

All values that originate outside the module go through `textContent` (never assigned into markup as a string). No `innerHTML` is used anywhere in the helper.

- [ ] **Step 4: Add the loading CSS modifier + inline variant**

Append to `static/css/base.css` (after the existing `.empty-state-action:active` rule):

```css
.empty-state--loading .empty-state-glyph {
  animation: pulse 1.6s ease-in-out infinite;
}

/* Inline variant — single-line tag for use inside table cells / info-rows
   where the block layout would be too tall. */
.empty-state--inline {
  display: inline-flex; align-items: baseline; gap: var(--space-1);
  font-size: var(--text-xs); color: var(--text3);
  font-style: italic;
}
.empty-state--inline .empty-state-glyph {
  font-size: var(--text-xs); margin-bottom: 0; line-height: 1;
  font-style: italic; color: var(--accent); opacity: 0.55;
}
.empty-state--inline .empty-state-title {
  font-size: var(--text-xs); color: var(--text3); margin-bottom: 0;
  font-weight: 500; font-family: var(--sans);
}
```

The `@keyframes pulse` is already defined in base.css; this reuses it.

- [ ] **Step 5: Run tests**

```bash
pytest tests/ -q
```
Expected: 69 passed.

- [ ] **Step 6: Commit**

```bash
git add static/js/core/states.js static/css/base.css tests/test_dashboard_static.py
git commit -m "states(ui): add core/states.js helper + loading CSS modifier"
```

---

## Task 2: Migrate the 5 existing inline empty-states onto the helper

**Files modified:**
- `static/js/pages/sessions.js`
- `static/js/pages/recording.js`
- `static/js/pages/session_detail.js`
- `static/views/sessions.html`
- `static/views/recording.html`
- `static/views/session-detail.html`

This is the proof-of-API task. If `renderState` doesn't fit one of these five comfortably, iterate the helper before continuing to Task 3.

### Step 1: Sessions filtered-empty (replace mode)

In `static/js/pages/sessions.js`, find `renderSessionsList(rows)` around line 166. The current code assigns a multi-line empty-state HTML template into `tbody.innerHTML` when `rows.length === 0`.

Replace the no-rows branch with this (no string-to-markup assignment):

```js
import { renderState } from '/static/js/core/states.js';

function renderSessionsList(rows) {
  const tbody = document.getElementById('sessionsBody');
  if (rows.length === 0) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.id = 'sessionsEmptySlot';
    row.appendChild(cell);
    tbody.replaceChildren(row);
    renderState(cell, 'empty', {
      title: 'No matching sessions',
      hint: 'Adjust the filters above, or start a new recording from the Recording tab.',
    });
    return;
  }
  // ... rest of renderSessionsList unchanged
}
```

The existing `tbody.innerHTML = rows.map(...)...` line further down (the rows-present branch) is **out of scope** for this PR — keep it as is.

### Step 2: Recording chart-canvas-empty (overlay mode)

In `static/views/recording.html`, find `<div class="chart-canvas-empty">` (around line 51) and add the overlay attribute:

```html
<div class="chart-canvas-empty" data-state-mode="overlay">
  <div class="empty-state">
    <div class="empty-state-glyph">/</div>
    <div class="empty-state-title">Waiting for IMU stream</div>
    <div class="empty-state-hint">Start a session and accelerometer + gyroscope magnitudes will draw here in real time.</div>
  </div>
</div>
```

The empty-state markup stays in HTML. Only the `data-state-mode` attribute is new.

In `pages/recording.js`, add the import and migrate the call sites that today toggle `.has-data` on the chart wrap. Locate them by searching for `chartCanvasWrap` or `has-data` in the file. Wherever the code adds the class, replace with:

```js
import { renderState } from '/static/js/core/states.js';

// when data is present (chart wrap getting .has-data):
renderState(document.querySelector('.chart-canvas-empty'), 'clear');

// when re-showing the empty state (chart wrap losing .has-data):
renderState(document.querySelector('.chart-canvas-empty'), 'empty', {
  title: 'Waiting for IMU stream',
  hint: 'Start a session and accelerometer + gyroscope magnitudes will draw here in real time.',
});
```

The title/hint are passed redundantly with the static HTML — that's intentional, so future copy edits live in one place (the JS call) and the static HTML is treated as fallback markup.

### Step 3: Recording pen-canvas-empty (overlay mode)

Same pattern as Step 2 for `<div class="pen-canvas-empty" id="penCanvasEmpty">` (around line 163 of `recording.html`). Add `data-state-mode="overlay"`. Find the show/hide logic in `pages/recording.js` (`updatePenCanvas`, `clearPenPreview`, or `drawPenCanvas`) and migrate to `renderState` calls.

### Step 4: Session Detail alignment-empty (replace mode upgrade)

In `static/views/session-detail.html`, find:

```html
<div class="alignment-empty" id="alignmentEmpty" style="display:none">Alignment ist für diese Session nicht verfügbar.</div>
```

Replace with:

```html
<div class="alignment-empty" id="alignmentEmpty" style="display:none"></div>
```

In `pages/session_detail.js`, find calls that set `alignmentEmpty.style.display`. Where the old code set display to `block` (alignment unavailable), replace with:

```js
import { renderState } from '/static/js/core/states.js';

const slot = document.getElementById('alignmentEmpty');
slot.style.display = '';
renderState(slot, 'empty', {
  title: 'No alignment data',
  hint: 'Pen and watch streams don\'t overlap, or the session was too short to align.',
});
```

Where the old code set display to `none` (alignment available), add a clear call:

```js
const slot = document.getElementById('alignmentEmpty');
slot.style.display = 'none';
renderState(slot, 'clear');
```

The inline `style="display:none"` stays as initial state so the slot is hidden before the JS decides whether to show it.

### Step 5: Sessions initial "Loading sessions…" placeholder

In `static/views/sessions.html`, the initial table-body placeholder currently contains a static empty-state row with text only. Replace the entire `<tbody id="sessionsBody">` initial content with a single empty placeholder:

```html
<tbody id="sessionsBody"></tbody>
```

In `pages/sessions.js mount()`, render the loading state into a placeholder row:

```js
const tbody = document.getElementById('sessionsBody');
if (tbody) {
  const row = document.createElement('tr');
  const cell = document.createElement('td');
  cell.colSpan = 4;
  cell.id = 'sessionsTableSlot';
  row.appendChild(cell);
  tbody.replaceChildren(row);
  renderState(cell, 'loading', { title: 'Loading sessions…' });
}
```

When `loadSessions()` returns and `renderSessionsList(rows)` runs, the existing tbody-assignment naturally replaces the loading row with data rows (or the helper's empty-state from Step 1).

### Step 6: Run tests + commit

```bash
pytest tests/ -q
git add -A
git commit -m "states(ui): migrate 5 existing inline empty-states to renderState helper"
```

### Step 7: Self-check

`grep -rE "empty-state-glyph|empty-state-title|empty-state-hint" static/js/pages/` → zero matches. All empty-state HTML now comes from the helper or from static view partials.

`grep -rE "empty-state-glyph|empty-state-title|empty-state-hint" static/views/` → still returns the 3 overlay markup blocks (chart-canvas-empty, pen-canvas-empty, alignment-empty becomes a small one-liner without a fixed title structure — actually for alignment-empty the HTML is now empty after Step 4, so only 2 overlay blocks remain). That's expected — overlay mode keeps the markup and lets the helper rewrite text via textContent.

---

## Task 3: Recording — device-card empty states + log panel empty states

**Files modified:** `static/views/recording.html`, `static/css/recording.css`, `static/js/pages/recording.js`

### Step 1: Markup — add an inline empty-state slot to each device card

For each of the 3 device cards (Pen, Watch, AirPods) in `static/views/recording.html`, insert an empty-state slot between `.device-header` and the first `.device-row`. Wrap the existing device-rows in a `.device-rows` div so the JS can hide them as a group.

Example for Pen card:

```html
<div class="card card-muted">
  <div class="device-header">
    <div class="device-name">Smart Pen</div>
    <div class="status-badge badge-err" id="penBadge">Disconnected</div>
  </div>
  <div class="device-empty-slot" id="penDeviceEmpty" style="display:none"></div>
  <div class="device-rows" id="penDeviceRows">
    <div class="device-row"><span>Dot type</span><span class="v" id="dotType">–</span></div>
    <!-- other existing rows -->
  </div>
  <!-- rest of card unchanged: card-details, toggle, device-actions -->
</div>
```

Repeat for Watch (`#watchDeviceEmpty` / `#watchDeviceRows`) and AirPods (`#airpodsDeviceEmpty` / `#airpodsDeviceRows`).

### Step 2: CSS — device-empty-slot styling

Add to `static/css/recording.css`:

```css
.device-empty-slot {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border);
  font-size: var(--text-sm); color: var(--text3); font-style: italic;
}
.device-empty-slot:empty { display: none !important; }
```

### Step 3: JS — wire from `onStatus`

In `pages/recording.js`, add the import at the top and a small helper near other private functions:

```js
import { renderState } from '/static/js/core/states.js';

function _updateDeviceEmpty(slotId, rowsId, connected, title) {
  const slot = document.getElementById(slotId);
  const rows = document.getElementById(rowsId);
  if (!slot || !rows) return;
  if (connected) {
    slot.style.display = 'none';
    rows.style.display = '';
    renderState(slot, 'clear');
  } else {
    slot.style.display = '';
    rows.style.display = 'none';
    renderState(slot, 'empty', { title, inline: true });
  }
}
```

In `onStatus(s)`, near the existing badge updates (search for `penBadge`/`watchBadge`/`airpodsBadge`), add:

```js
_updateDeviceEmpty('penDeviceEmpty', 'penDeviceRows', !!s.pen_connected,
  'Connect the pen to see live dot data.');
_updateDeviceEmpty('watchDeviceEmpty', 'watchDeviceRows',
  !!(s.watch_connected || s.watch_stream_active),
  'Start the watch app to see live IMU data.');
_updateDeviceEmpty('airpodsDeviceEmpty', 'airpodsDeviceRows',
  !!s.airpods_connected,
  'Connect AirPods to capture head IMU.');
```

The connected-check predicates must mirror what determines the corresponding badge state. Read the existing code that sets `#penBadge` / `#watchBadge` / `#airpodsBadge` and use the same expressions — do not invent a new definition of "connected".

### Step 4: Log panel empty states

In `pages/recording.js renderLogs()` (≈line 390), the current function assigns `sampleEl.innerHTML = sampleRows.map(...).join('')` and similarly for `eventEl`. The migration here is to handle the no-rows case via the helper; the rows-present case keeps its current behaviour (out of scope to migrate the row-rendering itself).

Add the no-rows branch:

```js
export function renderLogs() {
  const sampleEl = document.getElementById('sampleLog');
  const eventEl = document.getElementById('eventLog');
  const sampleRows = (S.sampleLog || []).slice(-S.logRows);
  const eventRows = (S.eventLog || []).slice(-S.logRows);

  if (sampleRows.length === 0) {
    renderState(sampleEl, 'empty', {
      title: 'No samples yet',
      hint: 'Sample stream begins once a session is recording.',
    });
  } else {
    // existing rows-present code stays unchanged
    sampleEl.innerHTML = sampleRows.map(renderSampleRow).join('');
  }

  if (eventRows.length === 0) {
    renderState(eventEl, 'empty', {
      title: 'No events yet',
      hint: 'Server and device events will appear here.',
    });
  } else {
    eventEl.innerHTML = eventRows.map(renderEventRow).join('');
  }
}
```

The placeholder `<div class="log-row">` blocks currently inside `<div id="sampleLog">` and `<div id="eventLog">` in `recording.html` are no longer needed — the helper renders the empty state when rows are zero. Remove them from the static HTML:

```html
<div class="log-panel" id="sampleLog"></div>
<div class="log-panel" id="eventLog"></div>
```

### Step 5: Run tests + commit

```bash
pytest tests/ -q
git add -A
git commit -m "states(ui): Recording device cards + log panels empty states"
```

---

## Task 4: Sessions — quality summary 4-tiles loading state

**Files modified:** `static/views/sessions.html`, `static/css/sessions.css`, `static/js/pages/sessions.js`

### Step 1: Markup

In `static/views/sessions.html`, wrap the existing `.health-grid` with a `.health-grid-wrap` and add an overlay sibling for the loading state. The 4 tiles inside the grid stay unchanged.

```html
<div class="health-grid-wrap">
  <div class="health-grid">
    <!-- existing 4 .health-box tiles unchanged -->
  </div>
  <div class="health-grid-loading" id="healthGridLoading" data-state-mode="overlay">
    <div class="empty-state empty-state--loading">
      <div class="empty-state-glyph">/</div>
      <div class="empty-state-title">Loading…</div>
    </div>
  </div>
</div>
```

### Step 2: CSS

Add to `static/css/sessions.css`:

```css
.health-grid-wrap { position: relative; }
.health-grid-loading {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: color-mix(in oklch, var(--surface) 80%, transparent);
  pointer-events: none;
  transition: opacity var(--dur-slow) var(--ease-default);
}
.health-grid-wrap.has-data .health-grid-loading { opacity: 0; }
```

### Step 3: JS — show on mount, clear on first quality data

In `pages/sessions.js`:

```js
import { renderState } from '/static/js/core/states.js';
```

In `mount()`, do not add explicit code — the static HTML already shows the loading overlay since `.has-data` is absent on the wrap initially.

In `renderQualitySummary()` (or wherever the 4 tile values are populated — search for `qualityTotal` / `qualityOk` etc.), at the end of the function:

```js
renderState(document.getElementById('healthGridLoading'), 'clear');
```

This adds `.has-data` to the wrap → CSS fades out the overlay.

### Step 4: Run tests + commit

```bash
pytest tests/ -q
git add -A
git commit -m "states(ui): Sessions quality summary loading state"
```

---

## Task 5: Session Detail — page-body loading + drift/timeline empty + alignment loading

**Files modified:** `static/views/session-detail.html`, `static/css/session-detail.css`, `static/js/pages/session_detail.js`

### Step 1: Page-body loading slot

In `static/views/session-detail.html`, add as the FIRST child of the partial (before `.session-detail-header`):

```html
<div class="page-detail-loading" id="pageDetailLoading" style="display:none">
  <div class="empty-state empty-state--loading">
    <div class="empty-state-glyph">/</div>
    <div class="empty-state-title">Loading session…</div>
    <div class="empty-state-hint">Fetching quality, alignment and timeline data.</div>
  </div>
</div>
```

### Step 2: CSS

Add to `static/css/session-detail.css`:

```css
#page-session-detail { position: relative; }
.page-detail-loading {
  position: absolute; inset: 0; z-index: 5;
  display: flex; align-items: center; justify-content: center;
  background: color-mix(in oklch, var(--bg) 85%, transparent);
}
```

### Step 3: JS — show on openSessionDetail, hide on resolve

In `pages/session_detail.js`, find `openSessionDetail(id)`. Wrap its body:

```js
export async function openSessionDetail(id) {
  const loadingSlot = document.getElementById('pageDetailLoading');
  if (loadingSlot) loadingSlot.style.display = '';

  try {
    // ... existing fetch + render logic ...
  } finally {
    if (loadingSlot) loadingSlot.style.display = 'none';
  }
}
```

The `finally` ensures the loading overlay doesn't get stuck if the fetch throws today (real error handling is Phase 2b — for now, the page just falls back to whatever data it has).

### Step 4: Drift-grid empty state

In `pages/session_detail.js`, find where the 4 drift-box values (`driftWatch`, `driftPen`, `driftRelative`, `driftSyncOffset`) are populated. Add a guard before the populate logic:

```js
// Determine whether timeline overlap exists. The exact field name comes from
// the validation payload — check the existing code path. Common candidates:
//   validation.timeline_overlap_seconds > 0
//   validation.overlap !== null
// Use whatever the existing code uses to decide if drift can be shown.
const hasOverlap = /* same expression used elsewhere in this function */;

if (!hasOverlap) {
  ['driftWatch', 'driftPen', 'driftRelative', 'driftSyncOffset'].forEach(id => {
    const el = document.getElementById(id);
    if (el) renderState(el, 'empty', { title: 'no overlap', inline: true });
  });
  return; // skip the rest of drift population
}
// existing populate logic
```

If the existing code does not have a single overlap predicate, search for the condition that currently controls whether drift values are shown vs '–'. The condition becomes the predicate above.

### Step 5: Timeline empty state

The timeline lives in `<div class="timeline-wrap" id="detailTimeline"></div>`. In `pages/session_detail.js renderTimeline(v)`, at the start:

```js
function renderTimeline(v) {
  const slot = document.getElementById('detailTimeline');
  if (!slot) return;
  if (!v || !v.timeline_overlap) {
    renderState(slot, 'empty', {
      title: 'No timeline overlap',
      hint: 'Pen and watch did not record in the same window for this session.',
    });
    return;
  }
  // ... existing drawing logic unchanged ...
}
```

Verify `v.timeline_overlap` is the right field; if not, use whatever the existing code already checks before drawing.

### Step 6: Alignment loading + supersede Task 2 Step 4 empty

The alignment data fetches asynchronously when the Alignment details section is opened. Find `renderAlignment` in `pages/session_detail.js`. The function currently renders directly into the alignment DOM. Add a loading state on entry, and combine with the Task 2 Step 4 empty-state branch:

```js
function renderAlignment(sessionId) {
  const empty = document.getElementById('alignmentEmpty');
  if (empty) {
    empty.style.display = '';
    renderState(empty, 'loading', { title: 'Computing alignment…' });
  }

  // ... existing fetch / compute logic ...

  // When alignment data arrives and is valid:
  if (empty) {
    empty.style.display = 'none';
    renderState(empty, 'clear');
  }
  // ... existing render-charts-and-metrics logic ...

  // When alignment is not available:
  if (empty) {
    empty.style.display = '';
    renderState(empty, 'empty', {
      title: 'No alignment data',
      hint: 'Pen and watch streams don\'t overlap, or the session was too short to align.',
    });
  }
}
```

The exact branching (success vs no-alignment) depends on the existing code path. Apply the loading-then-resolve pattern wherever the function decides which to render.

### Step 7: Run tests + commit

```bash
pytest tests/ -q
git add -A
git commit -m "states(ui): Session Detail page-body loading + drift/timeline/alignment empty"
```

---

## Task 6: Connections — device-card empty states

**Files modified:** `static/views/connections.html`, `static/css/connections.css`, `static/js/pages/connections.js`

### Step 1: Markup

For each of the Pen and Watch device cards in `static/views/connections.html`, insert an inline empty-state slot between `.device-header` and `.info-block`:

```html
<div class="card">
  <div class="device-header">
    <div class="card-title">Pen — NWP-F130 (BLE)</div>
    <div class="status-badge badge-err" id="connPenBadge">Disconnected</div>
  </div>
  <div class="conn-empty-slot" id="connPenEmpty" style="display:none"></div>
  <div class="info-block">
    <!-- existing rows -->
  </div>
  <!-- rest unchanged -->
</div>
```

Similarly for Watch card with `#connWatchEmpty`.

### Step 2: CSS

Add to `static/css/connections.css`:

```css
.conn-empty-slot {
  padding: var(--space-3) 0; margin-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
}
.conn-empty-slot:empty { display: none !important; }
```

### Step 3: JS

In `pages/connections.js`:

```js
import { renderState } from '/static/js/core/states.js';

function _toggleConnEmpty(slotId, connected, title) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  if (connected) {
    slot.style.display = 'none';
    renderState(slot, 'clear');
  } else {
    slot.style.display = '';
    renderState(slot, 'empty', { title, inline: true });
  }
}
```

In `onStatus(payload)`, near the existing device updates:

```js
_toggleConnEmpty('connPenEmpty', !!payload.pen_connected,
  'Connect the pen to populate live data');
_toggleConnEmpty('connWatchEmpty',
  !!(payload.watch_connected || payload.watch_stream_active),
  'Connect the watch app to populate live data');
```

Match the existing connected-predicate (the same one driving the badge state). Do not invent a new definition.

### Step 4: Run tests + commit

```bash
pytest tests/ -q
git add -A
git commit -m "states(ui): Connections device cards empty states"
```

---

## Task 7: System — validation-check rows inline empty tags

**Files modified:** `static/js/pages/system.js`

The 4 validation check values (`#checkAccel`, `#checkGyro`, `#checkPenTime`, `#checkRate`) currently render `–` until live data arrives. Replace the dash with an inline empty-state tag for the first paint.

### Step 1: JS

In `pages/system.js`:

```js
import { renderState } from '/static/js/core/states.js';

const CHECK_IDS = ['checkAccel', 'checkGyro', 'checkPenTime', 'checkRate'];

export function mount(container) {
  // ... existing mount code (if any) ...
  CHECK_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) renderState(el, 'empty', { title: 'waiting for status', inline: true });
  });
}
```

In `onStatus(s)`, the existing populate logic naturally overwrites the empty state via direct `textContent` assignment on each check element. No change to `onStatus` is required (the empty tag is just placeholder text — it's replaced wholesale when status arrives).

### Step 2: Run tests + commit

```bash
pytest tests/ -q
git add -A
git commit -m "states(ui): System validation checks inline empty state"
```

---

## Task 8: Audit pass + PR

**Files modified:** none expected; small fixes only if the audit surfaces issues.

### Step 1: Self-audit grep sweep

```bash
echo "Inline empty-state markup left in pages JS:"
grep -rE "empty-state-glyph|empty-state-title|empty-state-hint" static/js/pages/ || echo "(none — good)"

echo ""
echo "Loading-state calls (each should be gated by an initial-fetch flag, NOT per WS tick):"
grep -rnE "renderState\([^,]+,\s*['\"]loading['\"]" static/js/pages/

echo ""
echo "Pages with no renderState use:"
for f in static/js/pages/*.js; do
  if ! grep -q renderState "$f"; then echo "  $f"; fi
done
```

For each `renderState(..., 'loading', ...)` call surfaced by the grep, read the surrounding context. Confirm: the call is in `mount()` or in an event handler triggered once (e.g. `openSessionDetail`). It must NOT be inside `onStatus(payload)` — onStatus runs every WS tick and would re-render the loading state forever.

### Step 2: Run final tests

```bash
pytest tests/ -q  # expect 69 passed
```

### Step 3: Push + open PR

```bash
git push -u origin feature/dashboard-states-phase2a
gh pr create --base feature/adapt-web-ui \
  --title "Dashboard states phase 2a (empty + loading)" \
  --body "$(cat <<'EOF'
## Summary

Phase 2a of the dashboard-polish trilogy. Adds systematic empty + loading state coverage to every page. One core helper (\`renderState\`), 5 existing inline empty-states migrated to the helper, 11 new empty-state sites added, 2 section-level loading sites added (Sessions quality summary, Session Detail page-body) plus alignment lazy-load. No layout, no error states (Phase 2b), no branding (Phase 3).

## Spec & plan
- \`docs/superpowers/specs/2026-05-11-dashboard-states-phase2a-design.md\`
- \`docs/superpowers/plans/2026-05-11-dashboard-states-phase2a.md\`

## Success criteria conformance
- [ ] 1. \`core/states.js\` exports \`renderState\` with JSDoc.
- [ ] 2. Parametrise list includes \`/static/js/core/states.js\`.
- [ ] 3. Zero inline empty-state template strings in \`static/js/pages/\` (grep clean).
- [ ] 4. Every page mounts with at least one state-handled area.
- [ ] 5. Loading state does not re-trigger on WS ticks (audited per page).
- [ ] 6. All new empty-state sites implemented per the design table.
- [ ] 7. \`pytest tests/\` = 69 passes.

## Test plan
- [x] \`pytest tests/\` green at every commit.
- [ ] **You**: walk every page with no devices connected — confirm each card shows its empty hint; start a session — confirm empty hints clear cleanly. Open a session detail — confirm the page-body loading state appears briefly. Toggle filters on Sessions — confirm filtered-empty state appears.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:**
- Goal (systematic empty + loading rollout) → Tasks 1–8 cover it.
- Non-goals (no errors, no layout, no api.js changes) → enforced in Conventions + per-task scope notes.
- Helper API → Task 1 fully specifies it (signature, modes, JSDoc); Task 2 proves it on 5 sites.
- 10+ new empty-state sites from spec table → Task 3 (5: 3 device cards + 2 log panels), Task 4 (1: quality summary overlay), Task 5 (3: page-body, drift, timeline), Task 6 (2: 2 conn device cards), Task 7 (4: 4 system checks). Total: 15 new sites. (The spec said "10" but enumerated more in the breakdown — the plan covers everything in the spec's table.)
- 3 section-level loading sites → Task 2 Step 5 (Sessions initial), Task 4 (quality summary), Task 5 Step 1+3 (page-body) and Task 5 Step 6 (alignment lazy-load).

**Placeholder scan:** No "TBD" / "implement later" / "appropriate error handling". A few "verify the condition" / "match the existing predicate" notes are intentional — the engineer reads the existing code to find the right field name. That's good engineering, not placeholder.

**DOM-safety:** The helper and every new code example use `textContent`, `createElement`, `replaceChildren`. Existing `.innerHTML` assignments outside this PR's scope (e.g. the rows-present branch of `renderSessionsList`) are noted as out of scope, not migrated.

**Type consistency:** `renderState(slot, kind, opts)` signature identical across all tasks. `kind ∈ {'loading', 'empty', 'clear'}` consistent. `data-state-mode="overlay"` attribute used consistently for overlay slots. `inline: true` opt used consistently for compact tags.

No gaps requiring patches.
