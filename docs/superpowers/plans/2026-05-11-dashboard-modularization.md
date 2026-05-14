# Dashboard Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split monolithic `dashboard.html` (1572 LOC) and `static/dashboard.js` (1964 LOC) into per-page native ES modules with HTML/CSS partials, preserving behavior and performance.

**Architecture:** Per-page modules under `static/js/pages/` with a shared `static/js/core/` for cross-cutting concerns. View partials fetched once and cached. WS dispatch only invokes `onStatus` on the active page (hidden pages do no per-tick work). No build tooling.

**Tech Stack:** Vanilla JS (ES modules), HTML, CSS, FastAPI `StaticFiles`, `pytest` + `httpx.TestClient`.

**Spec:** `docs/superpowers/specs/2026-05-11-dashboard-modularization-design.md`

---

## Conventions used in this plan

- All file paths are relative to the project root.
- All line ranges refer to `static/dashboard.js` at the **base commit** of the new branch (`feature/adapt-web-ui` HEAD = `d0caae7` after the spec commit). If a previous task shifts those line numbers, use the function/symbol name to locate the block — the line numbers are a hint, not a hard reference.
- "Move block" means: cut the lines from `static/dashboard.js`, paste verbatim into the target file, prepend `export` to each top-level `function`/`const`/`let`/`async function` declaration, then add `import { ... } from '/static/js/...';` lines at the top of `static/dashboard.js` covering every name the moved block exposed.
- After each task, the dashboard must still load and work end-to-end in a browser. Manual smoke: open `http://localhost:8000`, click every tab, start/stop a session, toggle theme.
- Commit after every passing task. Use the message template shown in the task's commit step.

---

## Partial injection helper (used in Tasks 9–14)

View partials are first-party HTML served from our own `StaticFiles` mount. We still parse them via `DOMParser` rather than assignment from a string — this keeps the code free of the in-tree `innerHTML`-from-string anti-pattern (which would be flagged by the project's security hook).

Use this exact helper wherever the plan says "inject the partial":

```js
function injectPartial(slot, html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  slot.replaceChildren(...parsed.body.childNodes);
}
```

In Task 9 it lives temporarily inside `static/dashboard.js`. In Task 14 it moves into the bootstrap proper.

---

## Task 1: Create branch, scaffold directories, write static-asset smoke test

**Files:**
- Create: `tests/test_dashboard_static.py`
- Create directories: `static/js/core/`, `static/js/pages/`, `static/views/`, `static/css/`

- [ ] **Step 1: Create the new branch**

```bash
git checkout -b feature/dashboard-modularization
```

Expected: `Switched to a new branch 'feature/dashboard-modularization'`.

- [ ] **Step 2: Create directories with `.gitkeep` placeholders**

```bash
mkdir -p static/js/core static/js/pages static/views static/css
touch static/js/core/.gitkeep static/js/pages/.gitkeep static/views/.gitkeep static/css/.gitkeep
```

- [ ] **Step 3: Write the failing static-asset smoke test**

Create `tests/test_dashboard_static.py`:

```python
"""HTTP smokes that every dashboard static asset is served correctly.

ES modules fail silently in browsers when a 404 is served as text/html —
this test exists to make those failures loud during CI.
"""
from fastapi.testclient import TestClient
import pytest

from server import app

client = TestClient(app)


def test_root_serves_dashboard_shell():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "id=\"content\"" in r.text


def test_bootstrap_module_served_as_js():
    r = client.get("/static/dashboard.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


@pytest.mark.parametrize(
    "path",
    [
        # Filled in as modules/views/stylesheets are created. Keep alphabetised.
    ],
)
def test_static_assets_served(path):
    r = client.get(path)
    assert r.status_code == 200
    if path.endswith(".js"):
        assert "javascript" in r.headers["content-type"]
    elif path.endswith(".css"):
        assert "css" in r.headers["content-type"]
    elif path.endswith(".html"):
        assert "html" in r.headers["content-type"]
```

- [ ] **Step 4: Run test to verify**

Run: `pytest tests/test_dashboard_static.py -v`
Expected: 2 PASSED (root + bootstrap), 0 parametrised cases (empty list).

- [ ] **Step 5: Commit**

```bash
git add tests/test_dashboard_static.py static/js static/views static/css
git commit -m "refactor(ui): scaffold module dirs + static-asset smoke test"
```

---

## Task 2: Extract `core/format.js` (pure formatters)

**Files:**
- Create: `static/js/core/format.js`
- Modify: `static/dashboard.js`, `dashboard.html` (one-time `type="module"` change), `tests/test_dashboard_static.py`

**Block to move:** All `fmt*` helpers + status helpers — `fmtDuration`, `fmtHz`, `fmtNum`, `fmtClockGap`, `fmtMs`, `fmtSec`, `fmtAgo`, `fmtClock`, `fmtCommand`, `fmtUptime`, `statusBadgeClass`, `scoreBadge`, `scoreTooltip`, `syncDiagnostic`, `_fmtStripDate` (line 46–48). In the base file these are approximately lines 1814–1934 plus the `_fmtStripDate` block near the top.

- [ ] **Step 1: Add the failing test row**

Modify `tests/test_dashboard_static.py`: in the parametrise list, add `"/static/js/core/format.js"`.

Run: `pytest tests/test_dashboard_static.py -v`
Expected: the new parametrised case FAILS with 404.

- [ ] **Step 2: Create `static/js/core/format.js` with the moved code**

Cut the functions listed above from `static/dashboard.js`. Paste into `static/js/core/format.js`. Prepend `export` to each top-level declaration. The file should contain only these functions — no other code.

- [ ] **Step 3: Add the `import` to `static/dashboard.js`**

At the top of `static/dashboard.js`, add:

```js
import {
  fmtDuration, fmtHz, fmtNum, fmtClockGap, fmtMs, fmtSec, fmtAgo,
  fmtClock, fmtCommand, fmtUptime,
  statusBadgeClass, scoreBadge, scoreTooltip, syncDiagnostic,
  _fmtStripDate,
} from '/static/js/core/format.js';
```

- [ ] **Step 4: Convert `dashboard.html`'s script tag to a module**

In `dashboard.html`, find `<script src="/static/dashboard.js"></script>` and change to:

```html
<script type="module" src="/static/dashboard.js"></script>
```

(This is a one-time change; subsequent tasks rely on `type="module"` being set.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_dashboard_static.py -v && pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Manual smoke**

Start the server (`uvicorn server:app --port 8000`), open `http://localhost:8000`, confirm:
- Dashboard loads with no console errors.
- A session row (Sessions tab) shows durations and Hz values formatted as before.
- Status cluster in the topbar shows formatted ages ("12s ago").

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/format.js"
```

---

## Task 3: Extract `core/dom.js` (esc, escAttr, _roundRect)

**Files:**
- Create: `static/js/core/dom.js`
- Modify: `static/dashboard.js`, `tests/test_dashboard_static.py`

**Block to move:** `esc` (≈1936), `escAttr` (≈1942), `_roundRect` (≈1506).

- [ ] **Step 1: Failing test**

Add `"/static/js/core/dom.js"` to the parametrise list. Run tests; new case FAILS.

- [ ] **Step 2: Create `static/js/core/dom.js`**

Move the three functions verbatim, `export` each.

- [ ] **Step 3: Add import to `static/dashboard.js`**

```js
import { esc, escAttr, _roundRect } from '/static/js/core/dom.js';
```

- [ ] **Step 4: Run tests + manual smoke**

`pytest tests/test_dashboard_static.py -v`. Open dashboard; check that issue codes, session descriptions, and the alignment timeline (rounded rectangles) still render.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/dom.js"
```

---

## Task 4: Extract `core/api.js` (fetch helper + debug download)

**Files:**
- Create: `static/js/core/api.js`
- Modify: `static/dashboard.js`, `tests/test_dashboard_static.py`

**Block to move:** `api(path, method, body)` (≈1784) and `downloadDebugPackage()` (≈1798).

- [ ] **Step 1: Failing test** — add `/static/js/core/api.js` to parametrise list; run; FAILS.

- [ ] **Step 2: Create `static/js/core/api.js`** — move both functions, `export` each.

- [ ] **Step 3: Add import to `static/dashboard.js`**

```js
import { api, downloadDebugPackage } from '/static/js/core/api.js';
```

- [ ] **Step 4: Run tests + manual smoke** — Sessions tab still loads (uses `api()`); "⤓ debug package" link still downloads.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/api.js"
```

---

## Task 5: Extract `core/state.js` (the `S` object)

**Files:**
- Create: `static/js/core/state.js`
- Modify: `static/dashboard.js`, `tests/test_dashboard_static.py`

**Block to move:** The entire `const S = { ... }` block at lines 4–45.

- [ ] **Step 1: Failing test** — add `/static/js/core/state.js`; run; FAILS.

- [ ] **Step 2: Create `static/js/core/state.js`**

```js
// Single source of live data. Pages must NOT mutate S directly — use the
// exported mutators below.

export const S = { /* ... moved block ... */ };

export function updateFromStatus(payload) {
  // Placeholder that mirrors the existing in-place mutation pattern used by
  // handleStatus(). Gains real responsibility in Task 8.
}

export function getActiveSession() { return S.activeSession || null; }
export function getTheme() { return S.theme; }
export function getLogRows() { return S.logRows; }
```

(`S` stays exported so existing call sites that read `S.foo` continue to work during the migration. The contract tightens in Task 8.)

- [ ] **Step 3: Add import to `static/dashboard.js`**

```js
import { S, getActiveSession, getTheme, getLogRows } from '/static/js/core/state.js';
```

- [ ] **Step 4: Run tests + manual smoke** — full dashboard load, theme toggle, log-rows control, session detail open/close.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/state.js"
```

---

## Task 6: Extract `core/theme.js`, `core/anim.js`, `core/toast.js`

**Files:**
- Create: `static/js/core/theme.js`, `static/js/core/anim.js`, `static/js/core/toast.js`
- Modify: `static/dashboard.js`, `tests/test_dashboard_static.py`

**Blocks to move:**
- `theme.js`: `setTheme` (≈1757), `toggleTheme` (≈1770).
- `anim.js`: `SKEL_MIN_MS` (≈161), `setNumberSmooth` (≈163), `_startAnimLoop` (≈214).
- `toast.js`: `toastTimer` (≈1946), `toast` (≈1947).

- [ ] **Step 1: Failing tests** — add three rows to parametrise list. Run; three cases FAIL.

- [ ] **Step 2: Create the three files**

For each: move the block(s) listed above, prepend `export` to each top-level declaration. `toast.js`'s internal `toastTimer` stays module-private (no `export`); only `toast` is exported.

- [ ] **Step 3: Add imports to `static/dashboard.js`**

```js
import { setTheme, toggleTheme } from '/static/js/core/theme.js';
import { setNumberSmooth, _startAnimLoop, SKEL_MIN_MS } from '/static/js/core/anim.js';
import { toast } from '/static/js/core/toast.js';
```

- [ ] **Step 4: Run tests + manual smoke** — theme toggle works and persists across refresh; counters animate (Recording tab); call `toast('hi')` in DevTools console and confirm the toast appears.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/{theme,anim,toast}.js"
```

---

## Task 7: Extract `core/router.js` (hash routing, tab switching, page strip)

**Files:**
- Create: `static/js/core/router.js`
- Modify: `static/dashboard.js`, `tests/test_dashboard_static.py`

**Block to move:** `_routeFromHash` (≈84), `closeSessionDetail` (≈108), `updateTabIndicator` (≈120), `updatePageStrip` (≈49), `goHome` (≈575). Also the `hashchange` and DOMContentLoaded wiring that drives them — find these in the `// INIT` section near the bottom of `static/dashboard.js`.

- [ ] **Step 1: Failing test** — add `/static/js/core/router.js`; FAILS.

- [ ] **Step 2: Create `static/js/core/router.js`**

Move the functions listed. Keep the `window.addEventListener('hashchange', ...)` registration inside the module (it fires at module-load time — same contract as today). Export `_routeFromHash`, `closeSessionDetail`, `updateTabIndicator`, `updatePageStrip`, `goHome`.

- [ ] **Step 3: Add import to `static/dashboard.js`**

```js
import {
  _routeFromHash, closeSessionDetail, updateTabIndicator,
  updatePageStrip, goHome,
} from '/static/js/core/router.js';
```

- [ ] **Step 4: Manual smoke** — tab switching works; hash deep-link (`http://localhost:8000/#sessions`) lands on Sessions; session detail opens, back-out closes it.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/router.js"
```

---

## Task 8: Extract `core/ws.js` + `core/status_cluster.js`

**Files:**
- Create: `static/js/core/ws.js`, `static/js/core/status_cluster.js`
- Modify: `static/dashboard.js`, `static/js/core/state.js`, `tests/test_dashboard_static.py`

**Blocks to move:**
- `ws.js`: `connectWs` (≈536), `setWsStatus` (≈560). Reconnection logic + backoff stays as-is.
- `status_cluster.js`: `handleStatus` (≈603), `setStatusCluster` (≈806), `setPill` (≈799), `setBadge` (≈853), `setHealth` (≈859), `setNetworkNode` (≈584), `setNetworkLine` (≈593), `updateChart` (≈353), `updatePenCanvas` (≈391), `clearPenPreview` (≈431), `drawPenCanvas` (≈439). **Note:** `updateChart` / pen-canvas helpers technically belong to Recording (Task 13); they live in `status_cluster.js` for this task only to avoid a flailing intermediate state. Same for `setNetworkNode` / `setNetworkLine`, which Task 10 moves to Connections.

- [ ] **Step 1: Failing tests** — add `/static/js/core/ws.js` and `/static/js/core/status_cluster.js`. Two FAILs.

- [ ] **Step 2: Create `static/js/core/ws.js`**

Move `connectWs` and `setWsStatus`. Add imports it needs:

```js
import { handleStatus } from '/static/js/core/status_cluster.js';
import { updateFromStatus } from '/static/js/core/state.js';
```

In the WebSocket `onmessage` handler, wrap the existing `handleStatus(msg)` call with a preceding `updateFromStatus(msg);` so state ownership starts moving to `state.js`.

- [ ] **Step 3: Create `static/js/core/status_cluster.js`**

Move every function listed. Export each. The DOM-rendering portion of `handleStatus` stays here; only the `S.xxx = ...` assignments at its top will migrate in the next step.

- [ ] **Step 4: Tighten `core/state.js`'s `updateFromStatus`**

Replace the placeholder body with the actual state-mutation lines that `handleStatus` was doing inline (look for assignments to `S.xxx` near the top of `handleStatus`'s body — these are the lines that set things like `S.lastStatus`, `S.activeSession`, `S.chart`, etc.). **Move** those lines from `handleStatus` (in `status_cluster.js`) into `updateFromStatus` (in `state.js`). Leave the DOM-rendering portion in `handleStatus`.

- [ ] **Step 5: Add imports to `static/dashboard.js`**

```js
import { connectWs, setWsStatus } from '/static/js/core/ws.js';
import {
  handleStatus, setStatusCluster, setPill, setBadge, setHealth,
  setNetworkNode, setNetworkLine,
  updateChart, updatePenCanvas, clearPenPreview, drawPenCanvas,
} from '/static/js/core/status_cluster.js';
```

- [ ] **Step 6: Run tests + manual smoke**

Run `pytest tests/test_dashboard_static.py -v && pytest tests/ -q`. All PASS.

Manual: start the server; topbar status cluster cycles `connecting → connected`; with a live session, pen dot count climbs, watch chart updates, pen preview canvas draws.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract core/{ws,status_cluster}.js + tighten state ownership"
```

---

## Page-module contract (used in Tasks 9–13)

Every page module exports exactly four functions. Use this exact skeleton for each new page:

```js
// static/js/pages/<page>.js
let _mounted = false;
let _container = null;

export function mount(container) {
  if (_mounted) return;
  _container = container;
  // one-time DOM wiring: query selectors, attach listeners that should
  // never be re-added (they survive onShow/onHide cycles)
  _mounted = true;
}

export function onStatus(payload) {
  // called per WS tick, only while this page is active
}

export function onShow() {
  // called when this page becomes the active page; re-sync from state
}

export function onHide() {
  // called when leaving this page; stop rAF loops, clear timers
}
```

A page is created with three siblings: `static/js/pages/<page>.js`, `static/views/<page>.html`, `static/css/<page>.css`. The bootstrap (built in Task 14) wires them together.

**Intermediate state for Tasks 9–13:** until the bootstrap exists, the page module is imported by `static/dashboard.js`, the partial is fetched + injected via `injectPartial(...)` (the helper at the top of this plan) once at startup, `mount(slot)` is called, and `onStatus` is called unconditionally from `handleStatus`. The router's existing tab-switch logic remains unchanged. Task 14 replaces this with the real active-page dispatcher.

---

## Task 9: Extract System page

**Files:**
- Create: `static/js/pages/system.js`, `static/views/system.html`, `static/css/system.css`
- Modify: `dashboard.html`, `static/dashboard.js`, `static/js/core/status_cluster.js`, `tests/test_dashboard_static.py`

**Why System first:** it's the smallest and least-coupled page.

- [ ] **Step 1: Failing tests** — add three rows to parametrise list (`pages/system.js`, `views/system.html`, `css/system.css`).

- [ ] **Step 2: Inventory the System page**

In `dashboard.html`, find `<div class="page" id="page-system">` (≈line 1460) and read its entire markup block. In `static/dashboard.js`, find every function that touches `#page-system` DOM nodes or is called from System-page event handlers. In the `<style>` block of `dashboard.html`, find selectors scoped to `#page-system` or its child classes.

- [ ] **Step 3: Move markup**

Cut the entire `<div class="page" id="page-system"> ... </div>` block out of `dashboard.html`. Paste into `static/views/system.html` as the file's full contents (the `<div>` is the partial root).

In `dashboard.html`, replace the cut block with: `<div class="page" id="page-system" data-view="system"></div>` (the bootstrap will fetch+inject the partial; for this task we inject eagerly at startup — see Step 6).

- [ ] **Step 4: Move CSS**

Cut every selector targeting `#page-system` or its descendants out of `dashboard.html`'s `<style>` block. Paste into `static/css/system.css`. Add to `dashboard.html`'s `<head>`:

```html
<link rel="stylesheet" href="/static/css/system.css">
```

- [ ] **Step 5: Create `static/js/pages/system.js` using the page skeleton**

Use the skeleton from the "Page-module contract" section. Move the System-page-specific functions into the module (`updateChart` does **not** belong here — it belongs to Recording, see Task 13). Put their bodies inside or called from `mount`/`onStatus`/`onShow`/`onHide` as appropriate:
- `mount`: attach click/change handlers that exist for the lifetime of the page.
- `onStatus`: any per-tick render call that's specific to System (e.g. system-section uptimes if rendered there).
- `onShow` / `onHide`: empty for System unless there's a rAF loop (unlikely).

- [ ] **Step 6: Wire it into `static/dashboard.js`**

Add at the top of `static/dashboard.js`, just after the existing imports:

```js
import * as systemPage from '/static/js/pages/system.js';

function injectPartial(slot, html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  slot.replaceChildren(...parsed.body.childNodes);
}
```

Near the bottom (`// INIT` section), add:

```js
// Temporary eager mount — replaced by Task 14 bootstrap
fetch('/static/views/system.html')
  .then(r => r.text())
  .then(html => {
    const slot = document.getElementById('page-system');
    injectPartial(slot, html);
    systemPage.mount(slot);
  });
```

In `static/js/core/status_cluster.js`, add at the top:

```js
import * as systemPage from '/static/js/pages/system.js';
```

At the end of `handleStatus(s)`, add:

```js
systemPage.onStatus(s);
```

- [ ] **Step 7: Run tests + manual smoke**

`pytest tests/test_dashboard_static.py -v` (new cases PASS) and `pytest tests/ -q` (all green). Open the dashboard, click the System tab — looks and behaves identically to before.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract System page module"
```

---

## Task 10: Extract Connections page

**Files:**
- Create: `static/js/pages/connections.js`, `static/views/connections.html`, `static/css/connections.css`
- Modify: `dashboard.html`, `static/dashboard.js`, `static/js/core/status_cluster.js`, `tests/test_dashboard_static.py`

**Functions belonging to Connections:** `updateConnectionsPage` (≈1714). Also **move `setNetworkNode` and `setNetworkLine` out of `status_cluster.js` into `pages/connections.js`** since they only render the Connections-tab graph. Update `status_cluster.js` to no longer export them, and remove them from `static/dashboard.js`'s status-cluster import block.

- [ ] **Step 1: Failing tests** — add three rows.

- [ ] **Step 2: Move markup** — `<div class="page" id="page-connections">` block at ≈1337 from `dashboard.html` to `static/views/connections.html`. Leave behind `<div class="page" id="page-connections" data-view="connections"></div>`.

- [ ] **Step 3: Move CSS** — selectors targeting `#page-connections` and `.net-*` classes into `static/css/connections.css`. Add `<link rel="stylesheet" href="/static/css/connections.css">` to `dashboard.html`'s head.

- [ ] **Step 4: Move JS** — `updateConnectionsPage`, `setNetworkNode`, `setNetworkLine` into `static/js/pages/connections.js`, using the page skeleton:
- `mount`: query selectors, no listeners needed.
- `onStatus(payload)`: call the body of `updateConnectionsPage` here.
- `onShow`: also call the update once on entry, to refresh after returning from another tab.

Add the eager fetch + inject + mount block to `static/dashboard.js` and the `connectionsPage.onStatus(s)` call to the end of `handleStatus` in `status_cluster.js` (same pattern as Task 9 Step 6).

- [ ] **Step 5: Run tests + manual smoke** — Connections tab: node dots and link labels still update.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract Connections page module"
```

---

## Task 11: Extract Sessions page

**Files:**
- Create: `static/js/pages/sessions.js`, `static/views/sessions.html`, `static/css/sessions.css`
- Modify: `dashboard.html`, `static/dashboard.js`, `static/js/core/status_cluster.js`, `tests/test_dashboard_static.py`

**Functions belonging to Sessions:** `VERDICT_TRAINABLE`/`VERDICT_USABLE`/`VERDICT_SKIP` (≈960–962), `computeVerdict` (≈964), `FILTERS_KEY`/`DEFAULT_FILTERS` (≈982–983), `loadFilters` (≈985), `saveFilters` (≈992), `resetFilters` (≈995), `loadSessions` (≈1134), `_matchesFilters` (≈1185), `applyFilters` (≈1217), `_sigmaPill` (≈1233), `renderSessionsList` (≈1244), `renderQualitySummary` (≈1279).

- [ ] **Step 1: Failing tests** — add three rows.

- [ ] **Step 2: Move markup** — `<div class="page" id="page-sessions">` block (≈1205) into `static/views/sessions.html`.

- [ ] **Step 3: Move CSS** — selectors for `#page-sessions`, `.session-row`, `.filters-*`, the verdict pill classes — into `static/css/sessions.css`. Add `<link>` to head.

- [ ] **Step 4: Move JS into `static/js/pages/sessions.js`** using the page skeleton:
- `mount`: wire filter input listeners, reset button click, the "load sessions" trigger.
- `onShow`: call `loadSessions()` to refresh.
- `onStatus(payload)`: usually a no-op. If `payload` indicates a session has just stopped, call `loadSessions()` (preserve current behavior by reading `handleStatus`'s pre-refactor logic — look for any branch there that currently refreshes the sessions list).
- `onHide`: empty.

Add the eager fetch + inject + mount + handleStatus dispatch.

- [ ] **Step 5: Run tests + manual smoke** — Sessions tab: filters work, list renders, clicking a row opens detail.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract Sessions page module"
```

---

## Task 12: Extract Session Detail page

**Files:**
- Create: `static/js/pages/session_detail.js`, `static/views/session-detail.html`, `static/css/session-detail.css`
- Modify: `dashboard.html`, `static/dashboard.js`, `static/js/core/status_cluster.js`, `static/js/pages/sessions.js`, `tests/test_dashboard_static.py`

**Functions belonging to Session Detail:** `openSessionDetail` (≈997), `_renderDetailHeader` (≈1046), `_renderDetailStreams` (≈1088), `_renderDetailIssues` (≈1113), `renderAlignment` (≈1298), `_destroyAlignCharts` (≈1363), `_drawAlignVarianceCurve` (≈1368), `_drawAlignTimeline` (≈1516), `renderSessionValidation` (≈1656), `renderTimeline` (≈1672), `pct` (≈1705), `_alignFmtDelta` (≈1290).

**Special handling for `onHide`:** Session Detail has rAF / canvas state in `_drawAlignVarianceCurve` and `_drawAlignTimeline`. The existing `_destroyAlignCharts` function does cleanup — **call it in `onHide`**. This is the headline perf-win mechanism for this page (the heaviest one).

- [ ] **Step 1: Failing tests** — add three rows.

- [ ] **Step 2: Move markup** — `<div class="page" id="page-session-detail">` block (≈1257) into `static/views/session-detail.html`.

- [ ] **Step 3: Move CSS** — selectors for `#page-session-detail`, alignment canvas wrappers, validation timeline, issue list scoped to this page — into `static/css/session-detail.css`. Add `<link>` to head.

- [ ] **Step 4: Move JS into `static/js/pages/session_detail.js`** using the page skeleton:
- `mount`: wire close-button, copy-link buttons, alignment-plot canvas refs.
- `onShow`: a no-op. Session Detail is opened explicitly via `openSessionDetail(id)`, not by tab click.
- `onStatus`: no-op for now. (If a future requirement is to refresh the header when the displayed session is the live one, add it then.)
- `onHide`: call `_destroyAlignCharts()`; null out any retained DOM/canvas references.

`openSessionDetail` must be exported. In `static/js/pages/sessions.js`, replace any call to the global `openSessionDetail` with:

```js
import { openSessionDetail } from '/static/js/pages/session_detail.js';
```

(Add this import at the top of `sessions.js`.)

Add the eager fetch + inject + mount block to `static/dashboard.js` and the `sessionDetailPage.onStatus(s)` call to `handleStatus`.

- [ ] **Step 5: Run tests + manual smoke** — click a session row → detail opens with alignment plots; close → returns to list; reopen a different session — no console errors, alignment canvases render fresh.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract Session Detail page module"
```

---

## Task 13: Extract Recording page

**Files:**
- Create: `static/js/pages/recording.js`, `static/views/recording.html`, `static/css/recording.css`
- Modify: `dashboard.html`, `static/dashboard.js`, `static/js/core/status_cluster.js`, `tests/test_dashboard_static.py`

**Functions belonging to Recording:** `toggleSession` (≈880), `runStartPreflight` (≈905), `showPreflightResult` (≈922), `penConnect` (≈936), `penDisconnect` (≈941), `watchCmd` (≈945), `airpodsCmd` (≈949), `startTimer` (≈868), `toggleCardDetails` (≈580), `renderLogs` (≈1724), `renderSampleRow` (≈1737), `renderEventRow` (≈1745), `clearVisualLogs` (≈1751), `setLogRows` (≈1774).

**Also moved out of `core/status_cluster.js` into `pages/recording.js`** (per Task 8's note): `updateChart` (≈353), `updatePenCanvas` (≈391), `clearPenPreview` (≈431), `drawPenCanvas` (≈439). Remove their exports from `status_cluster.js` and remove them from `static/dashboard.js`'s status-cluster import block.

- [ ] **Step 1: Failing tests** — add three rows.

- [ ] **Step 2: Move markup** — `<div class="page" id="page-recording">` block (find it just after `#topbar` closes; should be around line 1000-1200) into `static/views/recording.html`.

- [ ] **Step 3: Move CSS** — selectors for recording controls, timer, pen-preview canvas, chart, logs panel — into `static/css/recording.css`. Add `<link>` to head.

- [ ] **Step 4: Move JS into `static/js/pages/recording.js`** using the page skeleton:
- `mount`: attach all click/keyboard handlers (start/stop button, pen connect, watch cmds, airpods cmds, logs filter, log-rows control). Initialise canvas refs and the timer DOM element.
- `onShow`: refresh the timer display; restart any rAF loop for the pen canvas if a session is active.
- `onStatus(payload)`: call into the chart updater, pen-canvas updater, log renderers, timer tick.
- `onHide`: cancel rAF loops, but **do not** stop the timer — a running session continues regardless of which tab is active (preserve existing behavior).

- [ ] **Step 5: Run tests + manual smoke** — start a real session; watch chart and pen canvas update; stop session; logs panel still shows events; switch tabs while session runs and confirm the timer keeps advancing.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(ui): extract Recording page module"
```

---

## Task 14: Slim the shell + real bootstrap with active-page dispatch + perf audit

**Files:**
- Modify: `dashboard.html` (drop to ~80 lines)
- Modify: `static/dashboard.js` (rewrite to bootstrap form)
- Modify: `static/js/core/status_cluster.js` (remove per-page imports and direct `onStatus` calls; introduce dispatcher hook)

- [ ] **Step 1: Add the dispatcher hook to `core/status_cluster.js`**

At the top of `static/js/core/status_cluster.js`:

```js
let _activePageDispatch = () => {};
export function setActivePageDispatcher(fn) { _activePageDispatch = fn; }
```

At the end of `handleStatus(s)`, replace the per-page calls (`systemPage.onStatus(s)`, `connectionsPage.onStatus(s)`, `sessionsPage.onStatus(s)`, `sessionDetailPage.onStatus(s)`, `recordingPage.onStatus(s)` — added during Tasks 9–13) with the single line:

```js
_activePageDispatch(s);
```

Remove the `import * as <page>Page from ...` lines that were added to `status_cluster.js` in Tasks 9–13.

- [ ] **Step 2: Rewrite `static/dashboard.js` as the bootstrap**

Replace the entire file with:

```js
import * as state from '/static/js/core/state.js';
import { connectWs } from '/static/js/core/ws.js';
import { setTheme } from '/static/js/core/theme.js';
import { _startAnimLoop } from '/static/js/core/anim.js';
import { api } from '/static/js/core/api.js';
import { handleStatus, setActivePageDispatcher } from '/static/js/core/status_cluster.js';
import { _routeFromHash } from '/static/js/core/router.js';

import * as recording      from '/static/js/pages/recording.js';
import * as sessions       from '/static/js/pages/sessions.js';
import * as sessionDetail  from '/static/js/pages/session_detail.js';
import * as connections    from '/static/js/pages/connections.js';
import * as system         from '/static/js/pages/system.js';

const pages = {
  recording, sessions, 'session-detail': sessionDetail, connections, system,
};

const partialCache = new Map();
const mounted = new Set();
let activePage = null;

function injectPartial(slot, html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  slot.replaceChildren(...parsed.body.childNodes);
}

async function loadPartial(pageId) {
  if (partialCache.has(pageId)) return partialCache.get(pageId);
  const r = await fetch(`/static/views/${pageId}.html`);
  const html = await r.text();
  partialCache.set(pageId, html);
  return html;
}

async function showPage(pageId) {
  if (activePage && pages[activePage]?.onHide) pages[activePage].onHide();

  const slot = document.getElementById(`page-${pageId}`);
  if (!mounted.has(pageId)) {
    injectPartial(slot, await loadPartial(pageId));
    pages[pageId].mount?.(slot);
    mounted.add(pageId);
  }
  if (pages[pageId].onShow) pages[pageId].onShow();
  activePage = pageId;
}

// Tab buttons → hash; the hashchange listener does the rest
document.querySelectorAll('.tab[data-page]').forEach(btn => {
  btn.addEventListener('click', () => {
    location.hash = btn.dataset.page;
  });
});

window.addEventListener('hashchange', () => {
  const pageId = _routeFromHash() || 'recording';
  if (pages[pageId]) showPage(pageId);
});

// WS tick → active page only
setActivePageDispatcher(payload => {
  if (activePage && pages[activePage]?.onStatus) pages[activePage].onStatus(payload);
});

// Init
document.getElementById('timer').textContent = '00:00:00';
setTheme(state.getTheme());
api('/status').then(s => { if (s) handleStatus({ type: 'status', ...s, chart: [] }); });
connectWs();
_startAnimLoop();
showPage(_routeFromHash() || 'recording');
```

- [ ] **Step 3: Slim `dashboard.html`**

Strip out everything that has now been moved:
- The remaining inline `<style>` content (everything per-page should already be gone — anything left should be base/topbar tokens; move that to `static/css/base.css` and `static/css/topbar.css`).
- The `<div class="page" ...>` blocks (now in `static/views/*.html`). Keep the empty `data-view`-bearing div placeholders that Tasks 9–13 left behind.

Add base/topbar stylesheet links and `<link rel="modulepreload">` for the core import chain to the `<head>`:

```html
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/topbar.css">
<link rel="stylesheet" href="/static/css/recording.css">
<link rel="stylesheet" href="/static/css/sessions.css">
<link rel="stylesheet" href="/static/css/session-detail.css">
<link rel="stylesheet" href="/static/css/connections.css">
<link rel="stylesheet" href="/static/css/system.css">

<link rel="modulepreload" href="/static/dashboard.js">
<link rel="modulepreload" href="/static/js/core/state.js">
<link rel="modulepreload" href="/static/js/core/ws.js">
<link rel="modulepreload" href="/static/js/core/status_cluster.js">
<link rel="modulepreload" href="/static/js/core/router.js">
<link rel="modulepreload" href="/static/js/core/format.js">
<link rel="modulepreload" href="/static/js/core/dom.js">
<link rel="modulepreload" href="/static/js/core/api.js">
<link rel="modulepreload" href="/static/js/core/theme.js">
<link rel="modulepreload" href="/static/js/core/anim.js">
<link rel="modulepreload" href="/static/js/core/toast.js">
```

(Adding `base.css` and `topbar.css` paths to the parametrise list in `tests/test_dashboard_static.py` at this step.)

Target shell size: ~80 lines.

- [ ] **Step 4: Run tests + full manual smoke**

`pytest tests/test_dashboard_static.py -v && pytest tests/ -q` — all PASS.

Full UI walk against a live session:
- Page load: no console errors; topbar interactive immediately.
- Each tab switches with the partial fetched on first visit (verify in DevTools Network: one `*.html` request per page, only the first time).
- Recording: start session, watch chart + pen canvas update.
- Switch to Sessions while recording: chart-update calls should stop (pause execution in DevTools and confirm `requestAnimationFrame` is no longer being scheduled for the pen canvas).
- Switch back to Recording: chart resumes.
- Session detail open/close: alignment plots draw; `_destroyAlignCharts` runs on close.
- Theme toggle persists across refresh.

- [ ] **Step 5: Perf audit**

In Chrome DevTools (Performance panel), against both `feature/adapt-web-ui` HEAD and the new branch:

1. **Cold-load:** hard refresh, record from start until topbar is interactive. Note `DOMContentLoaded` timestamp and the time of the first `setStatusCluster` paint.
2. **Per-tab idle:** with a live session running, record 30 s on each tab. Note `Long Tasks` count and average frame time.
3. **Listener inventory:** in the DevTools console run

   ```js
   getEventListeners(document.body).length
   ```

   on each branch (after dashboard fully loaded). New branch must be ≤ baseline.

Record numbers in a temporary file `perf-audit.txt` in the project root (do not commit it; it goes into the PR description).

Budget check (from spec):
- DOMContentLoaded → first interactive topbar: within 50 ms of baseline.
- Per-tick CPU on active page: ≤ baseline.
- Listeners + intervals + rAF registrants: ≤ baseline.

If any budget is violated, the most likely causes are: (a) modulepreload tags are missing or wrong, (b) a page's `onHide` failed to cancel an rAF, (c) a listener got double-bound because `mount` was called twice. Fix the cause; do not move on with a budget violation.

- [ ] **Step 6: Apply opportunistic small fixes**

If the perf audit or the inventory pass surfaced any of these, fix them now:
- Dead functions (no callers after migration). Delete.
- Double-bound listeners (e.g. a `mount` re-runs on `onShow` by mistake). Verify the `_mounted` guard.
- Intervals never cleared. Add cleanup in `onHide` or at module level.

Each fix gets its own micro-commit, e.g. `fix(ui): clear pen-canvas rAF on Recording onHide`.

- [ ] **Step 7: Commit the bootstrap + shell slim**

```bash
git add -A
git commit -m "refactor(ui): slim shell + bootstrap with active-page dispatch"
```

- [ ] **Step 8: Open PR with perf numbers**

```bash
git push -u origin feature/dashboard-modularization
gh pr create --title "Dashboard modularization (per-page ES modules + HTML/CSS partials)" --body "$(cat <<'EOF'
## Summary
- Splits `dashboard.html` (1572 LOC) and `static/dashboard.js` (1964 LOC) into per-page ES modules under `static/js/{core,pages}/`, HTML partials in `static/views/`, and CSS partials in `static/css/`.
- No build tooling; native modules served by FastAPI's existing `StaticFiles`.
- Active-page dispatch: hidden pages do no work per WS tick.

## Spec
`docs/superpowers/specs/2026-05-11-dashboard-modularization-design.md`

## Performance
<paste perf-audit.txt numbers here — TTI delta, Long Tasks count per tab, listener count>

## Test plan
- [x] `pytest tests/` green (incl. new `test_dashboard_static.py`)
- [x] Manual side-by-side vs `feature/adapt-web-ui` HEAD against a live session — every tab, session start/stop, pen connect, session detail open/close, theme toggle.
- [x] Perf audit recorded.
EOF
)"
```

---

## Self-review

**Spec coverage:**
- Goal (modularize JS + CSS + HTML) → Tasks 2–13 cover JS, Tasks 9–13 cover CSS + HTML partials.
- Non-goals (no routing change, no build tooling, no visual change) → Plan only edits the listed files; no `package.json`, no new routes, no styling changes.
- Performance budget → Task 14 Step 5 explicitly measures TTI, per-tick CPU, and listener inventory against the budget.
- Page-module contract → Skeleton defined in the inline section before Task 9; reused in Tasks 9–13.
- Migration sequence (spec § Migration sequence, 9 steps) → Tasks 1–14 follow it (the spec's "step 9: perf audit + cleanup" maps to Task 14 steps 5–6).
- Testing (static-asset smoke test) → Task 1 creates it; every subsequent task extends it.

**Placeholder scan:** Checked for `TBD`, `TODO`, `appropriate error handling`, `similar to Task N`, "implement later", "fill in details". The plan contains none. Two intentional hand-offs are documented (the "this lives in `status_cluster.js` for now, moved in Task 13" note in Task 8; the "placeholder body" comment in Task 5 Step 2 that Task 8 Step 4 fills in). Both name the resolving task explicitly.

**Type/name consistency:** Page-module contract uses `mount(container)`, `onStatus(payload)`, `onShow()`, `onHide()` — same names in every page task (9–13) and in the Task-14 bootstrap. `setActivePageDispatcher` defined in Task 14 Step 1 and called from the bootstrap in Step 2 — consistent signature. `_destroyAlignCharts` referenced in Task 12 matches the existing name in `dashboard.js` (≈line 1363). `injectPartial` helper defined once in the conventions section, used identically in Tasks 9–13 and in the final bootstrap (Task 14 Step 2).

No gaps requiring patches.
