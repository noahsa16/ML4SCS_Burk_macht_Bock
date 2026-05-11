// static/js/pages/sessions.js — Sessions page module
//
// openSessionDetail lives in pages/session_detail.js; row clicks use
// onclick="location.hash='#session/<id>'" which triggers router.js
// _routeFromHash → openSessionDetail; no direct import needed here.

import { api, apiResult } from '/static/js/core/api.js';
import { esc, escAttr } from '/static/js/core/dom.js';
import { fmtDuration, scoreBadge } from '/static/js/core/format.js';
import { S } from '/static/js/core/state.js';
import { renderState } from '/static/js/core/states.js';

let _mounted = false;

// ════════════════════════════════════════════════════════════
//  SESSION VERDICT — single 3-level summary used by both
//  the triage list (filter target) and the detail page header.
// ════════════════════════════════════════════════════════════
// Thresholds match docs/superpowers/specs/2026-05-11-sessions-tab-redesign-design.md
// and src/training docs in CLAUDE.md (σ ≤ -3 trainable, ≥ 5 min within-session).
const VERDICT_TRAINABLE = 'trainable';
const VERDICT_USABLE    = 'usable';
const VERDICT_SKIP      = 'skip';

export function computeVerdict(quality, alignment, durationSec) {
  const ml = quality?.ml_readiness?.status || quality?.quality || 'unknown';
  const issues = [
    ...(quality?.ml_readiness?.blockers || []),
    ...(quality?.recording_health?.blockers || []),
  ].map(i => i.code);
  if (ml === 'bad' || issues.includes('sync_failed') || issues.includes('streams_do_not_overlap')) {
    return { level: VERDICT_SKIP, label: 'Skip' };
  }
  const sigma = alignment?.sigma;
  const dur = Number(durationSec || 0);
  if (ml === 'ok' && Number.isFinite(sigma) && sigma <= -3 && dur >= 300) {
    return { level: VERDICT_TRAINABLE, label: 'Trainable' };
  }
  return { level: VERDICT_USABLE, label: 'Usable' };
}

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

export async function loadSessions() {
  const [sessionsR, qualityR] = await Promise.all([
    apiResult('/sessions', 'GET'),
    apiResult('/sessions/quality', 'GET'),
  ]);
  if (!sessionsR.ok || !qualityR.ok) {
    _renderSessionsError(sessionsR.ok ? qualityR.error : sessionsR.error);
    return;
  }
  const data = sessionsR.data;
  const quality = qualityR.data;
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
    api('/sessions/' + encodeURIComponent(s.session_id) + '/alignment', 'GET')
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
  const sigma = a?.sigma;
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
  // Active-Filter-Hinweis: Inputs mit Non-Default kriegen Accent-Border (CSS handhabt das via .is-active)
  document.getElementById('filterQ').classList.toggle('is-active', filters.q !== '');
  document.getElementById('filterMl').classList.toggle('is-active', filters.ml !== 'all');
  document.getElementById('filterAlign').classList.toggle('is-active', filters.align !== 'all');
  const rows = (S.allSessions || []).filter(s => _matchesFilters(s, S.qualityBySession[s.session_id], filters));
  renderSessionsList(rows);
}

function _sigmaPill(sessionId) {
  const a = S.alignmentBySession?.[sessionId];
  const sigma = a?.sigma;
  if (!Number.isFinite(sigma)) {
    if (a?.status === 'failed') return '<span class="status-badge badge-err">failed</span>';
    return '<span class="mono" style="color:var(--text3)">—</span>';
  }
  const cls = sigma <= -3 ? 'badge-ok' : sigma <= -2 ? 'badge-warn' : 'badge-err';
  return '<span class="status-badge ' + cls + '">' + sigma.toFixed(2) + '</span>';
}

function _renderSessionsError(err) {
  const tbody = document.getElementById('sessionsBody');
  if (!tbody) return;
  const row = document.createElement('tr');
  const cell = document.createElement('td');
  cell.colSpan = 4;
  row.appendChild(cell);
  tbody.replaceChildren(row);
  const isNet = err?.kind === 'network';
  renderState(cell, 'error', {
    title: isNet ? 'Couldn’t load sessions' : 'Server error',
    hint: isNet
      ? 'Server didn’t respond. Check your connection or try again.'
      : `The server returned ${err?.status || 'an error'}${err?.message ? ': ' + err.message : ''}.`,
    action: { label: 'retry', onClick: loadSessions },
  });
}

function renderSessionsList(rows) {
  const tbody = document.getElementById('sessionsBody');
  if (!tbody) return;
  if (!rows.length) {
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
      ? '<div class="session-person">' + esc(personLabel) + '</div>'
        + '<div class="session-caption">' + esc(s.session_id) + (s.description ? ' · ' + esc(s.description) : '') + '</div>'
      : '<div class="session-person anonymous">Anonymous</div>'
        + '<div class="session-caption">' + esc(s.session_id) + (s.description ? ' · ' + esc(s.description) : '') + '</div>';
    return '<tr class="click-row" onclick="location.hash=\'#session/' + escAttr(s.session_id) + '\'">'
      + '<td class="session-cell">' + personCell + '</td>'
      + '<td class="mono" style="font-size:12px;color:var(--text2)">' + startFmt + ' · ' + dur + '</td>'
      + '<td>' + mlBadge + '</td>'
      + '<td class="mono">' + _sigmaPill(s.session_id) + '</td>'
      + '</tr>';
  }).join('');
}

function renderQualitySummary() {
  const summary = S.qualitySummary || { total: 0, ok: 0, warn: 0, bad: 0 };
  const ml = summary.ml_readiness || summary;
  const tot = document.getElementById('qualityTotal');
  const ok = document.getElementById('qualityOk');
  const warn = document.getElementById('qualityWarn');
  const bad = document.getElementById('qualityBad');
  if (tot) tot.textContent = summary.total ?? 0;
  if (ok) ok.textContent = ml.ok ?? 0;
  if (warn) warn.textContent = ml.warn ?? 0;
  if (bad) bad.textContent = ml.bad ?? 0;
  renderState(document.getElementById('healthGridLoading'), 'clear');
}

// ════════════════════════════════════════════════════════════
//  PAGE LIFECYCLE
// ════════════════════════════════════════════════════════════
export function mount(container) {
  if (_mounted) return;
  // Why: filter listeners are wired lazily inside loadSessions() on first call
  // (S._filtersWired guard). No additional one-time DOM wiring needed here;
  // the refresh button uses onclick="loadSessions()" exposed via window.
  _mounted = true;
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
}

export function onStatus(payload) {
  // Why: the session-just-stopped auto-refresh is handled in ws.js's
  // msg.type === 'stop' branch, which already calls loadSessions() when the
  // sessions page is active. No status-tick logic needed here.
}

export function onShow() {
  loadSessions();
}

export function onHide() {
  // No rAF loops or timers to clean up.
}
