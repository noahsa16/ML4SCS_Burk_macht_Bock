import { _fmtStripDate } from '/static/js/core/format.js';
import { S } from '/static/js/core/state.js';
import { openSessionDetail, onHide as sessionDetailOnHide } from '/static/js/pages/session_detail.js';
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
// detail page. Returns the page id to activate, or null for session-detail.
export function _routeFromHash() {
  const m = location.hash.match(/^#session\/(.+)$/);
  if (m) {
    return 'session-detail';
  }
  // Plain named page hash e.g. #recording, #sessions, #connections, #system
  const plain = location.hash.replace(/^#/, '');
  const pages = ['recording', 'sessions', 'connections', 'system'];
  if (pages.includes(plain)) return plain;
  return null;
}

// Called by the bootstrap's showPage when the session-detail route is active.
export function activateSessionDetail() {
  const m = location.hash.match(/^#session\/(.+)$/);
  if (!m) return;
  const id = decodeURIComponent(m[1]);
  updatePageStrip('sessions', `sessions / ${id}`);
  openSessionDetail(id);
}

export function closeSessionDetail() {
  if (location.hash.startsWith('#session/')) {
    location.hash = 'sessions';
  }
  sessionDetailOnHide();
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
//  RESIZE — keeps tab indicator measured correctly after layout changes
// ════════════════════════════════════════════════════════════
window.addEventListener('resize', updateTabIndicator);
