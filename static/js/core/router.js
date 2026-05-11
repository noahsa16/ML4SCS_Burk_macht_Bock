import { _fmtStripDate } from '/static/js/core/format.js';
import { S } from '/static/js/core/state.js';

// Why: openSessionDetail stays in dashboard.js until Task 12.
import { openSessionDetail } from '/static/dashboard.js';
// Temporary: loadSessions moved to pages/sessions.js in Task 11.
import { loadSessions } from '/static/js/pages/sessions.js';

// ════════════════════════════════════════════════════════════
//  PAGE METADATA
// ════════════════════════════════════════════════════════════
export const pageMeta = {
  recording:   { title: 'Live Recording',   sub: 'Pen + Watch data capture',                       strip: 'live capture' },
  sessions:    { title: 'Session History',  sub: 'All recorded sessions',                          strip: 'session index' },
  connections: { title: 'Connections',      sub: 'Device & server management',                     strip: 'connectivity' },
  system:      { title: 'System & Schema',  sub: 'Data structure · API reference · Project info',  strip: 'system & schema' },
};

// ════════════════════════════════════════════════════════════
//  PAGE STRIP
// ════════════════════════════════════════════════════════════
export function updatePageStrip(page, customLabel) {
  const dateEl = document.getElementById('pageStripDate');
  const labelEl = document.getElementById('pageStripLabel');
  if (!dateEl || !labelEl) return;
  dateEl.textContent = _fmtStripDate();
  labelEl.textContent = customLabel || pageMeta[page]?.strip || page;
}

// ════════════════════════════════════════════════════════════
//  TAB INDICATOR
// ════════════════════════════════════════════════════════════
// Slidender Tab-Underline: misst Position+Breite des aktiven Tabs und
// translatet ein einzelnes Indicator-Element dahin. CSS macht den Slide.
export function updateTabIndicator() {
  const indicator = document.getElementById('tabIndicator');
  const active = document.querySelector('.tab.active');
  if (!indicator || !active) return;
  const parentRect = active.parentElement.getBoundingClientRect();
  const tabRect = active.getBoundingClientRect();
  // Insets entsprechen dem alten ::after left:14px / right:14px Padding
  const inset = 14;
  const left = tabRect.left - parentRect.left + inset;
  const width = Math.max(0, tabRect.width - inset * 2);
  indicator.style.transform = `translateX(${left}px)`;
  indicator.style.width = `${width}px`;
  indicator.classList.add('ready');
}

// ════════════════════════════════════════════════════════════
//  HASH ROUTING
// ════════════════════════════════════════════════════════════
// Hash routing: only one route shape — #session/<id> opens the
// detail page. Empty hash returns to whichever tab was active.
export function _routeFromHash() {
  const m = location.hash.match(/^#session\/(.+)$/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
    document.getElementById('page-session-detail').classList.add('active');
    document.querySelectorAll('.tab').forEach(n => n.classList.toggle('active', n.dataset.page === 'sessions'));
    updateTabIndicator();
    updatePageStrip('sessions', `sessions / ${id}`);
    openSessionDetail(id);
    return;
  }
  // No detail route — make sure detail page is hidden if it was open.
  document.getElementById('page-session-detail')?.classList.remove('active');
}

export function closeSessionDetail() {
  if (location.hash.startsWith('#session/')) {
    history.replaceState(null, '', location.pathname + location.search);
  }
  document.getElementById('page-session-detail').classList.remove('active');
  document.getElementById('page-sessions').classList.add('active');
  updatePageStrip('sessions');
  if (!S._filtersWired) loadSessions();
}

// ════════════════════════════════════════════════════════════
//  HOME NAVIGATION
// ════════════════════════════════════════════════════════════
// Brand-Klick → zurück zur Recording-Page (Home-Behavior)
export function goHome() {
  document.querySelector('.tab[data-page="recording"]')?.click();
}

// ════════════════════════════════════════════════════════════
//  INIT (fires at module-load time)
// ════════════════════════════════════════════════════════════
window.addEventListener('hashchange', _routeFromHash);
window.addEventListener('load', _routeFromHash);
// Initial Page-Strip-Befüllung (vor erstem Tab-Klick). Wenn ein
// #session/<id> Hash bereits gesetzt ist, übernimmt _routeFromHash.
if (!location.hash.startsWith('#session/')) {
  updatePageStrip('recording');
}

// Initial nach Font-Load (sonst stimmt die Breite nicht), und bei Resize
window.addEventListener('load', () => requestAnimationFrame(updateTabIndicator));
if (document.fonts?.ready) {
  document.fonts.ready.then(updateTabIndicator);
}
window.addEventListener('resize', updateTabIndicator);
