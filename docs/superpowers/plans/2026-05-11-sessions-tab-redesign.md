# Sessions Tab Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the overloaded Sessions tab (14-column table + inline-expand panel that dumps everything at once) with a calm 4-column triage list (persistent filters) and a dedicated Session Detail page using progressive disclosure (single verdict + 4 collapsible sections).

**Architecture:** Frontend-only refactor of `dashboard.html` + `static/dashboard.js`. The existing per-session rendering functions (`renderSessionValidation`, `renderTimeline`, `renderAlignment`, `_drawAlignVarianceCurve`, `_drawAlignTimeline`) get **reused** inside new collapsible `<details>` sections on a dedicated detail page reached via hash route `#session/<id>`. No backend changes.

**Tech Stack:** Vanilla JS + module-scoped state object `S`, native HTML5 `<details>`/`<summary>` for collapse, `localStorage` for filter + section state, Chart.js (already used by alignment charts).

**Spec:** `docs/superpowers/specs/2026-05-11-sessions-tab-redesign-design.md`

**Note on testing:** This project has no JS test harness — frontend changes are verified by running the FastAPI server and smoke-checking in a browser. Steps use `Run server + open page + check X` as the verification step instead of `pytest`.

---

## File Map

- **Modify** `dashboard.html`:
  - Replace inner content of `<div class="page" id="page-sessions">` (lines 995–1103) with filter bar + 4-column table.
  - Add new sibling `<div class="page" id="page-session-detail">` after it.
  - Remove inline-detail CSS rules (`.sessions-table tr.detail-row …`, lines 588–591).
  - Add new CSS for `.verdict-badge`, `.session-detail-header`, `.detail-section`, `.filter-bar`.
- **Modify** `static/dashboard.js`:
  - Replace `renderSessions()` with `renderSessionsList()` (4 columns, no inline expand).
  - Replace `filterSessions()` with `applyFilters()` (persistent multi-criterion).
  - Add new functions: `computeVerdict()`, `openSessionDetail()`, `closeSessionDetail()`, `loadFilters()`, `saveFilters()`, `_routeFromHash()`.
  - Remove `_mountValidationPanel()` and the detail-row DOM-shuffle dance.
  - Update tab-click handler to clear hash when leaving sessions, and to route on `hashchange`.
- **Create** `docs/superpowers/manual-smoke/sessions-redesign.md` — short checklist used by Task 8.

No backend file is touched.

---

## Task 1: Pure helpers — `computeVerdict()` and filter state plumbing

Start with the only piece that has a meaningful pure-function contract: the verdict logic. Then add the localStorage helpers so later tasks can use them.

**Files:**
- Modify: `static/dashboard.js` — add to the SESSIONS TABLE section, near `loadSessions` (around line 900).

- [ ] **Step 1: Add `computeVerdict()` above `loadSessions()`**

Insert immediately before `// ════════════ SESSIONS TABLE ═══════` block (around line 900):

```javascript
// ════════════════════════════════════════════════════════════
//  SESSION VERDICT — single 3-level summary used by both
//  the triage list (filter target) and the detail page header.
// ════════════════════════════════════════════════════════════
// Thresholds match docs/superpowers/specs/2026-05-11-sessions-tab-redesign-design.md
// and src/training docs in CLAUDE.md (σ ≤ -3 trainable, ≥ 5 min within-session).
const VERDICT_TRAINABLE = 'trainable';
const VERDICT_USABLE    = 'usable';
const VERDICT_SKIP      = 'skip';

function computeVerdict(quality, alignment, durationSec) {
  const ml = quality?.ml_readiness?.status || quality?.quality || 'unknown';
  const issues = [
    ...(quality?.ml_readiness?.blockers || []),
    ...(quality?.recording_health?.blockers || []),
  ].map(i => i.code);
  if (ml === 'bad' || issues.includes('sync_failed') || issues.includes('streams_do_not_overlap')) {
    return { level: VERDICT_SKIP, label: 'Skip' };
  }
  const sigma = alignment?.sigma_minimal_variance;
  const dur = Number(durationSec || 0);
  if (ml === 'ok' && Number.isFinite(sigma) && sigma <= -3 && dur >= 300) {
    return { level: VERDICT_TRAINABLE, label: 'Trainable' };
  }
  return { level: VERDICT_USABLE, label: 'Usable' };
}
```

- [ ] **Step 2: Add filter-state helpers below `computeVerdict()`**

```javascript
// Filter state persists in localStorage so reloads don't drop user intent.
const FILTERS_KEY = 'sessionsFilter.v1';
const DEFAULT_FILTERS = { q: '', ml: 'all', align: 'all', minFive: false };

function loadFilters() {
  try {
    const raw = localStorage.getItem(FILTERS_KEY);
    if (!raw) return { ...DEFAULT_FILTERS };
    return { ...DEFAULT_FILTERS, ...JSON.parse(raw) };
  } catch { return { ...DEFAULT_FILTERS }; }
}
function saveFilters(f) {
  try { localStorage.setItem(FILTERS_KEY, JSON.stringify(f)); } catch {}
}
function resetFilters() { localStorage.removeItem(FILTERS_KEY); }
```

- [ ] **Step 3: Smoke-check helpers in the browser console**

Run the server: `uvicorn server:app --host 0.0.0.0 --port 8000`
Open `http://localhost:8000`. In DevTools console, run:

```javascript
computeVerdict({ ml_readiness: { status: 'ok', blockers: [] }, recording_health: { blockers: [] } },
               { sigma_minimal_variance: -5.27 }, 432)
// Expected: { level: 'trainable', label: 'Trainable' }

computeVerdict({ ml_readiness: { status: 'bad' } }, null, 0)
// Expected: { level: 'skip', label: 'Skip' }

computeVerdict({ ml_readiness: { status: 'ok' } }, { sigma_minimal_variance: -2.1 }, 432)
// Expected: { level: 'usable', label: 'Usable' }

saveFilters({ q: 'foo', ml: 'ok', align: 's3', minFive: true });
loadFilters();
// Expected: { q: 'foo', ml: 'ok', align: 's3', minFive: true }
resetFilters();
```

- [ ] **Step 4: Commit**

```bash
git add static/dashboard.js
git commit -m "Sessions: add computeVerdict + filter-state helpers"
```

---

## Task 2: CSS — verdict badge, detail header, sections, filter bar

Add all visual primitives the later tasks need. Doing this first means later HTML/JS work isn't blocked on style decisions.

**Files:**
- Modify: `dashboard.html` — CSS `<style>` block. Find the existing `/* ─── Sessions page ─── */` block (around line 477) and **after the end** of the Pen-IMU alignment CSS (search for `.alignment-empty`), append the new rules.

- [ ] **Step 1: Append new CSS at the end of the Sessions page CSS section**

Find the line containing `.alignment-empty {` (around line 599+); after its closing `}`, insert:

```css
/* ─── Filter bar (new triage UI) ───────────────────────────── */
.filter-bar {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin-bottom: 14px;
}
.filter-bar input[type="text"] { max-width: 280px; }
.filter-bar select,
.filter-bar input[type="text"] {
  font-size: 12.5px; padding: 6px 9px;
  border: 1px solid var(--border2); border-radius: var(--radius-sm);
  background: var(--surface); color: var(--text);
}
.filter-bar label.toggle {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text2); cursor: pointer; user-select: none;
}
.filter-bar .reset-link {
  font-size: 12px; color: var(--text3); text-decoration: underline;
  background: none; border: none; cursor: pointer; padding: 0;
}
.filter-bar .reset-link:hover { color: var(--text); }
.filter-bar .spacer { flex: 1; }

/* ─── Verdict badge (detail page header) ───────────────────── */
.verdict-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 220px; padding: 14px 28px;
  font-family: var(--sans); font-size: 22px; font-weight: 700;
  letter-spacing: 0.04em; text-transform: uppercase;
  border-radius: var(--radius-sm); border: 1px solid var(--border);
}
.verdict-badge.trainable { color: var(--green); border-color: oklch(0.700 0.150 145 / 0.6); background: oklch(0.700 0.150 145 / 0.08); }
.verdict-badge.usable    { color: #b08000;        border-color: oklch(0.770 0.140 88 / 0.55); background: oklch(0.770 0.140 88 / 0.10); }
.verdict-badge.skip      { color: #c54a4a;        border-color: oklch(0.620 0.190 25 / 0.55); background: oklch(0.620 0.190 25 / 0.08); }

.session-detail-header {
  display: flex; flex-direction: column; gap: 14px;
  padding: 18px 22px; margin-bottom: 18px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
}
.session-detail-header .back-link {
  font-size: 12px; color: var(--text2); text-decoration: none;
  background: none; border: none; padding: 0; cursor: pointer; align-self: flex-start;
}
.session-detail-header .back-link:hover { color: var(--text); }
.session-detail-header .title-row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.session-detail-header .title { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
.session-detail-header .subtitle { color: var(--text2); font-size: 13px; margin-top: 4px; }
.session-detail-header .pills { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.session-detail-header .pill {
  font-size: 11.5px; font-family: var(--mono); padding: 4px 10px;
  border-radius: var(--radius-pill); border: 1px solid var(--border); background: var(--surface2); color: var(--text2);
}
.session-detail-header .pill.ok  { color: var(--green); border-color: oklch(0.700 0.150 145 / 0.45); }
.session-detail-header .pill.warn { color: #b08000;     border-color: oklch(0.770 0.140 88 / 0.45); }
.session-detail-header .pill.err  { color: #c54a4a;     border-color: oklch(0.620 0.190 25 / 0.45); }

/* ─── Collapsible sections (HTML5 <details>) ───────────────── */
.detail-section {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); margin-bottom: 12px; overflow: hidden;
}
.detail-section > summary {
  list-style: none; cursor: pointer; user-select: none;
  padding: 14px 20px;
  display: flex; align-items: center; gap: 10px;
  font-size: 14px; font-weight: 600; letter-spacing: -0.005em; color: var(--text);
}
.detail-section > summary::-webkit-details-marker { display: none; }
.detail-section > summary::before {
  content: '▸'; color: var(--text3); font-size: 11px; transition: transform 0.15s ease;
}
.detail-section[open] > summary::before { transform: rotate(90deg); }
.detail-section > summary .count {
  font-family: var(--mono); font-size: 11px; color: var(--text3);
  background: var(--surface2); padding: 2px 7px; border-radius: var(--radius-pill);
  margin-left: 6px;
}
.detail-section .section-body { padding: 4px 20px 18px; }
```

- [ ] **Step 2: Reload the page and confirm no CSS errors**

Hard-reload `http://localhost:8000`. Open DevTools Console — there must be no CSS parse errors. The page should look identical to before (these classes aren't used yet).

- [ ] **Step 3: Commit**

```bash
git add dashboard.html
git commit -m "Sessions: add CSS for verdict badge, filter bar, detail sections"
```

---

## Task 3: HTML — new Sessions page body + detail page skeleton

Replace the Sessions page HTML with the slim version, and append the new detail page. The detail page starts empty — JS will populate it.

**Files:**
- Modify: `dashboard.html` lines 995–1103 (the entire `<div class="page" id="page-sessions">…</div>`).
- Modify: `dashboard.html` — insert new `<div class="page" id="page-session-detail">` immediately after the closing of `page-sessions`.

- [ ] **Step 1: Replace the body of `#page-sessions`**

Use Edit to replace the block starting at `<div class="page" id="page-sessions">` and ending at its matching `</div>` (the one just before `<!-- ══════════ PAGE: CONNECTIONS ══════════ -->`) with:

```html
    <div class="page" id="page-sessions">
      <div class="card" style="margin-bottom:14px">
        <div class="chart-meta">
          <div class="card-title" style="margin:0">Data Quality Report<span>model readiness per recording</span></div>
          <button class="btn btn-outline btn-sm" onclick="loadSessions()">↻ Refresh</button>
        </div>
        <div class="health-grid">
          <div class="health-box"><div class="k">Total Sessions</div><div class="v" id="qualityTotal">–</div></div>
          <div class="health-box"><div class="k">ML Ready</div><div class="v ok" id="qualityOk">–</div></div>
          <div class="health-box"><div class="k">ML Warnings</div><div class="v warn" id="qualityWarn">–</div></div>
          <div class="health-box"><div class="k">ML Blocked</div><div class="v err" id="qualityBad">–</div></div>
        </div>
      </div>

      <div class="filter-bar">
        <input type="text" id="filterQ" placeholder="Search session, person, or description…">
        <select id="filterMl" title="ML readiness">
          <option value="all">ML: all</option>
          <option value="ok">Ready</option>
          <option value="warn">Warnings</option>
          <option value="bad">Blocked</option>
        </select>
        <select id="filterAlign" title="Alignment confidence">
          <option value="all">Alignment: all</option>
          <option value="s3">σ ≤ −3 (trainable)</option>
          <option value="s2">σ ≤ −2 (ok)</option>
          <option value="failed">failed</option>
          <option value="none">no pen</option>
        </select>
        <label class="toggle"><input type="checkbox" id="filterMinFive"> ≥ 5 min</label>
        <button class="reset-link" id="filterReset" type="button">Reset</button>
        <span class="spacer"></span>
      </div>

      <div class="card" style="padding:0;overflow:hidden">
        <table class="sessions-table">
          <thead>
            <tr>
              <th>Session</th>
              <th>Start · Duration</th>
              <th>ML Status</th>
              <th>Alignment σ</th>
            </tr>
          </thead>
          <tbody id="sessionsBody">
            <tr><td colspan="4"><div class="empty-state"><div class="empty-state-title">Loading sessions…</div></div></td></tr>
          </tbody>
        </table>
      </div>
    </div>
```

- [ ] **Step 2: Append `#page-session-detail` directly after `#page-sessions`**

After the closing `</div>` of `#page-sessions` and before `<!-- ══════════ PAGE: CONNECTIONS ══════════ -->`, insert:

```html

    <!-- ══════════ PAGE: SESSION DETAIL ══════════ -->
    <div class="page" id="page-session-detail">
      <div class="session-detail-header">
        <button class="back-link" type="button" onclick="closeSessionDetail()">← Sessions</button>
        <div class="title-row">
          <div>
            <div class="title" id="detailTitle">–</div>
            <div class="subtitle" id="detailSubtitle">–</div>
          </div>
          <a class="export-link" id="detailReportLink" href="#" target="_blank">⤓ md report</a>
        </div>
        <div class="verdict-badge" id="detailVerdict">–</div>
        <div class="pills">
          <span class="pill" id="detailPillMl">ML –</span>
          <span class="pill" id="detailPillRec">Rec –</span>
          <span class="pill" id="detailPillAlign">Align –</span>
        </div>
      </div>

      <details class="detail-section" data-section="streams">
        <summary>Streams &amp; Samples</summary>
        <div class="section-body" id="detailStreams">–</div>
      </details>

      <details class="detail-section" data-section="timeline">
        <summary>Timeline &amp; Drift</summary>
        <div class="section-body">
          <div class="timeline-wrap" id="detailTimeline"></div>
          <div class="drift-grid">
            <div class="drift-box"><div class="k">Watch clock drift</div><div class="v" id="driftWatch">–</div></div>
            <div class="drift-box"><div class="k">Pen clock drift</div><div class="v" id="driftPen">–</div></div>
            <div class="drift-box"><div class="k">Relative drift</div><div class="v" id="driftRelative">–</div></div>
            <div class="drift-box"><div class="k">Clock offset gap</div><div class="v" id="driftSyncOffset">–</div></div>
          </div>
        </div>
      </details>

      <details class="detail-section" data-section="alignment">
        <summary>Pen ↔ Watch Alignment</summary>
        <div class="section-body">
          <div class="alignment-section" id="alignmentSection" style="display:block;margin-top:0;padding-top:0;border-top:none">
            <div class="alignment-head">
              <div class="card-title" style="margin-bottom:4px">Stroke-Variance Time-Sync</div>
              <div class="alignment-status" id="alignmentStatus">–</div>
            </div>
            <div class="alignment-explainer" id="alignmentExplainer">
              Beim Schreiben hält die schreibende Hand die Uhr ruhig — Pausen und Gesten erzeugen
              mehr Bewegung. Der Algorithmus probiert verschiedene Zeitverschiebungen δ aus und
              wählt die, bei der die Pen-Striche auf die ruhigsten Phasen fallen.
            </div>
            <div class="alignment-metrics">
              <div class="drift-box"><div class="k">Offset δ</div><div class="v" id="alignDelta">–</div></div>
              <div class="drift-box"><div class="k">Confidence σ</div><div class="v" id="alignSigma">–</div></div>
              <div class="drift-box"><div class="k">Striche</div><div class="v" id="alignStrokes">–</div></div>
              <div class="drift-box"><div class="k">Ruhe-Faktor</div><div class="v" id="alignFactor">–</div></div>
            </div>
            <div class="alignment-charts">
              <div class="alignment-chart">
                <div class="alignment-chart-title">Varianz-Suchkurve</div>
                <canvas id="alignVarCanvas"></canvas>
              </div>
              <div class="alignment-chart">
                <div class="alignment-chart-title">Pen-Striche auf Watch-Bewegung</div>
                <canvas id="alignTimelineCanvas"></canvas>
              </div>
            </div>
            <div class="alignment-empty" id="alignmentEmpty" style="display:none">Alignment ist für diese Session nicht verfügbar.</div>
          </div>
        </div>
      </details>

      <details class="detail-section" data-section="issues">
        <summary>Issues <span class="count" id="detailIssuesCount">0</span></summary>
        <div class="section-body">
          <div class="issue-list" id="detailIssues"></div>
          <div class="validation-note" id="detailIssuesSummary"></div>
        </div>
      </details>
    </div>
```

- [ ] **Step 3: Reload and confirm the Sessions tab still works in a degraded way**

Hard-reload, click the Sessions tab. The 4-column header is visible; the body says "Loading sessions…" forever (because JS hasn't been rewired yet — expected). The detail page is hidden (`display: none` from `.page` rule). Console: no errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard.html
git commit -m "Sessions: replace tab HTML with 4-col list + detail page skeleton"
```

---

## Task 4: JS — hash routing + page switching

Get navigation between list and detail working before re-implementing rendering. After this task the URL drives which page is visible.

**Files:**
- Modify: `static/dashboard.js` — the tab-click handler (around line 45–62) and add a new `_routeFromHash()` function.

- [ ] **Step 1: Add `_routeFromHash()` next to the tab-click handler**

Insert immediately **after** the tab-click `forEach` block ending around line 62:

```javascript
// Hash routing: only one route shape — #session/<id> opens the
// detail page. Empty hash returns to whichever tab was active.
function _routeFromHash() {
  const m = location.hash.match(/^#session\/(.+)$/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
    document.getElementById('page-session-detail').classList.add('active');
    document.querySelectorAll('.tab').forEach(n => n.classList.toggle('active', n.dataset.page === 'sessions'));
    updateTabIndicator();
    openSessionDetail(id);
    return;
  }
  // No detail route — make sure detail page is hidden if it was open.
  document.getElementById('page-session-detail')?.classList.remove('active');
}

window.addEventListener('hashchange', _routeFromHash);
window.addEventListener('load', _routeFromHash);

function closeSessionDetail() {
  if (location.hash.startsWith('#session/')) {
    history.replaceState(null, '', location.pathname + location.search);
  }
  document.getElementById('page-session-detail').classList.remove('active');
  document.getElementById('page-sessions').classList.add('active');
}
```

- [ ] **Step 2: Stub `openSessionDetail()` so routing doesn't break**

Insert near the other Sessions functions (around line 1035 where `selectSession` lives), a minimal stub. The real implementation comes in Task 6.

```javascript
async function openSessionDetail(sessionId) {
  // Stub — populated in Task 6. Just makes the page visible.
  document.getElementById('detailTitle').textContent = `Session ${sessionId}`;
  document.getElementById('detailSubtitle').textContent = 'Loading…';
}
```

- [ ] **Step 3: Make the existing tab-click handler clear the hash when leaving session detail**

Find the tab-click handler block (lines 45–62) and add **immediately inside** the click callback, at the very top:

```javascript
    // Leaving any tab clears a session-detail route so the URL reflects the active tab.
    if (location.hash.startsWith('#session/')) {
      history.replaceState(null, '', location.pathname + location.search);
      document.getElementById('page-session-detail')?.classList.remove('active');
    }
```

- [ ] **Step 4: Smoke-test routing**

Reload. In console:

```javascript
location.hash = '#session/S029'
// Expected: detail page becomes visible, title shows "Session S029"
location.hash = ''
// Expected: detail page hides, last-active normal tab is shown
```

Also click between tabs — confirm no errors.

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.js
git commit -m "Sessions: hash route #session/<id> opens detail page"
```

---

## Task 5: JS — new triage list (filter bar + 4-col render)

Replace `renderSessions()` and `filterSessions()` with the new versions. Filter state writes/reads through the helpers from Task 1.

**Files:**
- Modify: `static/dashboard.js` — replace `renderSessions()` (line 942), `filterSessions()` (line 930), `_mountValidationPanel()` (line 1013), and `selectSession()` (line 1035).

- [ ] **Step 1: Replace `filterSessions()` and `renderSessions()` with `applyFilters()` + `renderSessionsList()`**

Delete the existing `filterSessions()` function (lines ~929–940) and `renderSessions()` (lines ~942–1011) and replace with:

```javascript
// Cached snapshot so filter changes don't re-fetch.
function _matchesFilters(s, q, filters) {
  const txt = filters.q.toLowerCase();
  if (txt && !(
    s.session_id?.toLowerCase().includes(txt) ||
    s.person_id?.toLowerCase().includes(txt) ||
    s.description?.toLowerCase().includes(txt)
  )) return false;

  const mlStatus = q?.ml_readiness?.status || q?.quality || 'unknown';
  if (filters.ml !== 'all' && mlStatus !== filters.ml) return false;

  // Alignment data lives on a separate endpoint; cached in S.alignmentBySession.
  // If a session's alignment isn't loaded yet, "all" passes; specific filters
  // exclude it until the bulk fetch completes (which re-applies filters).
  const a = S.alignmentBySession?.[s.session_id];
  const sigma = a?.sigma_minimal_variance;
  const failed = a?.status === 'failed' || (Number.isFinite(sigma) && sigma > -2);
  const hasPen = !!a && Number.isFinite(sigma);
  if (filters.align === 's3' && !(Number.isFinite(sigma) && sigma <= -3)) return false;
  if (filters.align === 's2' && !(Number.isFinite(sigma) && sigma <= -2)) return false;
  if (filters.align === 'failed' && !failed) return false;
  if (filters.align === 'none' && hasPen) return false;

  if (filters.minFive) {
    const dur = s.start_time && s.end_time
      ? (new Date(s.end_time) - new Date(s.start_time)) / 1000
      : 0;
    if (dur < 300) return false;
  }
  return true;
}

function applyFilters() {
  const filters = {
    q: document.getElementById('filterQ').value,
    ml: document.getElementById('filterMl').value,
    align: document.getElementById('filterAlign').value,
    minFive: document.getElementById('filterMinFive').checked,
  };
  saveFilters(filters);
  const rows = (S.allSessions || []).filter(s => _matchesFilters(s, S.qualityBySession[s.session_id], filters));
  renderSessionsList(rows);
}

function _sigmaPill(sessionId) {
  const a = S.alignmentBySession?.[sessionId];
  const sigma = a?.sigma_minimal_variance;
  if (!Number.isFinite(sigma)) {
    if (a?.status === 'failed') return '<span class="status-badge badge-err">failed</span>';
    return '<span class="mono" style="color:var(--text3)">—</span>';
  }
  const cls = sigma <= -3 ? 'badge-ok' : sigma <= -2 ? 'badge-warn' : 'badge-err';
  return `<span class="status-badge ${cls}">${sigma.toFixed(2)}</span>`;
}

function renderSessionsList(rows) {
  const tbody = document.getElementById('sessionsBody');
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state">
      <div class="empty-state-glyph">/</div>
      <div class="empty-state-title">No matching sessions</div>
      <div class="empty-state-hint">Adjust the filters above, or start a new recording from the Recording tab.</div>
    </div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(s => {
    const q = S.qualityBySession[s.session_id] || {};
    const ml = q.ml_readiness || { status: q.quality || 'unknown' };
    const mlBadge = scoreBadge(ml);
    const dur = s.start_time && s.end_time
      ? fmtDuration(Math.floor((new Date(s.end_time) - new Date(s.start_time)) / 1000))
      : (s.status === 'active' ? '<em style="color:var(--accent)">live</em>' : '–');
    const startFmt = s.start_time
      ? new Date(s.start_time).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })
      : '–';
    const personLabel = (s.person_id || '').trim();
    const personCell = personLabel
      ? `<div class="session-person">${esc(personLabel)}</div>
         <div class="session-caption">${esc(s.session_id)}${s.description ? ' · ' + esc(s.description) : ''}</div>`
      : `<div class="session-person anonymous">Anonymous</div>
         <div class="session-caption">${esc(s.session_id)}${s.description ? ' · ' + esc(s.description) : ''}</div>`;
    return `<tr class="click-row" onclick="location.hash='#session/${escAttr(s.session_id)}'">
      <td class="session-cell">${personCell}</td>
      <td class="mono" style="font-size:12px;color:var(--text2)">${startFmt} · ${dur}</td>
      <td>${mlBadge}</td>
      <td class="mono">${_sigmaPill(s.session_id)}</td>
    </tr>`;
  }).join('');
}
```

- [ ] **Step 2: Delete `_mountValidationPanel()` entirely**

Remove the whole `function _mountValidationPanel() { … }` block (lines ~1013–1024). It belongs to the old inline-expand mechanism.

- [ ] **Step 3: Delete `selectSession()` and `filterSessions` references**

Remove the `function selectSession(sessionId) { … }` block (lines ~1035–1040). The new row-click goes through `location.hash` directly.

Also remove the `oninput="filterSessions()"` references — they're already gone since Task 3 replaced the HTML, but search the JS for any remaining call sites: `grep -n 'filterSessions\|selectSession\|_mountValidationPanel' static/dashboard.js`. There should be no hits after this step.

- [ ] **Step 4: Wire up filter inputs and initial load**

Find `loadSessions()` (around line 903) and replace its current body with:

```javascript
async function loadSessions() {
  const [data, quality] = await Promise.all([
    api('/sessions', 'GET'),
    api('/sessions/quality', 'GET'),
  ]);
  S.allSessions = data || [];
  S.qualitySummary = quality?.summary || null;
  S.qualityBySession = {};
  (quality?.sessions || []).forEach(q => { S.qualityBySession[q.session_id] = q; });
  if (!S.validationBySession) S.validationBySession = {};
  if (!S.alignmentBySession) S.alignmentBySession = {};
  renderQualitySummary();

  // Bulk-fetch alignment for every session in parallel so the σ filter and
  // table column have data without per-row lazy loading. Sessions with no pen
  // data return an alignment payload whose sigma is null/missing — that's the
  // "no pen" filter category. Re-applies filters when each result lands.
  const missing = S.allSessions.filter(s => !S.alignmentBySession[s.session_id]);
  Promise.all(missing.map(s =>
    api(`/sessions/${encodeURIComponent(s.session_id)}/alignment`, 'GET')
      .then(a => { if (a) S.alignmentBySession[s.session_id] = a; })
      .catch(() => {})
  )).then(() => applyFilters());

  // Restore filter UI from localStorage on first render only.
  if (!S._filtersWired) {
    const f = loadFilters();
    document.getElementById('filterQ').value = f.q;
    document.getElementById('filterMl').value = f.ml;
    document.getElementById('filterAlign').value = f.align;
    document.getElementById('filterMinFive').checked = f.minFive;
    let deb;
    const debouncedApply = () => { clearTimeout(deb); deb = setTimeout(applyFilters, 150); };
    document.getElementById('filterQ').addEventListener('input', debouncedApply);
    document.getElementById('filterMl').addEventListener('change', applyFilters);
    document.getElementById('filterAlign').addEventListener('change', applyFilters);
    document.getElementById('filterMinFive').addEventListener('change', applyFilters);
    document.getElementById('filterReset').addEventListener('click', () => {
      resetFilters();
      document.getElementById('filterQ').value = '';
      document.getElementById('filterMl').value = 'all';
      document.getElementById('filterAlign').value = 'all';
      document.getElementById('filterMinFive').checked = false;
      applyFilters();
    });
    S._filtersWired = true;
  }
  applyFilters();
}
```

- [ ] **Step 5: Smoke-test the list**

Reload, click Sessions tab. Confirm:
- 4 columns visible (Session / Start · Duration / ML Status / Alignment σ).
- Typing in the search box filters the list (debounced ~150 ms).
- Changing ML/Alignment dropdowns filters; toggling ≥ 5 min filters.
- Reload page → filter values persist.
- Click "Reset" → all four filters clear.
- Click a row → URL changes to `#session/<id>`, detail page becomes visible (stub from Task 4).

- [ ] **Step 6: Commit**

```bash
git add static/dashboard.js
git commit -m "Sessions: replace inline-expand list with 4-col triage + persistent filters"
```

---

## Task 6: JS — full detail page rendering

Replace the `openSessionDetail()` stub with the real implementation: load data, fill header/verdict, populate the 4 collapsible sections by reusing existing render functions wherever possible.

**Files:**
- Modify: `static/dashboard.js` — replace the stub from Task 4.
- Modify: `static/dashboard.js` — adapt `renderSessionValidation()` and `renderAlignment()` to read from / write to the new DOM IDs.

- [ ] **Step 1: Replace the `openSessionDetail()` stub**

Replace the stub with:

```javascript
async function openSessionDetail(sessionId) {
  S.selectedSessionId = sessionId;
  document.getElementById('detailTitle').textContent = `Session ${sessionId}`;
  document.getElementById('detailSubtitle').textContent = 'Loading…';
  document.getElementById('detailReportLink').href = `/sessions/${encodeURIComponent(sessionId)}/report?format=md`;

  // Restore section open-state from localStorage.
  document.querySelectorAll('#page-session-detail details.detail-section').forEach(d => {
    const key = `sessionDetail.section.${d.dataset.section}.open`;
    d.open = localStorage.getItem(key) === '1';
    d.addEventListener('toggle', () => {
      try { localStorage.setItem(key, d.open ? '1' : '0'); } catch {}
    }, { once: false });
  });

  // Load quality (cached) + validation + alignment in parallel.
  const [validation, alignment] = await Promise.all([
    S.validationBySession[sessionId]
      ? Promise.resolve(S.validationBySession[sessionId])
      : api(`/sessions/${encodeURIComponent(sessionId)}/validation`, 'GET'),
    S.alignmentBySession[sessionId]
      ? Promise.resolve(S.alignmentBySession[sessionId])
      : api(`/sessions/${encodeURIComponent(sessionId)}/alignment`, 'GET'),
  ]);
  if (validation) S.validationBySession[sessionId] = validation;
  if (alignment) S.alignmentBySession[sessionId] = alignment;

  // The session_id may not be in S.allSessions if filters are tight — re-fetch list if missing.
  if (!S.allSessions?.find(s => s.session_id === sessionId)) {
    const data = await api('/sessions', 'GET');
    if (data) S.allSessions = data;
  }
  const session = S.allSessions.find(s => s.session_id === sessionId) || {};
  const quality = S.qualityBySession[sessionId] || {};

  _renderDetailHeader(session, quality, alignment);
  _renderDetailStreams(session, quality);
  renderSessionValidation(sessionId);   // reuses existing impl, now wired to new IDs (see Step 3)
  renderAlignment(sessionId);            // reuses existing impl, now in the alignment section
  _renderDetailIssues(quality);
}

function _renderDetailHeader(session, quality, alignment) {
  const durationSec = session.start_time && session.end_time
    ? (new Date(session.end_time) - new Date(session.start_time)) / 1000
    : 0;
  const verdict = computeVerdict(quality, alignment, durationSec);

  const person = (session.person_id || '').trim();
  document.getElementById('detailTitle').textContent =
    `${session.session_id || '–'}${person ? ' · ' + person : ''}`;
  const startFmt = session.start_time
    ? new Date(session.start_time).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' })
    : '–';
  document.getElementById('detailSubtitle').textContent =
    `${session.description ? '"' + session.description + '" · ' : ''}${startFmt} · ${fmtDuration(Math.floor(durationSec))}`;

  const v = document.getElementById('detailVerdict');
  v.className = `verdict-badge ${verdict.level}`;
  v.textContent = verdict.label;

  const mlStatus = quality?.ml_readiness?.status || 'unknown';
  const recStatus = quality?.recording_health?.status || 'unknown';
  const sigma = alignment?.sigma_minimal_variance;

  const pillCls = (st) => st === 'ok' ? 'ok' : st === 'warn' ? 'warn' : st === 'bad' ? 'err' : '';
  const mlPill = document.getElementById('detailPillMl');
  mlPill.className = 'pill ' + pillCls(mlStatus);
  mlPill.textContent = `ML ${mlStatus}`;

  const recPill = document.getElementById('detailPillRec');
  recPill.className = 'pill ' + pillCls(recStatus);
  recPill.textContent = `Rec ${recStatus}`;

  const alignPill = document.getElementById('detailPillAlign');
  if (Number.isFinite(sigma)) {
    alignPill.className = 'pill ' + (sigma <= -3 ? 'ok' : sigma <= -2 ? 'warn' : 'err');
    alignPill.textContent = `Align σ=${sigma.toFixed(2)}`;
  } else {
    alignPill.className = 'pill';
    alignPill.textContent = 'Align —';
  }
}

function _renderDetailStreams(session, quality) {
  const watch = quality?.watch || {};
  const pen = quality?.pen || {};
  const airpods = quality?.airpods || {};
  const cov = (q) => q?.coverage_pct != null ? `${(q.coverage_pct * 100).toFixed(0)}%` : '–';
  document.getElementById('detailStreams').innerHTML = `
    <div class="drift-grid" style="grid-template-columns: repeat(3, 1fr)">
      <div class="drift-box">
        <div class="k">Watch</div>
        <div class="v">${Number(session.watch_samples || 0).toLocaleString()}</div>
        <div class="k" style="margin-top:6px">${watch.estimated_hz ? fmtHz(watch.estimated_hz) : '– Hz'} · coverage ${cov(watch)}</div>
      </div>
      <div class="drift-box">
        <div class="k">Pen</div>
        <div class="v">${Number(session.pen_samples || 0).toLocaleString()}</div>
        <div class="k" style="margin-top:6px">${pen.has_server_time ? 'wall-clock' : 'legacy'}</div>
      </div>
      <div class="drift-box">
        <div class="k">AirPods</div>
        <div class="v">${Number(session.airpods_samples || 0).toLocaleString()}</div>
        <div class="k" style="margin-top:6px">${airpods.estimated_hz ? fmtHz(airpods.estimated_hz) : '–'}</div>
      </div>
    </div>`;
}

function _renderDetailIssues(quality) {
  const ml = quality?.ml_readiness || { blockers: [], warnings: [], info: [] };
  const rec = quality?.recording_health || { blockers: [], warnings: [], info: [] };
  const all = [
    ...(ml.blockers || []).map(i => ({ ...i, sev: 'err' })),
    ...(ml.warnings || []).map(i => ({ ...i, sev: 'warn' })),
    ...(rec.blockers || []).map(i => ({ ...i, sev: 'err' })),
    ...(rec.warnings || []).map(i => ({ ...i, sev: 'warn' })),
  ];
  document.getElementById('detailIssuesCount').textContent = all.length;
  document.getElementById('detailIssues').innerHTML = all.length
    ? all.map(i => `<span class="issue-chip" title="${escAttr(i.message || i.rationale || '')}">${esc(i.code)}</span>`).join('')
    : '<span class="issue-chip">no blocking issues</span>';
  document.getElementById('detailIssuesSummary').textContent = all.length
    ? 'Hover an issue chip to see rationale. Severity is mixed: blockers are red, warnings yellow.'
    : 'Nothing flagged on this session.';
}
```

- [ ] **Step 2: Update `renderSessionValidation()` to use the new DOM IDs**

The existing function writes to `validationTitle`, `validationOverall`, `validationMlReady`, `validationRecording`, `validationPenPct`, `validationSyncDiagnostic`, `validationTimeline`, `validationSummary`, `validationIssues`. The detail page only keeps the **timeline + drift boxes** as part of the "Timeline & Drift" section — header info is now in the detail header, issues moved to the Issues section.

Replace the entire `function renderSessionValidation(sessionId) { … }` body (lines 1419–1467) with:

```javascript
function renderSessionValidation(sessionId) {
  const v = S.validationBySession[sessionId];
  if (!v) {
    document.getElementById('detailTimeline').innerHTML = '<div class="validation-note">Validation data loading…</div>';
    return;
  }
  document.getElementById('driftWatch').textContent = fmtMs(v.source_clocks?.watch_source_to_local_drift_ms);
  document.getElementById('driftPen').textContent = fmtMs(v.source_clocks?.pen_source_to_local_drift_ms);
  document.getElementById('driftRelative').textContent = fmtMs(v.source_clocks?.relative_pen_vs_watch_clock_drift_ms);
  document.getElementById('driftSyncOffset').textContent = fmtClockGap(
    v.source_clocks?.source_clock_offset_gap_ms,
    v.sync_estimate
  );
  document.getElementById('detailTimeline').innerHTML = renderTimeline(v);
}
```

- [ ] **Step 3: Confirm `renderAlignment()` still works**

The existing `renderAlignment()` writes to `alignmentSection`, `alignmentStatus`, `alignmentExplainer`, `alignDelta`, `alignSigma`, `alignStrokes`, `alignFactor`, `alignVarCanvas`, `alignTimelineCanvas`, `alignmentEmpty` — all of these IDs are preserved in the new HTML (Task 3, the `<details data-section="alignment">` body). No code changes needed.

- [ ] **Step 4: Update `loadValidationIfNeeded` / `loadAlignmentIfNeeded` — delete them**

These were only called from the old `selectSession()` flow. `openSessionDetail()` now fetches inline. Delete both functions (around lines 918–927 and 1042–1051). Re-grep to confirm nothing else calls them: `grep -n 'loadValidationIfNeeded\|loadAlignmentIfNeeded' static/dashboard.js`. Should return zero hits.

- [ ] **Step 5: Smoke-test detail page end-to-end**

Reload `http://localhost:8000`. Pick a real session (e.g. S029 if present, otherwise the latest). Click its row.

Confirm:
- URL becomes `#session/<id>`.
- Header shows session id, person, description, date+duration.
- Big verdict badge displays (Trainable/Usable/Skip) with appropriate color.
- 3 small pills underneath show ML, Rec, σ.
- All 4 sections start collapsed.
- Opening "Streams & Samples" shows three boxes.
- Opening "Timeline & Drift" renders the timeline bars and 4 drift values.
- Opening "Pen ↔ Watch Alignment" renders both Chart.js canvases (variance curve + timeline).
- Opening "Issues" shows chips matching the session's blockers/warnings.
- Reload while section is open → it stays open. Close it, reload → stays closed.
- Click "← Sessions" → returns to the list, filters intact.

- [ ] **Step 6: Commit**

```bash
git add static/dashboard.js
git commit -m "Sessions: full detail page with verdict, streams, drift, alignment, issues"
```

---

## Task 7: Cleanup — remove dead CSS & legacy inline-expand code

The new flow leaves behind some unused CSS and a few leftover artifacts (the old standalone `sessionValidationPanel`, the now-unused `.sessions-toolbar` rule, the inline detail-row rules).

**Files:**
- Modify: `dashboard.html` — strip dead CSS.
- Modify: `static/dashboard.js` — verify no `sessionValidationPanel`/`detail-row` references remain.

- [ ] **Step 1: Remove dead CSS from `dashboard.html`**

Delete these blocks:

```css
.sessions-toolbar { display: flex; gap: 10px; margin-bottom: 14px; align-items: center; }
.sessions-toolbar input { max-width: 240px; }
.sessions-toolbar .ml { margin-left: auto; }
```

And:

```css
/* ─── Inline detail row inside sessions table ──────────────── */
.sessions-table tr.detail-row > td { padding: 0 !important; background: var(--surface); border-top: none; }
.sessions-table tr.detail-row .validation-panel { margin: 0; border-radius: 0; border-left: 4px solid var(--accent); }
.sessions-table tr.detail-row .validation-panel.active { display: block; }
```

The `.validation-panel`, `.validation-metrics`, `.validation-metric` rules can stay — `renderTimeline()` still uses `.timeline-*` and the panel CSS is harmless when no element has the class.

- [ ] **Step 2: Grep for any leftover dead references**

```bash
grep -n 'sessionValidationPanel\|sessions-toolbar\|detail-row\|session-detail-mount\|sessionDetailMount' dashboard.html static/dashboard.js
```

Expected: zero hits. If any appear, delete that line / element.

- [ ] **Step 3: Run pytest to confirm no backend test broke**

```bash
pytest tests/
```

Expected: same number of tests pass as before (the backend wasn't touched, but this is a cheap safety net).

- [ ] **Step 4: Commit**

```bash
git add dashboard.html static/dashboard.js
git commit -m "Sessions: drop dead CSS + inline-expand leftovers"
```

---

## Task 8: Final smoke checklist + close

Run through the spec's manual smoke checklist on a real running server. If anything fails, fix it before declaring done.

- [ ] **Step 1: Run server**

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: Walk the checklist**

Open `http://localhost:8000`, click Sessions tab, and verify each item:

1. Sessions list renders with 4 columns; no inline expand on click.
2. Each filter persists across reload — pick "σ ≤ −3", reload, filter still applied.
3. Reset link clears all four filters and removes the `sessionsFilter.v1` key from localStorage (DevTools → Application → Local Storage).
4. Clicking a row navigates to `#session/<id>`; pressing browser Back returns to the list with filters intact.
5. Detail header shows the correct verdict for known sessions: S029 → Trainable (assuming σ ≤ −3 and ≥ 5 min); a session with sync_failed → Skip.
6. All four sections start collapsed on first visit.
7. Opening one section and reloading the page restores it open (check `sessionDetail.section.<name>.open` keys in localStorage).
8. Sessions without alignment data show "Align —" in the header pill and the Alignment-section body says "Alignment ist für diese Session nicht verfügbar."
9. The "≥ 5 min" toggle filters out short sessions correctly.
10. The MD-report link in the header downloads the per-session markdown report.

- [ ] **Step 3: If anything failed, fix it and re-commit**

For each failure, write a small follow-up commit. Don't claim done until every box is checked.

- [ ] **Step 4: Final commit (only if you made fixes)**

```bash
git add -p
git commit -m "Sessions: smoke-fix <describe>"
```

- [ ] **Step 5: Push the branch for review (or merge per repo convention)**

```bash
git push -u origin feature/adapt-web-ui
```

---

## Notes for the executing agent

- **Don't introduce a JS test framework just for this work.** The project has no JS tests; manual smoke is the contract. If you find yourself wanting one, surface it as a separate proposal — out of scope here.
- **Reuse before rewriting.** `renderTimeline`, `renderAlignment`, `_drawAlignVarianceCurve`, `_drawAlignTimeline`, `fmtDuration`, `fmtHz`, `fmtMs`, `fmtClockGap`, `fmtSec`, `scoreBadge`, `scoreTooltip`, `syncDiagnostic`, `esc`, `escAttr` already exist. Don't reimplement.
- **localStorage keys** must be exactly `sessionsFilter.v1` and `sessionDetail.section.<name>.open` (named in the spec, used by Step 2 of the smoke check). Don't drift.
- **No backend endpoints change.** If you find yourself reaching for `server.py` or `src/server/`, stop and reread the spec.
