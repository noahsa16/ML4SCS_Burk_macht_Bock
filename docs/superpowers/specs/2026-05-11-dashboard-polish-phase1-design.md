# Dashboard Polish — Phase 1 (Audit + Visual Feintuning)

**Date:** 2026-05-11
**Author:** Noah Samel (with Claude)
**Status:** Draft — awaiting approval before implementation planning
**Target branch:** `feature/dashboard-polish-phase1` off `feature/adapt-web-ui` (head `7418898`)
**Phase:** 1 of 3 (Phase 2 = empty/loading/error states; Phase 3 = layout overhauls + branding)

## Goal

Make all 5 dashboard pages feel like one cohesive piece by eliminating token drift, normalising spacing/typography rhythm, ensuring full hover/focus coverage, and applying a curated set of aesthetic refinements that the user approves per-item via the brainstorming Visual Companion. Output: a presentation-ready, screenshot-able dashboard whose existing "editorial-quiet" identity is sharpened, not replaced.

## Non-goals

- Layout changes (component re-composition) — Phase 3.
- New features or components — never as polish.
- Empty / loading / error states — Phase 2.
- Branding, logo, footer, header treatment — Phase 3.
- JavaScript changes. JS stays untouched.
- HTML structure changes, unless a consistency fix requires a class rename.
- New micro-animations beyond hover/focus feedback (no page transitions, no scroll animations, no confetti).
- Mobile / responsive pass. The dashboard is desktop-only and stays that way.

## Constraints

- The existing OKLCH-based token system in `static/css/base.css` is the foundation. Tokens may be **added** (e.g. spacing/type scale primitives) but never replaced without per-item review.
- Light AND dark theme must both be tested at every step. Anything that looks right in one but wrong in the other counts as a regression.
- Each commit must be small enough to bisect a visual regression to a single file or single concern.
- Tests stay green (`pytest tests/` = 68 passes). They cover HTTP-asset smokes only — they do not catch visual issues, so manual side-by-side comparison is part of every commit.

## Approach

Two passes, in order:

### Pass A — Structural Audit (mechanical, no taste)

A code-pattern audit of all 7 CSS files (`base`, `topbar`, `recording`, `sessions`, `session-detail`, `connections`, `system`) and 5 view partials. Findings written to `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md` as a tabular report. Categories:

- **Token drift** — hardcoded `font-size`, `padding`, `margin`, `gap`, `border-radius`, `color` values that should resolve to a token.
- **Type-scale wildgrowth** — every distinct `font-size` value across all CSS. Target: ≤ 6 sizes.
- **Spacing-rhythm breaks** — padding/margin values that don't fall on a 4/8/12/16/24/32/48 scale.
- **Hover/focus coverage** — every `button`, `select`, `input`, `.tab`, `.card`, `.row`, and other interactive element must have `:hover` AND `:focus-visible` rules.
- **Transition inconsistency** — every transition must use a shared curve + one of two duration tokens (fast/slow). Catalogue every existing transition for conformance.
- **Border-radius drift** — any `border-radius` value not one of `--radius-xs/sm/md/pill`.
- **Off-palette colors** — any direct color value (hex, `rgb()`, `rgba()`) not from the OKLCH token set.

The audit doc is the first commit on the branch. Noah reviews it and marks items to drop before any code change lands.

### Pass B — Aesthetic Refinements (per-item, with the user)

Once Pass A's mechanical fixes are committed, the Visual Companion is opened. Per page (System → Connections → Sessions → Session Detail → Recording), Claude pushes a mockup screen showing:

- Current state (left)
- Proposed refinement (right)
- 1–3 sentences explaining the choice

Noah responds: **Yes** / **No** / **Adjust**. Approved items become a single commit per page. Rejected items are dropped silently; adjusted items get a v2 mockup before any code lands.

The companion is the gate: no aesthetic change is implemented without explicit per-item approval.

## In scope

- All 7 CSS files under `static/css/`
- All 5 view partials under `static/views/`
- `dashboard.html` (shell)
- Both light and dark theme tokens in `base.css`
- The new audit document under `docs/superpowers/audits/`
- A new screenshot directory `docs/screenshots/polish-phase1/` (Noah captures, since Claude cannot run a browser)

## Out of scope

(See Non-goals above. Repeated here for the implementation plan to enforce.)

## Success criteria

Objectively verifiable at the end of the PR:

1. **No hardcoded font-sizes.** All `font-size` declarations either reference a `--text-*` token or are explicitly listed as exceptions with an inline `/* Why: ... */` comment.
2. **No hardcoded spacing.** All `padding`, `margin`, `gap`, `top`/`right`/`bottom`/`left` (when used as offsets) reference a `--space-*` token or have an exception comment.
3. **Every interactive element has visible `:hover` and `:focus-visible` states.** Audited by a grep + manual cross-check.
4. **Transitions normalised.** All `transition` declarations use one of two shared curves and one of two durations (`--ease-default`, `--dur-fast` ≈ 140ms, `--dur-slow` ≈ 240ms). Exceptions documented inline.
5. **Colors on-palette.** No `#hex`, no `rgb()`, no `rgba()` outside the OKLCH token set. Exceptions documented.
6. **Border-radius on-token.** Every `border-radius` is one of `--radius-xs/sm/md/pill`. Exceptions documented.
7. **Per-page refinements implemented.** Each refinement that Noah marked **Yes** in Pass B is in the final branch. Each commit message references the refinement description.
8. **Light + dark screenshots delivered.** 10 PNGs in `docs/screenshots/polish-phase1/` (5 pages × 2 themes).
9. **Tests green.** `pytest tests/` = 68 pass.

## Implementation sequencing

Each step is a small, bisectable commit (or short series).

1. **Audit document.** Write `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md`. No code touched. Noah reviews and prunes findings.
2. **Token primitives.** Add `--space-1` through `--space-8`, `--text-xs/sm/base/md/lg/xl`, `--ease-default`, `--dur-fast`, `--dur-slow` to `:root` in `base.css`. Existing tokens stay. Add any other missing primitives surfaced by the audit.
3. **`base.css` token migration.** Hardcoded values → tokens. Add any missing global `:hover` / `:focus-visible` defaults.
4. **`topbar.css` token migration.** Same pattern.
5. **`recording.css` token migration.**
6. **`sessions.css` token migration.**
7. **`session-detail.css` token migration.**
8. **`connections.css` token migration.**
9. **`system.css` token migration.**
10. **Refinements: System page.** Open Visual Companion, propose 1–2 refinements, Noah approves, single commit.
11. **Refinements: Connections page.**
12. **Refinements: Sessions page.**
13. **Refinements: Session Detail page.**
14. **Refinements: Recording page.**
15. **Screenshots.** Noah captures 10 PNGs (5 pages × light/dark) and commits them to `docs/screenshots/polish-phase1/`. Claude cannot do this.
16. **Success-criteria audit.** Walk through criteria 1–9 from this spec, document conformance in the PR description.

After step 9 the dashboard should already feel more cohesive even with no aesthetic changes — that's the leverage of the mechanical pass. Steps 10–14 add the layer of intentional taste on top.

## Risk register

| Risk | Mitigation |
|---|---|
| Token migration silently shifts visual rendering by a pixel or two and Noah dislikes the result | Each per-file migration commit is reviewed side-by-side before the next one lands. Any unintended shift is rolled back to the previous commit; the token in question is then reviewed |
| Dark theme breaks because Pass A focused on light theme by default | Every migration commit ships both theme renderings; Noah confirms both look right before approving |
| Claude's "assertive" aesthetic proposals don't match Noah's taste | Per-item Yes/No/Adjust gate via Visual Companion. No aesthetic change lands without explicit approval |
| The audit doc is huge and Noah's pruning becomes a chore | The audit is structured as one table per category, sortable by file. Noah marks rows to skip; he doesn't have to explain why |
| A consistency fix requires a class rename that touches JS | Out of scope per § Non-goals. If a fix can't be done without touching JS, it gets deferred to Phase 3 |
| Visual Companion server times out between mockups | The server auto-restarts; mockups persist in `.superpowers/brainstorm/` because we'll start with `--project-dir` |

## Open questions

None blocking. Possible future considerations, explicitly out of scope here:

- A pre-commit lint rule that rejects new hardcoded `px` values outside the token set. Would prevent token drift from re-accumulating. Belongs to a future tooling pass, not this PR.
- A Storybook-equivalent for visually testing components in isolation. Would speed up Phase 2 (empty/loading/error states) but is more infrastructure than this project warrants.
