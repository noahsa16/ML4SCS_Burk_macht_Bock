# Dashboard States — Phase 2a (Empty + Loading)

**Date:** 2026-05-11
**Author:** Noah Samel (with Claude)
**Status:** Draft — awaiting approval before implementation planning
**Target branch:** `feature/dashboard-states-phase2a` off `feature/adapt-web-ui`
**Phase:** 2a of 3 (Phase 2b = error states + connectivity edges; Phase 3 = layout + branding)

## Goal

Make every page on the dashboard look intentional in its non-happy states. Apply the existing `.empty-state` editorial pattern systematically to every component that can currently appear blank or half-finished, and add section-level loading indicators where the user currently sees a flash of nothing before data arrives. Output: no page reads as "half-built" in any reachable state.

## Non-goals

- Error states. If `api()` returns 500 or the network dies, the page silently swallows it today; that stays for now. Phase 2b.
- WS-disconnect banners or mid-session connection loss UI. Phase 2b.
- Connectivity edge-case decision trees (pen-without-session, server-down, partial connectivity). Phase 2b.
- Layout changes, new components, branding. Phase 3.
- Changes to `core/api.js`. The fetch helper stays untouched — error pathing is Phase 2b.
- New tests for the helper. The existing HTTP-asset smoke test is sufficient for this PR's surface.

## Approach

One small core helper, applied uniformly. Two discrete state classes:

| State | Trigger | Visual | Where the pattern lives today |
|---|---|---|---|
| **Loading** | Initial fetch in flight, no data yet | Slash glyph with subtle pulse + "Loading X…" title | Sessions table placeholder row (text only, no glyph) |
| **Empty** | No error, no data | Slash glyph + title + hint + optional action | `.chart-canvas-empty`, `.pen-canvas-empty`, sessions filtered-empty, alignment-empty (one-liner) |

Plus one helper-operation, `clear`, that transitions a slot back to its normal data-showing state (removes the overlay or restores original content). **Error** is a third state deferred to Phase 2b.

## Architecture

### The helper

New module `static/js/core/states.js` exporting:

```js
/**
 * Render a state into a slot element. The slot is either a container that
 * gets its content replaced with an .empty-state block, or a positioned
 * overlay sibling (e.g. .chart-canvas-empty) that gets shown/hidden.
 *
 * @param {HTMLElement} slot - the element whose content is being managed
 * @param {'loading' | 'empty' | 'clear'} kind
 * @param {object} [opts]
 * @param {string} [opts.title]  - first line; required for loading/empty
 * @param {string} [opts.hint]   - second line, smaller
 * @param {string} [opts.glyph]  - override the default '/' glyph
 * @param {{ label: string, onClick: () => void }} [opts.action]  - empty only
 */
export function renderState(slot, kind, opts = {}) { ... }
```

The helper writes into the slot via `DOMParser` + `replaceChildren` (same pattern the dashboard bootstrap uses for view partials — keeps the security hook happy and avoids inline `innerHTML = string`).

For overlay-style slots (canvas wrappers), the helper toggles a single class (`.has-data` on the parent) rather than rewriting content. The helper detects this case via a `data-state-mode="overlay"` attribute on the slot.

### Loading-state CSS

`renderState(slot, 'loading', {...})` adds a `.empty-state--loading` modifier class. CSS already has the slash glyph; the modifier adds a subtle pulse animation reusing the existing `@keyframes pulse` from `base.css`:

```css
.empty-state--loading .empty-state-glyph {
  animation: pulse 1.6s ease-in-out infinite;
}
```

That's the entire loading visual difference. The structure is identical to empty — same slash, same title-and-hint layout — only the glyph breathes.

### Page lifecycle integration

Each page module already has `mount` / `onShow` / `onStatus` / `onHide`. The state helper is called from:

- `mount` — initial loading state shown for the page's primary content area, until the first data arrives.
- `onStatus` — when WS tick brings data, the page module decides per-section whether to call `renderState(slot, 'clear')` (data arrived, restore content) or `renderState(slot, 'empty', {...})` (still no data despite payload, e.g. no sessions exist).
- `onShow` — refresh loading state if returning to a page whose data is stale.

**Critical contract**: loading state must NOT re-trigger on subsequent WS ticks. The pattern is "show loading once at mount, transition to data or empty once the first relevant payload arrives, then stay in the data/empty state forever (until hide)". Pages enforce this with a module-private `_hasResolved` flag.

### Where errors fit (preview of 2b)

Phase 2b will add a fourth kind `'error'`. The helper will gain a fourth branch and one extra opts field (`error: { reason, onRetry }`). The migration target for Phase 2a does not need to anticipate this — pages can pass whatever shape they want into a future `'error'` kind without 2a-side changes.

## In scope

### Helper

- **Create**: `static/js/core/states.js`
- **Test entry**: add `/static/js/core/states.js` to the parametrise list in `tests/test_dashboard_static.py`

### Migrations of existing empty-states (5)

Each becomes a `renderState()` call in the relevant page module:

1. `recording.html` chart-canvas-empty (the IMU chart placeholder) → toggled from `pages/recording.js onStatus` via `data-state-mode="overlay"` on the wrap.
2. `recording.html` pen-canvas-empty (same shape, same module).
3. `session-detail.html` alignment-empty (currently a one-liner) → upgraded to the full pattern via `pages/session_detail.js`.
4. `pages/sessions.js renderSessionsList` filtered-empty branch — currently builds the empty-state from a template string; switches to `renderState()`.
5. `sessions.html` initial "Loading sessions…" placeholder row — replaced at mount time by `renderState(sessionsTableSlot, 'loading', { title: 'Loading sessions…' })` from `pages/sessions.js mount()`.

### New empty-state sites (10)

| # | Page | Site | Trigger | Action |
|---|---|---|---|---|
| 1 | Recording | Pen card data rows | `S.lastStatus.pen_connected === false` | Empty hint: "Connect the pen to see live dot data" |
| 2 | Recording | Watch card data rows | watch status `offline` | Empty hint: "Start the watch app to see live IMU data" |
| 3 | Recording | AirPods card data rows | airpods status `offline` | Empty hint: "Connect AirPods to capture head IMU" |
| 4 | Recording | Sample log panel | `S.sampleLog.length === 0` | Empty hint: "Sample stream begins once a session is recording" |
| 5 | Recording | Event log panel | `S.eventLog.length === 0` | Empty hint: "Server and device events will appear here" |
| 6 | Sessions | Quality summary 4-tiles | first paint, before `loadSessions()` resolves | Loading state with title "Loading…" applied to the 4-up |
| 7 | Session Detail | Whole page on initial open | `openSessionDetail(id)` called, before fetch resolves | Loading state covering the page-body |
| 8 | Session Detail | Drift-grid values | session has no overlap data | Empty hint: "Timeline drift can't be computed without overlapping pen+watch data" |
| 9 | Session Detail | Timeline visualisation | streams don't overlap | Empty hint: "No timeline overlap — pen and watch did not record in the same window" |
| 10 | System | Validation-check rows | no live status payload yet | Inline "waiting for status" tag on each row |

### Section-level loading

Three places where the initial fetch is slow enough that a loading state is meaningful:

- Sessions: between `mount()` and the first `loadSessions()` response (~100-300ms on localhost; longer over Cloudflare tunnel).
- Session Detail: between `openSessionDetail(id)` and the `/sessions/:id/...` fetch resolving.
- Alignment lazy-load inside Session Detail: between opening the Alignment details section and the alignment data resolving.

## Out of scope

Everything not listed under In scope. The non-goals section is exhaustive.

## Success criteria

1. `static/js/core/states.js` exists, exports `renderState`. JSDoc covers the four parameter signatures.
2. The parametrise list in `tests/test_dashboard_static.py` includes `/static/js/core/states.js`.
3. Zero inline empty-state template strings remain in the page-module JS. `grep -rE "empty-state-glyph|empty-state-title|empty-state-hint" static/js/pages/` returns zero matches outside of `core/states.js`.
4. Every page module mounts with a loading state for its primary content area (Sessions → table; Session Detail → page body; Recording → device-card hints toggle from data; Connections → device-cards; System → no-op since no primary content fetched).
5. Loading state does not re-render on WS ticks after the first data resolution. Verified by reading each page's `onStatus` body: the loading-state call sites are gated by a `_hasResolved` (or equivalent) flag.
6. Each of the 10 new empty-state sites in the table above is implemented and triggers under the documented condition.
7. `pytest tests/` = 68 passes (the new parametrise row adds a 69th passing case → expect 69 passes).

## Implementation sequencing (high-level — full plan comes next)

Each step is a small, mergeable commit (or short series). The branch can sit at any commit without breaking anything user-facing.

1. **Create the helper.** `core/states.js` with `renderState`. Smoke-test by loading the module in DevTools — calling each branch on a stub div.
2. **Add a state-mode CSS class set.** `.empty-state--loading` modifier with pulse. Other CSS that the helper relies on already exists.
3. **Migrate one existing site as proof** — sessions filtered-empty (it's the simplest container-replace case). Validates the helper API.
4. **Migrate remaining 4 existing sites.** One commit per site.
5. **Add the 10 new sites.** Grouped by page: Recording → Sessions → Session Detail → Connections → System. One commit per page.
6. **Add the 3 section-level loading sites.** Sessions / Session Detail / Alignment.
7. **Audit pass.** Walk every page, confirm no blank flashes, confirm no loading re-triggers, confirm pytest green. Document in PR description.

## Risk register

| Risk | Mitigation |
|---|---|
| Loading-state flash on every WS tick | Module-private `_hasResolved` flag; loading rendered only at mount and cleared after first data arrival |
| Helper API design becomes wrong after 1-2 sites | Migrate the simplest site first (sessions filtered-empty), iterate API before doing the other 14 |
| Empty-state hint copy is inconsistent across sites | Single style guide enforced in the implementation plan: title is the state (e.g. "No pen data"), hint is the action ("Connect the pen to start") — both short, both in sentence case |
| Some empty-state sites have no obvious slot (e.g. health-check rows in System) | Use inline-text fallback via a `.empty-state--inline` modifier rather than the full block; helper handles both modes |
| Initial loading state hides existing content (replace-with-overlay confusion) | Helper uses `data-state-mode` attribute on the slot to choose between `replaceChildren` and `.has-data` toggle |

## Open questions

None blocking. Possible future:

- A small JS test harness for the helper (mock DOM, assert that each kind produces the expected structure). Worth doing if the helper grows beyond Phase 2a's four states.
- Animation polish on state transitions (fade-in/out on loading→data). Out of scope; the existing `.chart-canvas-wrap.has-data` uses `transition: opacity` and works well enough.
