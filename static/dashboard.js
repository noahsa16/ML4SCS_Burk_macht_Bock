import * as systemPage from '/static/js/pages/system.js';
import * as connectionsPage from '/static/js/pages/connections.js';
import * as sessionsPage from '/static/js/pages/sessions.js';
import * as sessionDetailPage from '/static/js/pages/session_detail.js';
import * as recordingPage from '/static/js/pages/recording.js';
import { loadSessions } from '/static/js/pages/sessions.js';
import { openSessionDetail } from '/static/js/pages/session_detail.js';
import {
  toggleSession, penConnect, penDisconnect, watchCmd, airpodsCmd,
  toggleCardDetails, clearPenPreview, clearVisualLogs, setLogRows,
} from '/static/js/pages/recording.js';
import { api, downloadDebugPackage } from '/static/js/core/api.js';
import { S, getActiveSession, getTheme, getLogRows, updateFromStatus } from '/static/js/core/state.js';
import { setTheme, toggleTheme } from '/static/js/core/theme.js';
import { setNumberSmooth, _startAnimLoop, SKEL_MIN_MS } from '/static/js/core/anim.js';
import {
  _routeFromHash, closeSessionDetail, updateTabIndicator,
  updatePageStrip, goHome, pageMeta,
} from '/static/js/core/router.js';
import { connectWs, setWsStatus } from '/static/js/core/ws.js';
import {
  handleStatus, setStatusCluster, setPill, setBadge, setHealth,
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



// toggleSession, runStartPreflight, showPreflightResult, penConnect, penDisconnect,
// watchCmd, airpodsCmd, startTimer, toggleCardDetails, renderLogs, renderSampleRow,
// renderEventRow, clearVisualLogs, setLogRows, updateChart, updatePenCanvas,
// clearPenPreview, drawPenCanvas moved to static/js/pages/recording.js (Task 13).
//
// SESSION VERDICT, FILTERS, loadSessions, applyFilters, resetFilters, _matchesFilters,
// _sigmaPill, renderSessionsList, renderQualitySummary moved to
// static/js/pages/sessions.js (Task 11).
// openSessionDetail, _renderDetailHeader, _renderDetailStreams, _renderDetailIssues,
// renderAlignment, _destroyAlignCharts, _drawAlignVarianceCurve, _drawAlignTimeline,
// renderSessionValidation, renderTimeline, pct, _alignFmtDelta moved to
// static/js/pages/session_detail.js (Task 12).

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
setTheme(S.theme);
connectWs();

// Temporary eager mount — replaced by Task 14 bootstrap
fetch('/static/views/recording.html')
  .then(r => r.text())
  .then(html => {
    const slot = document.getElementById('page-recording');
    injectPartial(slot, html);
    recordingPage.mount(slot);
    // Initial status fetch deferred until recording DOM exists so that
    // recordingPage.onStatus can safely touch all recording-page elements.
    api('/status').then(s => {
      if (s) {
        const payload = { type: 'status', ...s, chart: [] };
        updateFromStatus(payload);
        handleStatus(payload, null);
      }
    });
  });

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

// Inline HTML onclick="..." handlers in recording.html and other views still
// reference these as globals. Until the bootstrap rewrite (Task 14) replaces
// onclick attributes with addEventListener bindings, expose them on `window`
// explicitly so the module-scoped names remain reachable from the HTML.
// loadSessions is referenced from sessions.html onclick="loadSessions()" (refresh btn).
// openSessionDetail is referenced from onclick="location.hash='#session/<id>'" paths via router.
Object.assign(window, {
  goHome, toggleTheme, toggleSession, toggleCardDetails,
  penConnect, penDisconnect, watchCmd, airpodsCmd,
  clearPenPreview, clearVisualLogs, loadSessions, closeSessionDetail,
  downloadDebugPackage, setTheme, setLogRows, openSessionDetail,
});
