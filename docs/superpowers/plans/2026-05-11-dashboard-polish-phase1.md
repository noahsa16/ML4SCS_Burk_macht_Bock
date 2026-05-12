# Dashboard Polish — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit and polish the dashboard's 7 CSS files + 5 view partials, eliminating token drift and applying per-page aesthetic refinements approved by the user via the Visual Companion. Output: a presentation-ready, screenshot-able dashboard whose existing "editorial-quiet" identity is sharpened.

**Architecture:** Two passes: (A) mechanical structural audit producing a findings document, followed by per-file token migration; (B) per-page aesthetic refinements gated by per-item user approval via the brainstorming Visual Companion. JS untouched. Light + dark theme both verified at every step.

**Tech Stack:** Vanilla CSS with OKLCH custom properties, IBM Plex Mono/Sans, no preprocessor, no build step.

**Spec:** `docs/superpowers/specs/2026-05-11-dashboard-polish-phase1-design.md`

---

## Conventions

- All paths relative to project root `/Users/noahsamel/PycharmProjects/ML4SCS_Burk_macht_Bock`.
- Base commit: `29de3c8` on `feature/adapt-web-ui` (spec commit). New branch: `feature/dashboard-polish-phase1`.
- After each task, dashboard must still render correctly. Manual smoke: open `http://localhost:8000`, walk every tab, toggle theme. Static-asset HTTP smoke test `pytest tests/` = 68 pass at every commit.
- Both light AND dark theme must be visually confirmed for each migration commit. Anything that looks right in one but wrong in the other counts as a regression and must be fixed before moving on.
- Commit messages use `polish(ui): ...` prefix to distinguish from refactor commits.

---

## Reality check — what's already present and what's missing

Before the plan: a quick survey to anchor numbers.

**Already in `static/css/base.css` `:root`:**
- Colors: `--bg`, `--surface`, `--surface2`, `--sidebar`, `--sidebar2`, `--border`, `--border2`, `--text`, `--text2`, `--text3`, `--accent`, `--accent-h`, `--green`, `--red`, `--yellow` (full light/dark variants).
- Fonts: `--mono`, `--sans`.
- Radius: `--radius-xs` (4px), `--radius-sm` (6px), `--radius-md` (10px), `--radius-pill` (999px).

**Missing tokens (to be added in Task 2):**
- Spacing scale.
- Type scale.
- Transition durations + easing.

**Surveyed drift (from initial grep):**
- 17 distinct `font-size` values across all CSS — far above the ≤ 6 target.
- Transition durations: 0.08s, 0.1s, 0.12s, 0.15s, 0.2s, 0.3s — must collapse to 2 values.
- One `border-radius: 2px` stray; the rest use tokens (good).
- All `transition` curves are `ease` (no `cubic-bezier`, no inconsistency in curves).

The audit task (Task 1) will produce the full list. These numbers are sanity-checks, not the audit itself.

---

## Task 1: Create branch + write the audit document

**Files:**
- Create: `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md`

**Why this task exists:** Mechanical fixes are wasted if we don't first know which fixes are needed. The audit is the artifact that drives Tasks 3–9. Noah reviews it and can drop rows.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feature/dashboard-polish-phase1
```

Expected: `Switched to a new branch 'feature/dashboard-polish-phase1'`.

- [ ] **Step 2: Generate the raw audit data**

Run each of these and collect the output. The audit doc compiles them into structured tables.

```bash
# 1. All distinct font-size values per file
grep -nH -oE "font-size:[^;]+;" static/css/*.css

# 2. All distinct padding/margin/gap values per file
grep -nHE "(padding|margin|gap):" static/css/*.css

# 3. All transition declarations per file
grep -nH -oE "transition:[^;]+;" static/css/*.css

# 4. All border-radius declarations per file (only values not using --radius-* tokens)
grep -nHE "border-radius:" static/css/*.css | grep -v "var(--radius"

# 5. Hardcoded colors (anything that's not var())
grep -nHE "#[0-9a-fA-F]{3,8}\b|rgba?\(" static/css/*.css

# 6. Hover/focus coverage — every interactive selector
grep -nHE "^\s*\.?(btn|button|tab|card|chip|row|select|input)" static/css/*.css | head -60

# 7. :hover and :focus-visible rule presence per file
for f in static/css/*.css; do echo "=== $f ==="; grep -cE ":hover|:focus-visible" "$f"; done
```

- [ ] **Step 3: Write the audit doc**

Create `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md` with this structure:

```markdown
# Dashboard Polish Phase 1 — Structural Audit

**Date:** 2026-05-11
**Base commit:** 29de3c8
**Scope:** 7 CSS files in `static/css/` + 5 view partials in `static/views/`.

This is a code-pattern audit, not a visual review. Every finding here
has an objective fix (a token to use, a missing rule to add). Noah can
mark rows to skip with "× skip" in the Status column.

---

## 1. Type-scale wildgrowth

Distinct font-size values present in the codebase today:

| Value | Files | Status | Proposed token |
|---|---|---|---|
| 10px   | <files>  |   | `--text-xs` ? |
| 10.5px | <files>  |   | merge into `--text-xs` |
| 11px   | <files>  |   | merge into `--text-xs` |
| 11.5px | <files>  |   | merge into `--text-xs` |
| 12px   | <files>  |   | `--text-sm` |
| 12.5px | <files>  |   | merge into `--text-sm` |
| 13px   | <files>  |   | merge into `--text-sm` |
| 13.5px | <files>  |   | merge into `--text-sm` |
| 14px   | <files>  |   | `--text-base` |
| 15px   | <files>  |   | merge into `--text-base` |
| 18px   | <files>  |   | `--text-md` |
| 19px   | <files>  |   | merge into `--text-md` |
| 20px   | <files>  |   | merge into `--text-md` |
| 22px   | <files>  |   | `--text-lg` |
| 28px   | <files>  |   | `--text-xl` |
| 32px   | <files>  |   | merge into `--text-xl` |
| 38px   | <files>  |   | merge into `--text-xl` |

**Target scale (6 sizes):** `--text-xs` 11px, `--text-sm` 12px,
`--text-base` 14px, `--text-md` 18px, `--text-lg` 22px, `--text-xl` 32px.

The collapse from 17 → 6 follows a roughly modular scale (≈1.25 ratio
between adjacent steps from base upward, slightly compressed below).
Noah can override any merge by writing the target value in the Status
column.

---

## 2. Spacing-rhythm breaks

Distinct padding/margin/gap values not on a 4/8/12/16/24/32/48/64 scale.

| File | Line | Property | Value | Proposed |
|---|---|---|---|---|
| <fill from grep output> | | | | |

**Target scale (8 steps):** `--space-1` 4px, `--space-2` 8px,
`--space-3` 12px, `--space-4` 16px, `--space-5` 24px, `--space-6` 32px,
`--space-7` 48px, `--space-8` 64px.

---

## 3. Transition inconsistency

| File | Line | Declaration | Proposed |
|---|---|---|---|
| <fill from grep output> | | | `transition: <props> var(--dur-fast) var(--ease-default)` |

**Target tokens:** `--dur-fast` 140ms, `--dur-slow` 240ms,
`--ease-default` `cubic-bezier(0.2, 0.6, 0.2, 1)`.

Rationale for collapsing 6 durations → 2: most current durations (0.1,
0.12, 0.15) are "snap-to-state" feedback (hover, focus) — those go to
`--dur-fast`. The 0.2 and 0.3 values are skeleton-shimmer-adjacent
"settle" feel — those go to `--dur-slow`.

---

## 4. Border-radius drift

| File | Line | Value | Proposed |
|---|---|---|---|
| <fill from grep output> | | | one of `--radius-xs/sm/md/pill` |

Exception: `border-radius: 50%` for dot indicators and circles stays as
is (geometric necessity, not a token miss).

---

## 5. Off-palette colors

| File | Line | Hardcoded color | Proposed |
|---|---|---|---|
| <fill from grep output> | | | nearest `--<token>` or new token |

Common exception: `transparent`, `currentColor`. Those stay.

---

## 6. Hover / Focus-visible coverage

Interactive selectors lacking `:hover` and/or `:focus-visible`.

| Selector | File | Has :hover | Has :focus-visible | Action |
|---|---|---|---|---|
| .btn       | base.css? | ? | ? | add if missing |
| .btn-sm    | | | | |
| .btn-primary | | | | |
| .tab       | topbar.css | | | |
| .card      | base.css | | | |
| .session-row | sessions.css | | | |
| .filter input | sessions.css | | | |
| .session-row select | sessions.css | | | |
| <add others surfaced by grep> | | | | |

A click-able element WITHOUT both states is a finding.

---

## Status legend
- ✓ apply — fix this in the migration pass
- × skip — leave as-is; Noah's call
- ⤸ defer — flag for Phase 2 or 3
- ✎ override — Noah wrote a different target value
```

- [ ] **Step 4: Fill in the audit tables**

Run the grep commands from Step 2 and populate the actual `<files>` and `<fill from grep output>` placeholders. Don't leave any placeholder text.

For Section 1 (Type-scale): under "Files", list which CSS files contain that font-size value (e.g. "sessions.css, recording.css").

For Sections 2, 3, 4, 5: each row is one finding. Use the format `file.css:LINE`.

For Section 6: enumerate the interactive selectors found in Step 2 grep #6. For each, check the file for the presence of a `:hover` and `:focus-visible` rule (search for `<selector>:hover` and `<selector>:focus-visible`). Fill the columns.

- [ ] **Step 5: Pause for Noah review**

Open the audit doc. Tell Noah:

> "Audit doc written to `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md`. Review the rows and mark anything to skip (× skip) or override (✎ override with new target). The migration tasks (3–9) will only act on rows you didn't mark skip."

Wait for explicit "go" before continuing.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md
git commit -m "polish(ui): phase 1 structural audit document"
```

---

## Task 2: Add token primitives to `base.css` `:root`

**Files:**
- Modify: `static/css/base.css` (lines 1–35 area, the `:root` and `body[data-theme="dark"]` blocks)

**Why this task is small and standalone:** the migration tasks (3–9) all *use* these tokens. Defining them in one commit lets every subsequent commit reference them without ambiguity. Adding only tokens (no usage) cannot break rendering.

- [ ] **Step 1: Verify spec → token mapping**

The token additions and their values are fixed in the spec. Confirm them by re-reading section 1 (Type-scale) and section 4 (Border-radius drift) of the audit document. If Noah marked any target value as ✎ override, use his value instead of the default.

Default token values (from spec):

```
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 24px;
--space-6: 32px;
--space-7: 48px;
--space-8: 64px;
--text-xs: 11px;
--text-sm: 12px;
--text-base: 14px;
--text-md: 18px;
--text-lg: 22px;
--text-xl: 32px;
--dur-fast: 140ms;
--dur-slow: 240ms;
--ease-default: cubic-bezier(0.2, 0.6, 0.2, 1);
```

- [ ] **Step 2: Add tokens to `:root` block in `base.css`**

In `static/css/base.css`, find the `:root {` block (starts around line 2). After the last existing token (`--radius-pill: 999px;`) and before the closing `}`, insert:

```css
  /* Spacing scale */
  --space-1:   4px;
  --space-2:   8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  24px;
  --space-6:  32px;
  --space-7:  48px;
  --space-8:  64px;

  /* Type scale */
  --text-xs:   11px;
  --text-sm:   12px;
  --text-base: 14px;
  --text-md:   18px;
  --text-lg:   22px;
  --text-xl:   32px;

  /* Motion */
  --dur-fast:  140ms;
  --dur-slow:  240ms;
  --ease-default: cubic-bezier(0.2, 0.6, 0.2, 1);
```

The dark-theme block (`body[data-theme="dark"] {`) does NOT need these tokens — spacing, type, and motion are theme-invariant.

- [ ] **Step 3: Verify nothing visually changed**

These tokens are defined but not yet used by any selector. Visual rendering must be identical to base commit. Open the dashboard in both themes, walk every tab, confirm no visible change.

Run: `pytest tests/ -q`
Expected: 68 passed.

- [ ] **Step 4: Commit**

```bash
git add static/css/base.css
git commit -m "polish(ui): add spacing, type, motion token primitives"
```

---

## Tasks 3–9: Per-file token migration

**Shared pattern for these 7 tasks.** Each task migrates one CSS file. Per file:

1. Open `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md`. Filter findings to rows whose `File` column matches the current task's file AND whose `Status` is NOT marked × skip.

2. Apply each finding in this order, one CSS rule at a time:
   - **Section 1 findings** (font-size) → replace hardcoded `font-size: Xpx` with `font-size: var(--text-<size>)`.
   - **Section 2 findings** (spacing) → replace hardcoded padding/margin/gap with `var(--space-<n>)`.
   - **Section 3 findings** (transitions) → replace `transition: <props> 0.Xs ease` with `transition: <props> var(--dur-fast) var(--ease-default)` (or `--dur-slow` if the original was 0.2–0.3s).
   - **Section 4 findings** (border-radius) → replace stray values with the closest `--radius-*` token.
   - **Section 5 findings** (off-palette colors) → replace with the nearest existing color token, OR if no good match, surface to Noah for a new token decision.
   - **Section 6 findings** (missing hover/focus) → add the missing `:hover` and/or `:focus-visible` rule using a consistent pattern (see hover-pattern below).

3. After every edit batch (≈ 5 findings, no more), visually verify in browser. Switch theme. Walk through any page that uses the file's selectors.

4. Run `pytest tests/ -q` (must be 68 passed).

5. Commit with message `polish(ui): migrate <file>.css to design tokens`.

**Standard hover/focus pattern for interactive elements (use when adding missing rules):**

```css
.foo {
  /* ...existing rules... */
  transition: background var(--dur-fast) var(--ease-default),
              border-color var(--dur-fast) var(--ease-default),
              color var(--dur-fast) var(--ease-default);
}
.foo:hover {
  background: var(--surface2);
  border-color: var(--border2);
}
.foo:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

Adjust the specific properties per element (e.g. a card might use `box-shadow` for hover, a pill might use `transform: translateY(-1px)`). The contract is: a consistent visual response, and `focus-visible` always uses the outline pattern above unless the element has a stronger reason (e.g. an `<input>` already has its own focus styling).

---

### Task 3: Migrate `base.css`

**Files:** `static/css/base.css`

Apply the Tasks-3–9 pattern to `base.css`. This is the foundation file — get it right first. Special considerations:

- `base.css` is loaded first; tokens defined here are available everywhere.
- The body, scrollbar, skeleton, and `.card`/`.btn` base classes live here. Hover/focus defaults for `.btn`, `.btn-sm`, `.btn-primary`, `.btn-outline`, `.btn-green`, `.btn-red` should be present if not already.
- `tabular-nums` and font-feature-settings on `body` stay as-is.

- [ ] **Step 1: Apply audit findings for `base.css`**

Walk through the audit doc, filter rows where `File` = `base.css`, apply each. Use the standard hover/focus pattern from the Tasks 3–9 preamble for missing-state findings.

- [ ] **Step 2: Visual smoke**

Open dashboard in both themes. Specifically check: buttons (all variants), cards, pills, skeleton loaders, scrollbar. Verify no visible regression.

- [ ] **Step 3: Tests + commit**

```bash
pytest tests/ -q  # expect 68 passed
git add static/css/base.css
git commit -m "polish(ui): migrate base.css to design tokens"
```

---

### Task 4: Migrate `topbar.css`

**Files:** `static/css/topbar.css`

Same pattern. Focus selectors: `#topbar`, `.brand`, `.tabs`, `.tab`, `.tab.active`, `.tab-indicator`, `.status-cluster`, `.status-cluster-dots`, `.status-dot`, `.theme-toggle`, `.page-strip`.

The status-cluster button is the most-visible interactive element on the page — its hover/focus behaviour must feel responsive but not jumpy.

- [ ] **Step 1: Apply audit findings for `topbar.css`**
- [ ] **Step 2: Visual smoke (every page, theme toggle works)**
- [ ] **Step 3: `pytest tests/ -q`, commit `polish(ui): migrate topbar.css to design tokens`**

---

### Task 5: Migrate `recording.css`

**Files:** `static/css/recording.css`

Largest of the page-CSS files (187 lines). Focus selectors: session control, timer, device cards, pen-canvas, IMU chart, logs panel.

- [ ] **Step 1: Apply audit findings for `recording.css`**
- [ ] **Step 2: Visual smoke — start a session, watch the chart + pen-canvas + logs render**
- [ ] **Step 3: `pytest tests/ -q`, commit `polish(ui): migrate recording.css to design tokens`**

---

### Task 6: Migrate `sessions.css`

**Files:** `static/css/sessions.css`

Focus selectors: `.session-row`, `.session-row:hover`, filter inputs (`.filters input`, `.filters select`), reset button, verdict pills, summary tiles.

The filter inputs are the most likely place for missing focus-visible states — verify carefully.

- [ ] **Step 1: Apply audit findings for `sessions.css`**
- [ ] **Step 2: Visual smoke — filters work, row hover/click**
- [ ] **Step 3: `pytest tests/ -q`, commit `polish(ui): migrate sessions.css to design tokens`**

---

### Task 7: Migrate `session-detail.css`

**Files:** `static/css/session-detail.css`

Focus selectors: `.session-detail-header`, `.detail-section`, `.alignment-*`, `.timeline-*`, `.verdict-badge`, `.issue-chip`, `.drift-box`, validation timeline.

- [ ] **Step 1: Apply audit findings for `session-detail.css`**
- [ ] **Step 2: Visual smoke — open a session detail, alignment plots render, timeline renders**
- [ ] **Step 3: `pytest tests/ -q`, commit `polish(ui): migrate session-detail.css to design tokens`**

---

### Task 8: Migrate `connections.css`

**Files:** `static/css/connections.css`

Smaller file (66 lines). Focus selectors: `.uptime-bar`, `.conn-grid`, `.network-map`, `.net-node`, `.net-line`, endpoint list rows.

- [ ] **Step 1: Apply audit findings for `connections.css`**
- [ ] **Step 2: Visual smoke — Connections tab renders, node/line states update on session change**
- [ ] **Step 3: `pytest tests/ -q`, commit `polish(ui): migrate connections.css to design tokens`**

---

### Task 9: Migrate `system.css`

**Files:** `static/css/system.css`

Smallest file (25 lines). Focus selectors: `.settings-grid`, `.setting-row`, `.setting-title`, `.setting-help`, `.schema-table`, `.tag`, `.tag-*`.

- [ ] **Step 1: Apply audit findings for `system.css`**
- [ ] **Step 2: Visual smoke — System tab renders, theme select + log rows select have focus states**
- [ ] **Step 3: `pytest tests/ -q`, commit `polish(ui): migrate system.css to design tokens`**

---

## Pass B preamble — Visual Companion workflow for refinements

Tasks 10–14 each follow this pattern. Re-read here, don't skim:

1. **Start the Visual Companion server** (once at the beginning of Task 10, reused for Tasks 11–14):

```bash
~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/brainstorming/scripts/start-server.sh \
  --project-dir /Users/noahsamel/PycharmProjects/ML4SCS_Burk_macht_Bock
```

Capture the returned JSON: `screen_dir`, `state_dir`, `url`. Tell Noah the URL.

If the server is already running (e.g. mid-task), check `$state_dir/server-info` — if it exists, server is alive; if missing or `server-stopped` is present, restart.

Reminder: add `.superpowers/` to `.gitignore` if not already there.

2. **For each page**, write a fresh HTML fragment to `$screen_dir/<page>-refinements.html` showing:
   - Current state on the left (small mockup of the page area you're proposing to change — use real labels/colours where possible)
   - Proposed refinement on the right
   - 1–3 sentence rationale below
   - Two clickable buttons: `data-choice="yes"` (Approve) and `data-choice="no"` (Reject). For adjust, Noah uses the terminal.
   - Multi-select container if proposing more than one refinement on the same page.

3. **Tell Noah:** "Visual Companion: <page> refinements at <url>. Click yes/no per item, or type 'adjust <item>: <change>' in the terminal."

4. **Read `$state_dir/events`** after Noah responds.

5. **For each Yes:** implement the change in the relevant CSS file. For each Adjust: produce v2 mockup, repeat. For each No: drop silently.

6. **Commit per page** with message `polish(ui): <page> aesthetic refinements (<count> applied)`.

7. **Push an unload screen** (`waiting-<page>.html` with the "Continuing in terminal..." message from the visual-companion guide) when moving to the next page.

---

## Task 10: System page refinements

**Files (potentially):**
- Modify: `static/css/system.css`
- Modify: `static/views/system.html` (only if a refinement requires markup change)
- Create: `$screen_dir/system-refinements.html` (and `waiting-system.html`)

- [ ] **Step 1: Start Visual Companion server**

Run the start-server command from the Pass B preamble. Capture `screen_dir`, `state_dir`, `url`. Tell Noah the URL.

- [ ] **Step 2: Write `system-refinements.html`**

Propose 1–2 refinements for the System page. The page is currently a settings grid with theme selector, log-rows selector, server info, schema table. Likely directions:
- The `.tag` and `.tag-*` chrome in the schema table could be more visually quiet (less heavy borders, subtler colour stops).
- The select-chrome on theme/logRows could match the editorial-quiet feel better.

Mockup fragment example (write something concrete based on your read of the current CSS):

```html
<h2>System page refinements</h2>
<p class="subtitle">Click yes or no on each item. Reject = stays as-is.</p>

<div class="options" data-multiselect>
  <div class="option" data-choice="refine-tags" onclick="toggleSelect(this)">
    <div class="letter">A</div>
    <div class="content">
      <h3>Quieter schema-table tags</h3>
      <p>Drop the filled background; switch to a 1px border + the existing accent colour at 30% opacity for the text. Same information, lower visual weight.</p>
    </div>
  </div>
  <div class="option" data-choice="refine-select" onclick="toggleSelect(this)">
    <div class="letter">B</div>
    <div class="content">
      <h3>Select chrome unification</h3>
      <p>Both selects (theme + logRows) use the same chevron, same hover state, same focus ring. Matches the editorial feel applied elsewhere in the dashboard.</p>
    </div>
  </div>
</div>
```

(Write the actual fragment grounded in what's *currently* in `system.css` — these are illustrative bullets, not a recipe.)

- [ ] **Step 3: Tell Noah**

> "Visual Companion: System page refinements at `<url>`. Click items to approve, or type 'adjust <item>: <change>' / 'no <item>' in terminal. When done, type 'next'."

- [ ] **Step 4: Read Noah's response**

After Noah responds in terminal: read `$state_dir/events` for browser clicks. Combine with terminal text. List approved items.

- [ ] **Step 5: Implement approved items**

For each approved item, edit `static/css/system.css` (or `static/views/system.html` if markup must change — but markup changes are a sign of scope creep, prefer pure CSS).

- [ ] **Step 6: Visual smoke (both themes)** then `pytest tests/ -q`.

- [ ] **Step 7: Push unload screen and commit**

Write `$screen_dir/waiting-system.html`:

```html
<div style="display:flex;align-items:center;justify-content:center;min-height:60vh">
  <p class="subtitle">System refinements applied — continuing in terminal.</p>
</div>
```

```bash
git add static/css/system.css static/views/system.html
git commit -m "polish(ui): System page aesthetic refinements (N applied)"
```

Replace `N` with the actual count.

---

## Task 11: Connections page refinements

**Files (potentially):**
- Modify: `static/css/connections.css`
- Modify: `static/views/connections.html` (only if necessary)
- Create: `$screen_dir/connections-refinements.html`

Follow the same 7-step pattern as Task 10. Likely refinement directions for Connections (these are seeds, not prescriptions — base your mockups on the actual current CSS):
- Network-map node/line states (idle / live / error): subtler colour gradients between states.
- Uptime bar: the segments could read more like an editorial timeline than a progress bar.
- Endpoint-list rows: tighter vertical rhythm using the new `--space-*` tokens.

Commit message: `polish(ui): Connections page aesthetic refinements (N applied)`.

---

## Task 12: Sessions page refinements

**Files (potentially):**
- Modify: `static/css/sessions.css`
- Modify: `static/views/sessions.html` (only if necessary)
- Create: `$screen_dir/sessions-refinements.html`

Follow the same 7-step pattern. Likely refinement seeds:
- Session-row hover: currently might be border-colour change; propose a subtle background shift (using `--surface2`) so the row "lifts" rather than gets boxed.
- Verdict pills (Trainable / Usable / Skip): more differentiation between the three. Currently they likely share a chrome and only differ in colour. Consider weight, subtle iconography, or letter-spacing.
- Filter inputs: the active-filter accent the recent editorial pass added could extend to the focus-visible ring.

Commit message: `polish(ui): Sessions page aesthetic refinements (N applied)`.

---

## Task 13: Session Detail page refinements

**Files (potentially):**
- Modify: `static/css/session-detail.css`
- Modify: `static/views/session-detail.html` (only if necessary)
- Create: `$screen_dir/session-detail-refinements.html`

Same pattern. Likely refinement seeds for the heaviest page:
- Detail-section headers: clearer hierarchy between top-level and sub-section labels.
- Alignment-plot wrappers: less heavy borders, more like editorial figure boxes (subtle top + bottom rules instead of full borders).
- Issue chips: the chip palette can carry semantic colour (info / warn / bad) more clearly without becoming loud.

Commit message: `polish(ui): Session Detail page aesthetic refinements (N applied)`.

---

## Task 14: Recording page refinements

**Files (potentially):**
- Modify: `static/css/recording.css`
- Modify: `static/views/recording.html` (only if necessary)
- Create: `$screen_dir/recording-refinements.html`

Same pattern. Likely refinement seeds:
- Timer block: this is the most-visible element when a session is active. Consider giving it more typographic presence (use `--text-xl` or `--text-lg`, more breathing room).
- Device-card chrome (pen / watch / airpods): the three cards have slightly different visual treatments today; unify them.
- IMU chart container: subtle padding refinement using new spacing tokens.
- Logs panel: tabular numerals are already on; consider monospace stamp prefix more prominent.

Commit message: `polish(ui): Recording page aesthetic refinements (N applied)`.

---

## Task 15: Noah captures screenshots

**Files:**
- Create: `docs/screenshots/polish-phase1/recording-light.png`, `recording-dark.png`
- Create: `docs/screenshots/polish-phase1/sessions-light.png`, `sessions-dark.png`
- Create: `docs/screenshots/polish-phase1/session-detail-light.png`, `session-detail-dark.png`
- Create: `docs/screenshots/polish-phase1/connections-light.png`, `connections-dark.png`
- Create: `docs/screenshots/polish-phase1/system-light.png`, `system-dark.png`

**Why this task exists:** Claude cannot run a browser. Screenshots are the user-side deliverable that proves the polish landed.

- [ ] **Step 1: Tell Noah**

> "Polish landed. Could you capture 10 screenshots (5 pages × light/dark theme) at the recommended viewport (1440×900 or similar) and save them under `docs/screenshots/polish-phase1/`? Filename pattern: `<page>-<theme>.png`."

- [ ] **Step 2: Wait for "done"**

After Noah confirms screenshots are in place:

- [ ] **Step 3: Commit**

```bash
git add docs/screenshots/polish-phase1/
git commit -m "polish(ui): phase 1 reference screenshots"
```

---

## Task 16: Success-criteria audit

**Files:**
- Modify (potentially): any CSS/view file that fails a criterion

**Why this task exists:** the spec enumerates 9 success criteria. Walk them, document conformance in the PR description, fix anything that doesn't pass.

- [ ] **Step 1: Run criterion checks**

Criterion 1 (no hardcoded font-sizes):
```bash
grep -nHE "font-size:\s*[0-9]" static/css/*.css | grep -v "var(--text" | grep -v "/\* Why:"
```
Expected: zero matches (or only matches with `/* Why: ... */` inline exception comments).

Criterion 2 (no hardcoded spacing):
```bash
grep -nHE "(padding|margin|gap):\s*[0-9]" static/css/*.css | grep -v "var(--space" | grep -v "/\* Why:"
```
Expected: zero matches (or documented exceptions). Note: `0` and `auto` are fine; the grep above won't match them.

Criterion 3 (hover/focus coverage):
```bash
# For every .btn-*, .tab, .card, .session-row, .filters input, .filters select,
# .net-node, etc — confirm both :hover and :focus-visible rules exist.
for sel in btn tab card session-row chip net-node; do
  echo "=== .$sel ==="
  grep -nHE "\.$sel[^{]*:hover" static/css/*.css | head -3
  grep -nHE "\.$sel[^{]*:focus-visible" static/css/*.css | head -3
done
```

Manually cross-check against the interactive-element list in the audit doc.

Criterion 4 (transition normalisation):
```bash
grep -nHE "transition:[^;]+;" static/css/*.css | grep -vE "var\(--dur-(fast|slow)\)" | grep -v "/\* Why:"
```
Expected: zero matches.

Criterion 5 (colors on-palette):
```bash
grep -nHE "#[0-9a-fA-F]{3,8}\b|rgba?\(" static/css/*.css | grep -v "/\* Why:"
```
Expected: zero matches.

Criterion 6 (border-radius on-token):
```bash
grep -nHE "border-radius:" static/css/*.css | grep -v "var(--radius" | grep -v "50%" | grep -v "/\* Why:"
```
Expected: zero matches.

Criterion 7 (per-page refinements implemented): for each Yes-marked item from Tasks 10–14, find the commit that implements it.

Criterion 8 (light + dark screenshots): `ls docs/screenshots/polish-phase1/` shows 10 PNGs.

Criterion 9 (tests green): `pytest tests/ -q` = 68 passed.

- [ ] **Step 2: Fix any criterion failures**

For each grep that returned non-zero matches NOT covered by exception comments: fix or add an exception comment explaining why.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "polish(ui): close success-criteria gaps"
```

- [ ] **Step 4: Open PR with criteria conformance documented**

```bash
git push -u origin feature/dashboard-polish-phase1
gh pr create --base feature/adapt-web-ui \
  --title "Dashboard polish phase 1 (audit + token migration + per-page refinements)" \
  --body "$(cat <<'EOF'
## Summary

Phase 1 of the dashboard polish trilogy: structural audit + design-token migration + per-page aesthetic refinements approved item-by-item via the Visual Companion. JS untouched. Layout, states, and branding deferred to Phases 2 and 3.

## Spec & plan
- `docs/superpowers/specs/2026-05-11-dashboard-polish-phase1-design.md`
- `docs/superpowers/plans/2026-05-11-dashboard-polish-phase1.md`
- `docs/superpowers/audits/2026-05-11-dashboard-polish-audit.md`

## Success criteria conformance
- [ ] **1. No hardcoded font-sizes.** Grep result: <paste>.
- [ ] **2. No hardcoded spacing.** Grep result: <paste>.
- [ ] **3. Hover + focus-visible on every interactive element.** Cross-check vs audit list: <pass/items>.
- [ ] **4. Transitions normalised.** Grep result: <paste>.
- [ ] **5. Colors on-palette.** Grep result: <paste>.
- [ ] **6. Border-radius on-token.** Grep result: <paste>.
- [ ] **7. Approved refinements implemented.** <N items across 5 pages>.
- [ ] **8. Screenshots delivered.** `docs/screenshots/polish-phase1/` contains 10 PNGs.
- [ ] **9. Tests green.** `pytest tests/` = 68 passed.

## Test plan
- [x] `pytest tests/` green after each commit.
- [x] Manual smoke (both themes) on every page after each migration commit.
- [x] Per-page aesthetic refinements approved by user via Visual Companion before implementation.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:**
- Goal (polish-pass, all 5 pages, presentation-ready) → Tasks 1–16 cover it.
- Non-goals (layout, states, branding, JS, mobile) → enforced via the per-task scope notes and the Pass-B preamble's "markup changes are a sign of scope creep" guidance.
- Approach (two passes: structural audit then per-item aesthetic refinements via Visual Companion) → Pass A = Tasks 1–9, Pass B = Tasks 10–14, screenshots = Task 15, criteria = Task 16.
- Success criteria 1–9 → all checked in Task 16 with concrete grep commands.

**Placeholder scan:**
- No "TBD", "TODO", "appropriate error handling", "similar to Task N", "fill in details".
- Two intentional placeholders in the audit doc template (`<files>`, `<fill from grep output>`) — Task 1 Step 4 explicitly says to fill them in; they're a template, not a deliverable defect.
- Tasks 10–14 refinement seeds (e.g. "Likely refinement directions") are documented as seeds, not prescriptions. The actual mockup content is produced live based on the current CSS. This is deliberate: aesthetic decisions cannot be hard-coded in a plan written before the audit.

**Type/name consistency:**
- Token names (`--space-1..8`, `--text-xs..xl`, `--dur-fast/slow`, `--ease-default`) defined in Task 2, referenced consistently in Tasks 3–9 and the standard hover/focus pattern.
- `screen_dir`/`state_dir` referenced consistently across Tasks 10–14.
- Commit message prefix `polish(ui):` used consistently.

No gaps requiring patches.
