# Dashboard modularization — design

**Date:** 2026-05-11
**Author:** Noah Samel (with Claude)
**Status:** Draft — awaiting approval before implementation planning
**Target branch:** `feature/dashboard-modularization` off `feature/adapt-web-ui`

## Goal

Split the monolithic dashboard (`dashboard.html`, 1572 lines; `static/dashboard.js`, 1964 lines) into per-page modules with a shared core, using native ES modules and HTML/CSS partials. No build tooling. Behavior must be preserved; perceived performance must be equal-or-better than the current `feature/adapt-web-ui` HEAD.

## Non-goals

- URL routing changes, deep-links, history API.
- TypeScript, JSX, bundler, `package.json`, any Node toolchain.
- Visual / layout / copy changes.
- Behavior changes to any panel.
- Server-side changes beyond MIME-type adjustments in `src/server/routes/dashboard.py` if FastAPI's `StaticFiles` defaults are insufficient.
- Any change to the ML pipeline, pen logger, or watch streamer.

## Constraints

- **No build step.** Modules load via `<script type="module">`; FastAPI's existing `StaticFiles` mount serves everything.
- **Pure refactor + small opportunistic fixes only.** Allowed during the refactor: dead-code removal, fixing obviously double-bound listeners or uncleared intervals, `var` → `const`/`let` in moved blocks, restoring lost context with brief comments. Not allowed: feature work, restyling, semantic changes.
- **Performance budget** (vs `feature/adapt-web-ui` HEAD):
  - DOMContentLoaded → first interactive topbar: within 50 ms.
  - Per-tick CPU on the active page: ≤ baseline.
  - Active animation frames, listeners, intervals: ≤ baseline (audited and documented).

## Architecture

### Directory layout

```
static/
  dashboard.js                # ~80-line bootstrap
  js/
    core/
      state.js                # `S` object + getters; single source of live data
      ws.js                   # connectWs, setWsStatus, status dispatch
      router.js               # hash routing, tab switching, page strip
      status_cluster.js       # handleStatus, setStatusCluster, pills/badges
      anim.js                 # setNumberSmooth, _startAnimLoop, skeletons
      api.js                  # api(), downloadDebugPackage
      toast.js                # toast queue + rendering
      theme.js                # setTheme, toggleTheme
      format.js               # all fmt* helpers, statusBadgeClass, scoreBadge
      dom.js                  # esc, _roundRect, small DOM helpers
    pages/
      recording.js
      sessions.js
      session_detail.js
      connections.js
      system.js
  views/
    recording.html
    sessions.html
    session-detail.html
    connections.html
    system.html
  css/
    base.css                  # tokens, typography, layout primitives
    topbar.css
    recording.css
    sessions.css
    session-detail.css
    connections.css
    system.css
```

`dashboard.html` (the shell, formerly 1572 lines) shrinks to ~80 lines: `<head>` with `<link rel="stylesheet">` per CSS file and `<link rel="modulepreload">` for the core import chain; `<body>` containing the inline topbar markup, an empty `<div id="content">`, the toast container, the page-strip element, and one `<script type="module" src="/static/dashboard.js">`.

### Page module contract

Every page module under `static/js/pages/` exports the same four functions:

```js
export function mount(container) { /* one-time DOM wiring; container is `#content` after partial injection */ }
export function onStatus(payload) { /* called on each WS tick, only if this page is active */ }
export function onShow() { /* called when page becomes visible; re-sync from core/state.js */ }
export function onHide() { /* called when leaving page; stop rAF loops, release transient state */ }
```

The bootstrap holds a `Map<pageId, module>` and a `Set<pageId>` of mounted pages. On route change it:

1. Calls `onHide()` on the previous active page (if any).
2. If the target page is not yet mounted: fetches its view partial (cached in-memory after first fetch), injects into `#content`, calls `mount()`, adds to mounted set.
3. Calls `onShow()` on the target page.
4. Updates the active-page reference; subsequent WS ticks dispatch `onStatus` only to the active page.

### State ownership

- `core/state.js` is the only module that mutates the `S` object. It exposes named getters (`getStatus()`, `getSessions()`, `getActiveSession()`, etc.) plus an `updateFromStatus(payload)` mutator called by `core/ws.js` on every tick.
- Page modules read state through getters in `onStatus(payload)` (for the active tick) and `onShow()` (for re-sync on return). They never reach into `S` directly.
- This keeps the existing "global object" mental model while making mutation centralized and grep-able.

### WS dispatch

`core/ws.js` owns the WebSocket connection, reconnection backoff (preserved from current code), and the status loop. On each tick it:

1. Calls `state.updateFromStatus(payload)`.
2. Calls `status_cluster.handleStatus(payload)` (always — topbar is global).
3. Calls the active page's `onStatus(payload)` if defined.

Hidden pages do no work per tick. This is an architectural perf win over the current implementation, where every panel re-renders on every tick regardless of visibility.

## Performance plan

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Module-import waterfall on cold load | `<link rel="modulepreload">` for the core chain in the shell `<head>`, flattening to one effective round trip |
| View-partial fetch latency on first nav | In-memory cache (`Map<pageId, html>`); first nav fetches, subsequent navs are zero-cost |
| CSS FOUC from split files | All CSS loaded eagerly in `<head>` via `<link rel="stylesheet">` — no lazy CSS |
| Double-bound canvas/animation loops on tab switch | `mount-once` guard in bootstrap; pages start rAF loops in `onShow()` and stop them in `onHide()` |
| Hidden pages drift from state | `onShow()` re-syncs from `core/state.js` before becoming visible |

### Budget enforcement

Documented in the PR description before merge:

- DOMContentLoaded → first interactive topbar (Performance panel timestamp): new branch within 50 ms of `feature/adapt-web-ui` HEAD.
- 30 s DevTools Performance recording per tab on both branches: `Long Tasks` count and average frame time tabulated.
- Listener/interval inventory: count of `addEventListener`, `setInterval`, `requestAnimationFrame` registrants on both branches — new branch must be ≤ baseline.

## Migration sequence

Each step is a small, bisectable commit (or short series). The dashboard remains fully functional after every step.

1. **Scaffold directories.** Create `static/js/{core,pages}/`, `static/views/`, `static/css/`. No code moves.
2. **Pure helpers.** Extract `core/format.js`, `core/dom.js`, `core/api.js`. Replace inline definitions with `import`s in `dashboard.js`. Verify in browser.
3. **State.** Extract `core/state.js` (the `S` object and named getters/mutators).
4. **Leaf services.** Extract `core/theme.js`, `core/anim.js`, `core/toast.js`.
5. **Router.** Extract `core/router.js` (hash routing, tab switching, page strip, `closeSessionDetail`).
6. **WS + status cluster.** Extract `core/ws.js` and `core/status_cluster.js`. If `status_cluster.js` exceeds ~400 lines, split off `network_graph.js`.
7. **Pages, in increasing complexity:** System → Connections → Sessions → SessionDetail → Recording. For each page: move JS into `pages/<page>.js`, extract markup into `static/views/<page>.html`, extract page-specific CSS into `static/css/<page>.css`, wire HTML-partial loader. Convert to the `mount`/`onStatus`/`onShow`/`onHide` contract.
8. **Shrink shell.** Reduce `dashboard.html` to the ~80-line shell described above; reduce `static/dashboard.js` to the bootstrap.
9. **Perf audit + cleanup pass.** Run the perf comparison, fix any regressions, document numbers in the PR. Apply any opportunistic fixes surfaced during the refactor (dead code, double-bindings, leaks).

## Testing

- **New** `tests/test_dashboard_static.py` — FastAPI `TestClient` smokes: `GET /` returns the shell; every module path under `/static/js/`, every partial under `/static/views/`, every stylesheet under `/static/css/` returns 200 with the expected content-type. Catches typos in import paths (ES modules fail silently in browsers when a 404 is served as `text/html`).
- **Existing** `pytest tests/` continues to pass without modification.
- **Manual side-by-side.** Two browser windows: `feature/adapt-web-ui` HEAD vs the new branch, against a live session via `scripts/start.sh`. Walk every tab. Trigger: session start/stop, pen connect/disconnect, watch start/stop, theme toggle, session-detail open/close, alignment-plot render, log filtering. Diff visual and console output.
- **Perf comparison.** As above (§ Performance plan → Budget enforcement).

## Open questions

None blocking. Possible future work, explicitly out of scope here:

- Real URL routes (`/sessions/S029`) replacing hash routing.
- Lazy-loading per-page JS modules on first nav (only worth it if cold-load TTI ever regresses).
- A small reactive layer over `core/state.js` if more than a few pages need fine-grained subscriptions.
