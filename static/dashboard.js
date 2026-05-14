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
import * as settings       from '/static/js/pages/settings.js';

import { loadSessions, deleteSession } from '/static/js/pages/sessions.js';
import { openSessionDetail, toggleSessionFlag } from '/static/js/pages/session_detail.js';
import {
  toggleSession, penConnect, penDisconnect, watchCmd, airpodsCmd,
  toggleCardDetails, clearPenPreview, clearVisualLogs, setLogRows,
  setPenViewMode, setRecMode,
} from '/static/js/pages/recording.js';

// ════════════════════════════════════════════════════════════
//  PAGE REGISTRY
// ════════════════════════════════════════════════════════════
const pages = {
  recording,
  sessions,
  'session-detail': sessionDetail,
  settings,
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
  // Why: in-page anchors like #sec-prefs on Settings are NOT page routes —
  // leave them alone so the browser can scroll to the section. Only act on
  // hashes that resolve to a real registered page.
  const pageId = _routeFromHash();
  if (pageId) showPage(pageId);
});

// ════════════════════════════════════════════════════════════
//  TOPBAR STATUS CLUSTER — pin-open drop-panel
// ════════════════════════════════════════════════════════════
// Hover gives a read-only peek; click toggles the panel into an
// "interaction mode" that stays open even when the mouse moves to
// the action button. Outside-click or Escape closes.
const _statusCluster = document.getElementById('statusCluster');
const _statusPanel = document.getElementById('statusHoverCard');

function _setClusterOpen(open) {
  if (!_statusCluster) return;
  _statusCluster.classList.toggle('is-open', !!open);
  _statusCluster.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (_statusPanel) _statusPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
}

_statusCluster?.addEventListener('click', (e) => {
  // Why: clicks on the action button / settings link must NOT toggle the
  // panel — they perform their own action while keeping the panel state.
  if (e.target.closest('.device-action')) return;
  if (e.target.closest('.status-hover-link')) return;
  const willOpen = !_statusCluster.classList.contains('is-open');
  _setClusterOpen(willOpen);
});

_statusCluster?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    _setClusterOpen(!_statusCluster.classList.contains('is-open'));
  } else if (e.key === 'Escape') {
    _setClusterOpen(false);
  }
});

// Outside-click closes the panel
document.addEventListener('click', (e) => {
  if (!_statusCluster?.classList.contains('is-open')) return;
  if (e.target.closest('#statusCluster')) return;
  _setClusterOpen(false);
});

// Escape closes
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && _statusCluster?.classList.contains('is-open')) {
    _setClusterOpen(false);
  }
});

// Pen action button — calls connect/disconnect based on current mode.
// The button stays inside the panel; we keep the panel open so the user
// sees the state transition (off → searching → on).
const _penAction = document.getElementById('hoverPenAction');
_penAction?.addEventListener('click', async (e) => {
  e.stopPropagation();
  const mode = _penAction.dataset.mode;
  if (mode === 'on' || mode === 'searching') {
    await penDisconnect();
  } else {
    await penConnect();
  }
});

// Settings link inside the panel — close panel before navigation.
document.getElementById('statusHoverSettingsLink')?.addEventListener('click', () => {
  _setClusterOpen(false);
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
  clearPenPreview, clearVisualLogs, loadSessions, deleteSession, closeSessionDetail,
  downloadDebugPackage, setTheme, setLogRows, openSessionDetail,
  setPenViewMode, toggleSessionFlag, setRecMode,
});
