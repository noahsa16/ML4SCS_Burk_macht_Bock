# Dashboard Branding + Onboarding Phase 3a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent footer (team/uni/semester) and a first-run welcome card (on Recording) to the dashboard. Both are additive — no existing component changes layout or visual treatment.

**Architecture:** New `<footer>` element appended to `<body>`; minor flex adjustment on `#main` so body = main + footer. New `.welcome-card` block in `recording.html`, visibility toggled by `pages/recording.js` based on `S.allSessions.length === 0` AND no devices connected AND not localStorage-dismissed.

**Tech Stack:** Vanilla CSS with OKLCH tokens, native ES modules, FastAPI `StaticFiles`.

**Spec:** `docs/superpowers/specs/2026-05-11-dashboard-branding-phase3a-design.md`

---

## Conventions

- All paths relative to project root `/Users/noahsamel/PycharmProjects/ML4SCS_Burk_macht_Bock`.
- Base commit: `e410380` on `feature/adapt-web-ui`. New branch: `feature/dashboard-branding-phase3a`.
- `pytest tests/` = 69 passing at every commit (becomes 70 after Task 1 adds the new `footer.css` row).
- Commit messages use `brand(ui):` prefix.
- Both light and dark theme must render correctly at every commit.
- **No JS changes outside `static/js/pages/recording.js`.** Other page modules and core/* are untouched.
- **No `innerHTML = string` assignments.** Welcome-card markup lives in the static HTML; JS only toggles visibility + handles the dismiss click.

---

## Reality check — current state

`<body>` already uses `display: flex; flex-direction: column` (base.css:78). `#main` has `flex: 1; height: 100vh; overflow: hidden` (base.css:114) — the `height: 100vh` forces main to claim the full viewport, leaving no room for a footer. Task 1 removes the `height: 100vh` so footer + main share the body height via flex.

`html, body { height: 100%; overflow: hidden }` (base.css:75) stays — overflow stays on the body, content scrolling happens inside `#content`.

---

## Task 1: Branch + Footer

**Files:**
- Create: `static/css/footer.css`
- Modify: `dashboard.html` (add `<footer>` element + `<link>` to footer.css)
- Modify: `static/css/base.css` (remove `height: 100vh` from `#main`)
- Modify: `tests/test_dashboard_static.py` (add parametrise row for `/static/css/footer.css`)

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feature/dashboard-branding-phase3a
```

Expected: `Switched to a new branch 'feature/dashboard-branding-phase3a'`.

- [ ] **Step 2: Add parametrise row to the static-asset smoke test**

In `tests/test_dashboard_static.py`, find the parametrise list. Add `"/static/css/footer.css"` in alphabetical order. The list is alphabetical by full path; `footer.css` goes between `connections.css` and `recording.css`.

Run: `pytest tests/test_dashboard_static.py -v`
Expected: the new case FAILS with 404.

- [ ] **Step 3: Create `static/css/footer.css`**

```css
/* Persistent dashboard footer — sits below #main inside <body>. */
#site-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-6);
  background: var(--surface);
  border-top: 1px solid var(--border);
  font-size: var(--text-xs);
  color: var(--text3);
  font-family: var(--sans);
}

.site-footer-left,
.site-footer-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.site-footer-sep {
  color: var(--border2);
  user-select: none;
}

#site-footer a {
  color: var(--text3);
  text-decoration: none;
  transition: color var(--dur-fast) var(--ease-default);
}
#site-footer a:hover { color: var(--text); }
#site-footer a:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

- [ ] **Step 4: Add `<footer>` and `<link>` to `dashboard.html`**

In `dashboard.html`, find the `<link rel="stylesheet" href="/static/css/system.css">` line in the `<head>` and add the new link after it:

```html
<link rel="stylesheet" href="/static/css/footer.css">
```

In `dashboard.html`, find the closing `</main>` (or `</div>` matching `<main id="main">` — the existing markup may use a div with id="main"). Read the file to confirm. After that closing tag (still inside `<body>`), add:

```html
<footer id="site-footer">
  <div class="site-footer-left">
    <span>Noah Samel · Ben Kriegsmann · Tajuddin Snasni</span>
    <span class="site-footer-sep">·</span>
    <span>ML4SCS · Leuphana University · SS 26</span>
  </div>
  <div class="site-footer-right">
    <a href="https://github.com/noahsa16/ML4SCS_Burk_macht_Bock" target="_blank" rel="noopener">github</a>
  </div>
</footer>
```

- [ ] **Step 5: Fix `#main` layout in base.css**

In `static/css/base.css`, find:

```css
#main { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
```

Replace with (drop `height: 100vh` so the body's flex layout governs sizing):

```css
#main { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
```

The `min-height: 0` is the standard fix that lets flex children respect `overflow: hidden` even when their natural content is larger than the available space.

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -q
```
Expected: 70 passed (69 prior + 1 new asset row).

- [ ] **Step 7: Manual visual smoke (you cannot run a browser, but verify by reading):**

- `grep -n "site-footer" dashboard.html static/css/footer.css` returns matches in both.
- `grep -n "height: 100vh" static/css/base.css` returns zero (the line was changed, not deleted-then-added).
- The footer text is exactly: `Noah Samel · Ben Kriegsmann · Tajuddin Snasni · ML4SCS · Leuphana University · SS 26` plus `github`.

- [ ] **Step 8: Commit**

```bash
git add static/css/footer.css dashboard.html static/css/base.css tests/test_dashboard_static.py
git commit -m "brand(ui): persistent footer with team + uni + semester byline"
```

---

## Task 2: Welcome card

**Files:**
- Modify: `static/views/recording.html` (add `.welcome-card` block)
- Modify: `static/css/recording.css` (add welcome-card styling)
- Modify: `static/js/pages/recording.js` (add `_updateWelcomeCard(s)` helper + dismiss handler)

### Step 1: Markup — add the welcome card to `recording.html`

The welcome card lives at the TOP of the recording partial, BEFORE `.rec-grid`. Insert this as the FIRST child of the partial:

```html
<div class="welcome-card" id="welcomeCard" style="display:none">
  <div class="welcome-card-head">
    <div class="welcome-card-glyph">/</div>
    <div>
      <div class="welcome-card-title">Welcome to ML4SCS</div>
      <div class="welcome-card-subtitle">Writing activity detection via Apple Watch IMU</div>
    </div>
  </div>
  <ol class="welcome-card-steps">
    <li>
      <span class="welcome-card-step-num">1</span>
      <div>
        <div class="welcome-card-step-title">Connect the pen</div>
        <div class="welcome-card-step-hint">Power on the Moleskine pen, then click Connect on the Smart Pen card.</div>
      </div>
    </li>
    <li>
      <span class="welcome-card-step-num">2</span>
      <div>
        <div class="welcome-card-step-title">Start the Watch app</div>
        <div class="welcome-card-step-hint">Open WatchStreamer on your Apple Watch — it streams IMU samples to this dashboard.</div>
      </div>
    </li>
    <li>
      <span class="welcome-card-step-num">3</span>
      <div>
        <div class="welcome-card-step-title">Press START</div>
        <div class="welcome-card-step-hint">Hit the START button once pen and watch both show as connected.</div>
      </div>
    </li>
  </ol>
  <button type="button" class="welcome-card-dismiss" id="welcomeDismiss">dismiss this welcome</button>
</div>
```

### Step 2: CSS — append to `static/css/recording.css`

```css
/* Welcome card — first-run onboarding, shown only when no sessions exist
   and no devices are connected. Hidden by default; toggled by recording.js. */
.welcome-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.welcome-card-head {
  display: flex; align-items: flex-start; gap: var(--space-4);
}
.welcome-card-glyph {
  font-family: var(--mono); font-style: italic; font-weight: 600;
  font-size: var(--text-xl); color: var(--accent); opacity: 0.55;
  line-height: 1;
}
.welcome-card-title {
  font-family: var(--sans); font-size: var(--text-lg); font-weight: 500;
  letter-spacing: -0.02em; color: var(--text);
  line-height: 1.1;
}
.welcome-card-subtitle {
  font-size: var(--text-sm); color: var(--text2);
  margin-top: var(--space-1);
}
.welcome-card-steps {
  list-style: none; margin: 0; padding: 0;
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}
.welcome-card-steps li {
  display: flex; align-items: flex-start; gap: var(--space-3);
}
.welcome-card-step-num {
  flex: 0 0 auto;
  font-family: var(--mono); font-size: var(--text-md); font-weight: 600;
  color: var(--accent);
  line-height: 1;
  margin-top: 2px;
}
.welcome-card-step-title {
  font-size: var(--text-base); font-weight: 600; color: var(--text);
}
.welcome-card-step-hint {
  font-size: var(--text-sm); color: var(--text3);
  margin-top: var(--space-1); line-height: 1.5;
}
.welcome-card-dismiss {
  align-self: flex-start;
  font-family: var(--sans); font-size: var(--text-sm); color: var(--text3);
  background: none; border: none; padding: 0; cursor: pointer;
  text-decoration: underline;
  transition: color var(--dur-fast) var(--ease-default);
}
.welcome-card-dismiss:hover { color: var(--text); }
.welcome-card-dismiss:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

@media (max-width: 880px) {
  .welcome-card-steps { grid-template-columns: 1fr; }
}
```

### Step 3: JS — wire visibility from `pages/recording.js`

In `static/js/pages/recording.js`, add a private helper near the other private functions:

```js
function _isWelcomeDismissed() {
  try { return localStorage.getItem('welcomeDismissed') === '1'; } catch { return false; }
}

function _updateWelcomeCard(s) {
  const card = document.getElementById('welcomeCard');
  if (!card) return;
  // Predicate: no sessions on disk yet, no devices connected, not dismissed.
  // S.allSessions is null/undefined until loadSessions() resolves — treat null
  // as "unknown, keep hidden so we don't flash".
  const noSessions = Array.isArray(S.allSessions) && S.allSessions.length === 0;
  const noPen = !s?.pen_connected;
  const noWatch = !(s?.watch_connected || s?.watch_stream_active);
  const noAirpods = !s?.airpods_connected;
  const show = noSessions && noPen && noWatch && noAirpods && !_isWelcomeDismissed();
  card.style.display = show ? '' : 'none';
}
```

The predicate field names mirror the existing connected-checks added in Phase 2a (read `_updateDeviceEmpty` calls in the same file to confirm — use the same expressions, do NOT invent new field names).

In `mount(container)`, wire the dismiss button click:

```js
export function mount(container) {
  if (_mounted) return;
  _mounted = true;
  // ... existing mount code ...

  const dismissBtn = document.getElementById('welcomeDismiss');
  if (dismissBtn) {
    dismissBtn.addEventListener('click', () => {
      try { localStorage.setItem('welcomeDismissed', '1'); } catch {}
      const card = document.getElementById('welcomeCard');
      if (card) card.style.display = 'none';
    });
  }
}
```

In `onStatus(s)`, call `_updateWelcomeCard(s)`:

```js
export function onStatus(s) {
  // ... existing onStatus body ...
  _updateWelcomeCard(s);
}
```

Place the call near the existing `_updateDeviceEmpty(...)` calls (they share the same state-driven visibility pattern).

### Step 4: Run tests

```bash
pytest tests/ -q
```
Expected: 70 passed.

### Step 5: Self-check

- `grep -n "welcomeCard\|welcomeDismiss\|welcome-card" static/views/recording.html static/css/recording.css static/js/pages/recording.js` returns matches in all three.
- `grep -n "innerHTML\s*=\s*['\"\`]" static/js/pages/recording.js` should show only PRE-EXISTING innerHTML assignments (e.g. the rows-present log-panel branch). Zero new ones from this task.
- The welcome card's static HTML in `recording.html` has `style="display:none"` so it doesn't flash on initial load.

### Step 6: Commit

```bash
git add static/views/recording.html static/css/recording.css static/js/pages/recording.js
git commit -m "brand(ui): first-run welcome card on Recording (state-driven + dismissable)"
```

---

## Task 3: Audit pass + PR

**Files:** none modified unless audit surfaces an issue.

### Step 1: Self-audit

Walk through each spec success criterion:

1. **Footer visible on every page**: Read `dashboard.html` — footer is outside the `#main` element (which holds the page slots). Visual identity check: `grep -nA 1 "site-footer" dashboard.html`.
2. **Footer does not overlap content**: `#main` now has `min-height: 0` instead of `height: 100vh`. The body's flex layout sizes `#main` to fill available space minus footer. Verified by reading the CSS.
3. **Welcome card visible on fresh dashboard**: predicate inspected in `pages/recording.js _updateWelcomeCard`. All four AND conditions must be true.
4. **Welcome card disappears on any device connect / session create / dismiss**: predicate inspected. When `s.pen_connected` becomes true, `noPen` becomes false → `show` becomes false → card hides on the next WS tick (or immediately via the dismiss click handler).
5. **Dismissed welcome persists across reloads**: `_isWelcomeDismissed` reads `localStorage.welcomeDismissed`. Dismiss button writes `'1'`. Verified.
6. **Both themes**: footer uses `--surface`, `--border`, `--text3`, `--text`, all theme-aware. Welcome-card uses `--surface`, `--border`, `--accent`, `--text`, `--text2`, `--text3`. All theme-aware. No hardcoded colors. Confirmed via `grep -nE "#[0-9a-fA-F]|oklch\(|rgb\(" static/css/footer.css static/css/recording.css`.
7. **`pytest tests/`** = 70.
8. **No JS changes outside `static/js/pages/recording.js`**: `git diff e410380..HEAD --name-only` shows only `static/js/pages/recording.js` under `static/js/`.

### Step 2: Final test run

```bash
pytest tests/ -q
```
Expected: 70 passed.

### Step 3: Push + open PR

```bash
git push -u origin feature/dashboard-branding-phase3a
gh pr create --base feature/adapt-web-ui \
  --title "Dashboard branding + onboarding phase 3a (footer + welcome card)" \
  --body "$(cat <<'EOF'
## Summary

Phase 3a of the dashboard-polish trilogy. Tight scope: persistent footer with team byline + a first-run welcome card on Recording. Both additive — no existing component changes layout or visual treatment.

**Footer** sits below `#main` in the body's flex column. Shows team names, project byline (\`ML4SCS · Leuphana University · SS 26\`), and a github link. Visible on every page.

**Welcome card** lives at the top of the Recording partial, hidden by default. Visible when: zero sessions on disk AND no pen/watch/airpods connected AND not previously dismissed. Three numbered steps + dismiss link. Hides immediately when any device connects, a session is created, or the user clicks dismiss. Dismiss persists in localStorage.

## Spec & plan
- \`docs/superpowers/specs/2026-05-11-dashboard-branding-phase3a-design.md\`
- \`docs/superpowers/plans/2026-05-11-dashboard-branding-phase3a.md\`

## Success criteria conformance
- [x] 1. Footer visible on every page, both themes.
- [x] 2. Footer does not overlap content (\`#main { min-height: 0 }\` replaces \`height: 100vh\`).
- [x] 3. Welcome card visible on fresh dashboard.
- [x] 4. Welcome card disappears on device-connect / session-create / dismiss.
- [x] 5. Dismiss persists in localStorage.
- [x] 6. Both themes render correctly.
- [x] 7. \`pytest tests/\` = 70 passes.
- [x] 8. No JS changes outside \`pages/recording.js\`.

## Test plan
- [x] \`pytest tests/\` green at every commit.
- [ ] **You**: open dashboard with no sessions + no devices → welcome card shows on Recording. Connect any device → card hides. Click dismiss → card hides; reload → still hidden. Walk all 5 pages → footer visible on each, both themes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:**
- Footer (Architecture → Task 1 covers).
- Welcome card markup (Architecture → Task 2 Step 1).
- Visibility predicate (Architecture → Task 2 Step 3, matches spec exactly).
- localStorage dismiss flag (Architecture → Task 2 Step 3).
- `#main { height: 100vh }` adjustment (Risk register → Task 1 Step 5).
- Both themes via tokens (success criteria → Task 3 Step 1 audit).

**Placeholder scan:** No "TBD", no "implement later", no "add appropriate handling". The "..." in JS code blocks (e.g. `// ... existing mount code ...`) is intentional — the engineer keeps existing code and adds the new lines around it. That's standard and unambiguous.

**Type consistency:** `_updateWelcomeCard(s)` signature used in both definition and call site. localStorage key `'welcomeDismissed'` consistent in `_isWelcomeDismissed` and dismiss handler. Element IDs `welcomeCard` and `welcomeDismiss` consistent across HTML / CSS / JS.

No gaps requiring patches.
