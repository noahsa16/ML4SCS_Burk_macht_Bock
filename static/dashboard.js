import * as systemPage from '/static/js/pages/system.js';
import * as connectionsPage from '/static/js/pages/connections.js';
import * as sessionsPage from '/static/js/pages/sessions.js';
import * as sessionDetailPage from '/static/js/pages/session_detail.js';
import { loadSessions } from '/static/js/pages/sessions.js';
import { openSessionDetail } from '/static/js/pages/session_detail.js';
import { esc } from '/static/js/core/dom.js';
import {
  fmtDuration, fmtNum,
  fmtClock, fmtCommand, fmtUptime,
} from '/static/js/core/format.js';
import { api, downloadDebugPackage } from '/static/js/core/api.js';
import { S, getActiveSession, getTheme, getLogRows, updateFromStatus } from '/static/js/core/state.js';
import { setTheme, toggleTheme } from '/static/js/core/theme.js';
import { setNumberSmooth, _startAnimLoop, SKEL_MIN_MS } from '/static/js/core/anim.js';
import { toast } from '/static/js/core/toast.js';
import {
  _routeFromHash, closeSessionDetail, updateTabIndicator,
  updatePageStrip, goHome, pageMeta,
} from '/static/js/core/router.js';
import { connectWs, setWsStatus } from '/static/js/core/ws.js';
import {
  handleStatus, setStatusCluster, setPill, setBadge, setHealth,
  updateChart, updatePenCanvas, clearPenPreview, drawPenCanvas,
} from '/static/js/core/status_cluster.js';

// ════════════════════════════════════════════════════════════
//  NAVIGATION
// ════════════════════════════════════════════════════════════
document.querySelectorAll('.tab').forEach(el => {
  el.addEventListener('click', () => {
    // Leaving any tab clears a session-detail route so the URL reflects the active tab.
    if (location.hash.startsWith('#session/')) {
      history.replaceState(null, '', location.pathname + location.search);
      sessionDetailPage.onHide();
      document.getElementById('page-session-detail')?.classList.remove('active');
    }
    const p = el.dataset.page;
    document.querySelectorAll('.tab').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
    document.getElementById('page-' + p).classList.add('active');
    const m = pageMeta[p];
    // pageTitle / pageSub gibt es im neuen Topbar-Layout nicht mehr —
    // der aktive Tab ist die Page-Identität.
    document.getElementById('pageTitle')?.replaceChildren(document.createTextNode(m.title));
    document.getElementById('pageSub')?.replaceChildren(document.createTextNode(m.sub));
    document.title = `${m.title} — Burk macht Bock`;
    if (p === 'sessions') sessionsPage.onShow();
    if (p === 'connections') connectionsPage.onShow();
    updatePageStrip(p);
    updateTabIndicator();
  });
});


// Status-Cluster im Topbar → springt direkt zur Connections-Page für Detail-Diagnose
document.getElementById('statusCluster')?.addEventListener('click', () => {
  document.querySelector('.tab[data-page="connections"]')?.click();
});



// Details-Toggle: Sekundär-Metriken auf einer Card ein-/ausklappen
function toggleCardDetails(btn) {
  btn.closest('.card')?.classList.toggle('expanded');
}


// ════════════════════════════════════════════════════════════
//  TIMER
// ════════════════════════════════════════════════════════════
export function startTimer() {
  S.timerInterval = setInterval(() => {
    if (!S.startTime) return;
    const elapsed = Math.floor((Date.now() - S.startTime.getTime()) / 1000);
    document.getElementById('timer').textContent = fmtDuration(elapsed);
    document.getElementById('timerLabel').textContent = `Recording session ${S.sessionId || ''}`;
  }, 1000);
}

// ════════════════════════════════════════════════════════════
//  SESSION CONTROL
// ════════════════════════════════════════════════════════════
async function toggleSession() {
  if (S.sessionActive) {
    const res = await api('/session/stop', 'POST');
    toast('Session stopped');
    if (res?.command_id) console.info('Stop command_id', res.command_id);
    S.chartMax = 0;
  } else {
    const pid = document.getElementById('personId').value.trim() || 'unknown';
    const description = document.getElementById('sessionDescription').value.trim();
    const preflight = await runStartPreflight();
    if (!preflight.canStart) return;

    const res = await api('/session/start', 'POST', {
      person_id: pid,
      description,
      force_preflight: preflight.force,
    });
    if (res?.preflight && !res.session_id) {
      showPreflightResult(res.preflight);
      return;
    }
    if (res?.session_id) toast(`▶ Session ${res.session_id} started`);
  }
}

async function runStartPreflight() {
  const preflight = await api('/session/preflight');
  if (!preflight) return { canStart: false, force: false };
  if (preflight.blockers?.length) {
    showPreflightResult(preflight);
    document.querySelector('.tab[data-page="connections"]')?.click();
    return { canStart: false, force: false };
  }
  if (preflight.warnings?.length) {
    showPreflightResult(preflight);
    const lines = preflight.warnings.map(item => `• ${item.message || item.code}`).join('\n');
    const proceed = window.confirm(`Preflight warning:\n${lines}\n\nStart session anyway?`);
    return { canStart: proceed, force: proceed };
  }
  return { canStart: true, force: false };
}

function showPreflightResult(preflight) {
  const blockers = preflight.blockers || [];
  const warnings = preflight.warnings || [];
  const first = blockers[0] || warnings[0];
  if (!first) {
    toast('Preflight OK');
    return;
  }
  toast(`${blockers.length ? 'Blocked' : 'Warning'}: ${first.code || first.message}`);
}

// ════════════════════════════════════════════════════════════
//  PEN / WATCH COMMANDS
// ════════════════════════════════════════════════════════════
async function penConnect() {
  const r = await api('/pen/connect', 'POST');
  if (r?.ok) toast('Pen logger started — switch pen on');
  else toast('⚠ ' + (r?.error || 'Error'));
}
async function penDisconnect() {
  await api('/pen/disconnect', 'POST');
  toast('Pen disconnected');
}
async function watchCmd(cmd) {
  await api(`/watch/${cmd}`, 'POST');
  toast(`Watch command: ${cmd}`);
}
async function airpodsCmd(cmd) {
  await api(`/airpods/${cmd}`, 'POST');
  toast(`AirPods command: ${cmd}`);
}

// SESSION VERDICT, FILTERS, loadSessions, applyFilters, resetFilters, _matchesFilters,
// _sigmaPill, renderSessionsList, renderQualitySummary moved to
// static/js/pages/sessions.js (Task 11).
// openSessionDetail, _renderDetailHeader, _renderDetailStreams, _renderDetailIssues,
// renderAlignment, _destroyAlignCharts, _drawAlignVarianceCurve, _drawAlignTimeline,
// renderSessionValidation, renderTimeline, pct, _alignFmtDelta moved to
// static/js/pages/session_detail.js (Task 12).

// ════════════════════════════════════════════════════════════
//  LOG RENDERING + SETTINGS
// ════════════════════════════════════════════════════════════
export function renderLogs() {
  const sampleRows = (S.sampleLog || []).slice(-S.logRows).reverse();
  const eventRows = (S.eventLog || []).slice(-S.logRows).reverse();

  document.getElementById('sampleLog').innerHTML = sampleRows.length
    ? sampleRows.map(renderSampleRow).join('')
    : '<div class="log-row sample-row"><span class="log-time">--:--:--</span><span class="sample-pill">idle</span><span class="log-msg">Waiting for pen/watch samples…</span></div>';

  document.getElementById('eventLog').innerHTML = eventRows.length
    ? eventRows.map(renderEventRow).join('')
    : '<div class="log-row"><span class="log-time">--:--:--</span><span class="log-src">server</span><span class="log-msg">Waiting for events…</span></div>';
}

function renderSampleRow(row) {
  const d = row.data || {};
  const msg = row.source === 'watch'
    ? `acc=(${fmtNum(d.ax)}, ${fmtNum(d.ay)}, ${fmtNum(d.az)}) gyro=(${fmtNum(d.rx)}, ${fmtNum(d.ry)}, ${fmtNum(d.rz)}) |a|=${fmtNum(d.acc_mag)} |r|=${fmtNum(d.gyro_mag)}`
    : `${d.dot_type || 'dot'} x=${fmtNum(d.x)} y=${fmtNum(d.y)} p=${d.pressure ?? '–'}`;
  return `<div class="log-row sample-row"><span class="log-time">${fmtClock(row.ts)}</span><span class="sample-pill">${esc(row.source || 'sample')}</span><span class="log-msg">${esc(msg)}</span></div>`;
}

function renderEventRow(row) {
  const cls = row.level === 'error' ? 'error' : (row.level === 'warn' ? 'warn' : '');
  const extra = row.data ? ` ${JSON.stringify(row.data)}` : '';
  return `<div class="log-row"><span class="log-time">${fmtClock(row.ts)}</span><span class="log-src">${esc(row.source || 'log')}</span><span class="log-msg ${cls}">${esc((row.message || '') + extra)}</span></div>`;
}

function clearVisualLogs() {
  S.sampleLog = [];
  S.eventLog = [];
  renderLogs();
}

function setLogRows(value) {
  S.logRows = Number(value) || 24;
  localStorage.setItem('logRows', String(S.logRows));
  document.getElementById('logRowsSelect').value = String(S.logRows);
  renderLogs();
}


// ════════════════════════════════════════════════════════════
//  PARTIAL INJECTION
// ════════════════════════════════════════════════════════════
function injectPartial(slot, html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  slot.replaceChildren(...parsed.body.childNodes);
}

// ════════════════════════════════════════════════════════════
//  INIT
// ════════════════════════════════════════════════════════════
document.getElementById('timer').textContent = '00:00:00';
setTheme(S.theme);
setLogRows(S.logRows);

// Initial status fetch — no previous session, prevSessionId is null
api('/status').then(s => {
  if (s) {
    const payload = { type: 'status', ...s, chart: [] };
    updateFromStatus(payload);
    handleStatus(payload, null);
  }
});

connectWs();

// Temporary eager mount — replaced by Task 14 bootstrap
fetch('/static/views/connections.html')
  .then(r => r.text())
  .then(html => {
    const slot = document.getElementById('page-connections');
    injectPartial(slot, html);
    connectionsPage.mount(slot);
  });

fetch('/static/views/sessions.html')
  .then(r => r.text())
  .then(html => {
    const slot = document.getElementById('page-sessions');
    injectPartial(slot, html);
    sessionsPage.mount(slot);
  });

fetch('/static/views/system.html')
  .then(r => r.text())
  .then(html => {
    const slot = document.getElementById('page-system');
    injectPartial(slot, html);
    systemPage.mount(slot);
  });

fetch('/static/views/session-detail.html')
  .then(r => r.text())
  .then(html => {
    const slot = document.getElementById('page-session-detail');
    injectPartial(slot, html);
    sessionDetailPage.mount(slot);
    // If the page was opened via #session/<id> before this fetch completed,
    // re-trigger routing now that the DOM is ready.
    if (location.hash.startsWith('#session/')) {
      _routeFromHash();
    }
  });

// Inline HTML onclick="..." handlers in dashboard.html still reference these as
// globals. Until the bootstrap rewrite (Task 14) replaces onclick attributes with
// addEventListener bindings, expose them on `window` explicitly so the module-scoped
// names remain reachable from the HTML.
// loadSessions is referenced from sessions.html onclick="loadSessions()" (refresh btn).
// openSessionDetail is referenced from onclick="location.hash='#session/<id>'" paths via router.
Object.assign(window, {
  goHome, toggleTheme, toggleSession, toggleCardDetails,
  penConnect, penDisconnect, watchCmd, airpodsCmd,
  clearPenPreview, clearVisualLogs, loadSessions, closeSessionDetail,
  downloadDebugPackage, setTheme, setLogRows, openSessionDetail,
});
