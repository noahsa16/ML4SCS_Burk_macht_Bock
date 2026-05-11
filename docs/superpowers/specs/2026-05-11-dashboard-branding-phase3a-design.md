# Dashboard Branding + Onboarding — Phase 3a

**Date:** 2026-05-11
**Author:** Noah Samel (with Claude)
**Status:** Draft — awaiting approval before implementation planning
**Target branch:** `feature/dashboard-branding-phase3a` off `feature/adapt-web-ui`
**Phase:** 3a of 3 (3b = layout overhauls; deferred)

## Goal

Add the missing identity layer to the dashboard: a persistent footer with team/semester/uni info, and a first-run welcome card on the Recording page. Both are additive — no existing component changes layout or visual treatment.

## Non-goals

- Brand wordmark changes. The existing `.brand` ("Burk macht Bock" + "/" + hover-tooltip) stays untouched.
- Layout overhauls of any page (Phase 3b).
- A multi-step onboarding wizard. The welcome card is one static block.
- Print stylesheet / "report mode" view (was an option earlier; cut by Noah).
- New JS architecture (no module added; recording.js gets two new functions).
- Mobile / responsive treatment.
- Changes to `dashboard.html` shell structure beyond adding the footer element.

## Architecture

### Footer

New global element appended to `<body>` after `<main>`. Persistent across page navigation (lives outside the page-content `<main>`).

Content (left side · right side):
- **Left**: team byline · project byline. `Noah Samel · Ben Kriegsmann · Tajuddin Snasni` then a `·` separator then `ML4SCS · Leuphana University · SS 26`.
- **Right**: `github` text link to the repo. Optional commit-short version label (cut if it bloats the design — Noah decides during implementation).

Treatment:
- `--text-xs` font-size, `--text3` colour.
- `border-top: 1px solid var(--border)`.
- Sits at bottom of viewport — `body` already uses flex column; `<main>` gets `flex: 1`, footer is the second flex item.
- Does not occupy fixed height; auto-sizes to content with `--space-3` vertical padding.
- Both themes render via existing tokens. No new CSS variables.

### Welcome card

New static HTML block inside `recording.html`, hidden by default (`style="display:none"`). `pages/recording.js` toggles its visibility from `onStatus(payload)` and `mount()`.

Visibility predicate (all must be true for the card to show):
- `S.allSessions?.length === 0` — no sessions exist on disk (loadSessions has completed and returned empty).
- `!s.pen_connected` — pen offline.
- Watch offline: same predicate as device-card empty state (Phase 2a uses `S.watchConnected` derived from `watchUiOnline`).
- AirPods offline: same predicate as airpods device-card empty state.
- `!localStorage.getItem('welcomeDismissed')` — not previously dismissed.

When any condition flips false, the card hides immediately. The card does not re-appear automatically — it only shows on a truly fresh dashboard.

Content (concrete copy in implementation; this is the structure):
- Title: "Welcome to ML4SCS"
- Subtitle: "Writing activity detection via Apple Watch IMU"
- Three numbered steps as a flex row:
  1. **Connect the pen** — "Tap the pen, then click Connect on the Smart Pen card."
  2. **Start the Watch app** — "Open WatchStreamer on your Apple Watch."
  3. **Press START** — "Hit the START button when both devices show as connected."
- One dismiss link below: `[ dismiss this welcome ]` — sets `welcomeDismissed` in localStorage.

CSS in `static/css/recording.css` (extends existing). One new class `.welcome-card` plus child classes for steps.

## In scope

- New: `static/css/footer.css` for the footer styling (or extend `base.css` — implementation chooses).
- Modify: `dashboard.html` — add `<footer>` element after `<main>`. Adjust `body` / `main` CSS to flex-column with `main` as `flex: 1`.
- Modify: `static/css/base.css` — adjust body/main rules if needed.
- Modify: `static/views/recording.html` — add `.welcome-card` block (hidden) at top of `.rec-grid` or as a sibling above it.
- Modify: `static/css/recording.css` — add welcome-card styling.
- Modify: `static/js/pages/recording.js` — add `_updateWelcomeCard(s)` helper, call from `onStatus(s)` and `mount()`. Add dismiss button click handler in `mount()`.
- Modify: `tests/test_dashboard_static.py` — add `/static/css/footer.css` to parametrise list if a separate file is used.

## Out of scope

See Non-goals. Restated: no brand changes, no layout overhauls, no multi-step wizard, no print stylesheet, no new core JS module.

## Success criteria

1. Footer is visible on every page (Recording, Sessions, Session Detail, Connections, System). Renders with both light and dark theme correctly.
2. Footer does not overlap content; if a page's content is taller than the viewport, scrolling reveals content above the footer cleanly.
3. Welcome card is visible on a fresh dashboard: zero sessions on disk, no pen, no watch, no airpods. On the Recording tab.
4. Welcome card disappears the moment any of: a device connects, a session is created, or the user clicks dismiss.
5. Once dismissed (via localStorage), the welcome card stays hidden across reloads, even if the state still matches the predicate.
6. Both themes render welcome card correctly.
7. `pytest tests/` = 69 (or +1 if a new static asset is added).
8. No JS changes outside `static/js/pages/recording.js`.

## Risk register

| Risk | Mitigation |
|---|---|
| Existing `body { overflow: hidden }` (set in base.css) clips the footer | Verify on read; either change to `overflow: hidden` on `<main>` only and `body` flex-column, or remove the body-level overflow. Tested with both themes. |
| Footer width competes with `<main>` content max-width | Footer spans full viewport width to match the topbar's full-width treatment. Inner content centred to match the page-content max-width. |
| Welcome card flashes briefly during initial load | Card starts `display: none` in static HTML. `recording.js mount()` reads state once and explicitly shows-or-hides; never the inverse. State `S.allSessions` is null until `loadSessions()` resolves, so predicate fails (length check on null is falsy) and card stays hidden until state is known. Acceptable. |
| localStorage `welcomeDismissed` flag persists across sessions / new users on same machine | Single-user dev tool. Acceptable. |
| Welcome card visible during recording → user expectation broken (it shouldn't show with a session active) | Predicate includes `S.allSessions?.length === 0` — once any session has ever been recorded, the card stays hidden forever. Even after dismiss-flag cleared, an empty-sessions state would re-show — but that's only achievable via deleting sessions.csv manually. Acceptable. |

## Open questions

None blocking. Possible future:

- A "tour" mode that highlights specific dashboard regions in sequence. Out of scope; this is a single static welcome.
- Version label in the footer (commit-short). Implementation may include if trivially derivable from `window.__buildInfo` or similar — but no server endpoint exists today, so likely cut.
- Replacing the brand-tooltip with a more discoverable surface (e.g. an info icon in the topbar). Cut from this phase; the tooltip works.
