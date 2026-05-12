import { S, getTheme, updateFromStatus } from '/static/js/core/state.js';
import { connectWs } from '/static/js/core/ws.js';
import { setTheme, toggleTheme } from '/static/js/core/theme.js';
import { _startAnimLoop } from '/static/js/core/anim.js';
import { api, downloadDebugPackage } from '/static/js/core/api.js';
import { handleStatus, setActivePageDispatcher } from '/static/js/core/status_cluster.js';
import {
  _routeFromHash, activateSessionDetail,
  updateTabIndicator, updatePageStrip, pageMeta,
  closeSessionDetail, goHome,
} from '/static/js/core/router.js';

import * as recording      from '/static/js/pages/recording.js';
import * as sessions       from '/static/js/pages/sessions.js';
import * as sessionDetail  from '/static/js/pages/session_detail.js';
import * as connections    from '/static/js/pages/connections.js';
import * as system         from '/static/js/pages/system.js';

import { loadSessions } from '/static/js/pages/sessions.js';
import { openSessionDetail } from '/static/js/pages/session_detail.js';
import {
  toggleSession, penConnect, penDisconnect, watchCmd, airpodsCmd,
  toggleCardDetails, clearPenPreview, clearVisualLogs, setLogRows,
} from '/static/js/pages/recording.js';

// ════════════════════════════════════════════════════════════
//  PAGE REGISTRY
// ════════════════════════════════════════════════════════════
const pages = {
  recording,
  sessions,
  'session-detail': sessionDetail,
  connections,
  system,
};

const partialCache = new Map();
const mounted = new Set();
let activePage = null;

// ════════════════════════════════════════════════════════════
//  PARTIAL INJECTION
// ════════════════════════════════════════════════════════════
function injectPartial(slot, html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  slot.replaceChildren(...parsed.body.childNodes);
}

async function loadPartial(pageId) {
  if (partialCache.has(pageId)) return partialCache.get(pageId);
  const r = await fetch(`/static/views/${pageId}.html`);
  const html = await r.text();
  partialCache.set(pageId, html);
  return html;
}

// ════════════════════════════════════════════════════════════
//  PAGE SWITCHING
// ════════════════════════════════════════════════════════════
async function showPage(pageId) {
  if (activePage && pages[activePage]?.onHide) pages[activePage].onHide();

  // Toggle .page.active visibility
  document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
  const slot = document.getElementById(`page-${pageId}`);
  if (slot) slot.classList.add('active');

  // Toggle .tab.active — session-detail shares the sessions tab
  const tabPage = pageId === 'session-detail' ? 'sessions' : pageId;
  document.querySelectorAll('.tab').forEach(n =>
    n.classList.toggle('active', n.dataset.page === tabPage),
  );
  updateTabIndicator();

  // Page strip + document title
  const meta = pageMeta[tabPage] || pageMeta.recording;
  updatePageStrip(tabPage);
  document.title = `${meta.title} — Burk macht Bock`;

  // Lazy-mount on first visit
  if (slot && !mounted.has(pageId)) {
    injectPartial(slot, await loadPartial(pageId));
    pages[pageId]?.mount?.(slot);
    mounted.add(pageId);
  }

  // Session-detail needs its own activation logic (opens session from hash)
  if (pageId === 'session-detail') activateSessionDetail();

  if (pages[pageId]?.onShow) pages[pageId].onShow();
  activePage = pageId;
}

// ════════════════════════════════════════════════════════════
//  NAVIGATION
// ════════════════════════════════════════════════════════════
// Tab buttons → hash; hashchange listener drives showPage
document.querySelectorAll('.tab[data-page]').forEach(btn => {
  btn.addEventListener('click', () => {
    // Leaving a session-detail hash route — clear it so URL reflects the tab
    if (location.hash.startsWith('#session/')) {
      history.replaceState(null, '', location.pathname + location.search);
    }
    location.hash = btn.dataset.page;
  });
});

window.addEventListener('hashchange', () => {
  const pageId = _routeFromHash() || 'recording';
  showPage(pageId);
});

// Status-Cluster in topbar → jump to Connections for diagnostics
document.getElementById('statusCluster')?.addEventListener('click', () => {
  document.querySelector('.tab[data-page="connections"]')?.click();
});

// ════════════════════════════════════════════════════════════
//  ACTIVE-PAGE DISPATCHER
// ════════════════════════════════════════════════════════════
setActivePageDispatcher(payload => {
  if (activePage && pages[activePage]?.onStatus) pages[activePage].onStatus(payload);
});

// ════════════════════════════════════════════════════════════
//  INIT
// ════════════════════════════════════════════════════════════
setTheme(getTheme());

// Font-load indicator measurement after fonts are ready
if (document.fonts?.ready) {
  document.fonts.ready.then(updateTabIndicator);
}

// Initial status fetch — deferred until recording DOM is mounted (done in showPage)
// Recording page is always the first mount, so we chain the fetch after it.
const _initialPage = _routeFromHash() || 'recording';
showPage(_initialPage).then(() => {
  api('/status').then(s => {
    if (s) {
      const payload = { type: 'status', ...s, chart: [] };
      updateFromStatus(payload);
      handleStatus(payload, null);
    }
  });
});

connectWs();
_startAnimLoop();

// ════════════════════════════════════════════════════════════
//  GLOBALS — onclick= handlers in view partials
// ════════════════════════════════════════════════════════════
Object.assign(window, {
  goHome, toggleTheme, toggleSession, toggleCardDetails,
  penConnect, penDisconnect, watchCmd, airpodsCmd,
  clearPenPreview, clearVisualLogs, loadSessions, closeSessionDetail,
  downloadDebugPackage, setTheme, setLogRows, openSessionDetail,
});
