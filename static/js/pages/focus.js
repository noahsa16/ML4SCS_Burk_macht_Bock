// static/js/pages/focus.js — Focus Tracker page module
//
// Pulls /focus/today + /focus/week (server reads data/inference_log.csv),
// renders a hero number + day-timeline + week-bar chart.
//
// Reactive live-pill is fed from the per-second WS status tick (same
// payload that drives the Recording-page inference card).

import { api } from '/static/js/core/api.js';

let _mounted = false;
let _refreshTimer = null;
let _lastTodayData = null;
let _lastFetchOk = null;  // null = never fetched, true/false after first attempt

// Why: 5 s lets a fresh write-stretch surface on the page within seconds,
// not half a minute. Cheap to do (two small GETs).
const REFRESH_INTERVAL_MS = 5_000;
const DAY_MS = 24 * 60 * 60 * 1000;

// ════════════════════════════════════════════════════════════
//  FORMATTERS
// ════════════════════════════════════════════════════════════
function _fmtClockFromSeconds(secs) {
  const n = Math.max(0, Math.round(secs || 0));
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return `${h}:${String(m).padStart(2, '0')}`;
}

function _fmtMins(secs) {
  return `${Math.round((secs || 0) / 60)} min`;
}

function _fmtTimeOfDay(ts_ms) {
  if (!ts_ms) return '—';
  const d = new Date(ts_ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function _fmtRange(stretch) {
  const start = _fmtTimeOfDay(stretch.start_ms);
  const end = _fmtTimeOfDay(stretch.end_ms);
  const dur = Math.max(1, Math.round(stretch.duration_s / 60));
  return `${start} – ${end} · ${dur} min`;
}

// ════════════════════════════════════════════════════════════
//  PAGE LIFECYCLE
// ════════════════════════════════════════════════════════════
export function mount(container) {
  if (_mounted) return;
  _mounted = true;
  // Mount once; the actual data load runs from onShow (which fires
  // right after mount on first visit). Avoids a double-fetch race.
}

export function onShow() {
  _refresh();
  if (_refreshTimer) clearInterval(_refreshTimer);
  _refreshTimer = setInterval(_refresh, REFRESH_INTERVAL_MS);
  _advanceNowMarker();
}

export function onHide() {
  if (_refreshTimer) {
    clearInterval(_refreshTimer);
    _refreshTimer = null;
  }
}

export function onStatus(s) {
  _updateLivePill(s?.live_inference);
  _updateFooterModel(s?.live_inference);
  // Why: the "now" marker on the day strip should creep forward smoothly,
  // not jump in 30 s _refresh increments. Cheap: only re-positions an
  // existing div; no DOM thrash.
  _advanceNowMarker();
}

// ════════════════════════════════════════════════════════════
//  DATA REFRESH
// ════════════════════════════════════════════════════════════
async function _refresh() {
  const [today, week] = await Promise.all([
    api('/focus/today'),
    api('/focus/week'),
  ]);
  // Validate shape: an HTTP-error response from `api()` carries
  // `http_status` but none of the real fields. Treat as no-data.
  const todayOk = today && typeof today.total_writing_seconds === 'number';
  const weekOk  = week  && Array.isArray(week.days);
  _lastFetchOk = todayOk && weekOk;
  if (todayOk) _renderToday(today);
  if (weekOk)  _renderWeek(week);
  if (!todayOk && !weekOk) {
    // Nothing to render — fall back to a friendly idle layout.
    _renderEmptyShell();
  }
}

function _renderEmptyShell() {
  const clockEl = document.getElementById('focusHeroClock');
  if (clockEl) clockEl.textContent = '0:00';
  const subEls = [
    ['focusHeroMetaStretches', '—'],
    ['focusHeroMetaFirst', '—'],
    ['focusHeroMetaLast', '—'],
  ];
  for (const [id, val] of subEls) {
    const el = document.querySelector(`#${id} .focus-hero-meta-num`);
    if (el) el.textContent = val;
  }
}

// ════════════════════════════════════════════════════════════
//  TODAY — hero number + day timeline
// ════════════════════════════════════════════════════════════
function _renderToday(today) {
  _lastTodayData = today;

  const clockEl = document.getElementById('focusHeroClock');
  if (clockEl) clockEl.textContent = _fmtClockFromSeconds(today.total_writing_seconds);

  const stretches = today.stretches || [];

  const stretchesRow = document.querySelector('#focusHeroMetaStretches .focus-hero-meta-num');
  if (stretchesRow) stretchesRow.textContent = String(stretches.length);

  const firstRow = document.querySelector('#focusHeroMetaFirst .focus-hero-meta-num');
  if (firstRow) firstRow.textContent = stretches.length
    ? _fmtTimeOfDay(stretches[0].start_ms)
    : '—';

  const lastRow = document.querySelector('#focusHeroMetaLast .focus-hero-meta-num');
  if (lastRow) lastRow.textContent = stretches.length
    ? _fmtTimeOfDay(stretches[stretches.length - 1].end_ms)
    : '—';

  _renderDayStrip(today);
}

function _renderDayStrip(today) {
  const host = document.getElementById('focusDayStretches');
  const empty = document.getElementById('focusDayEmpty');
  if (!host) return;
  host.replaceChildren();

  const dayStart = today.day_start_ms;
  const stretches = today.stretches || [];

  if (!stretches.length) {
    if (empty) empty.classList.remove('is-hidden');
    _advanceNowMarker(today);
    return;
  }
  if (empty) empty.classList.add('is-hidden');

  // Position each stretch as a percentage of the 24-hour day.
  stretches.forEach((s, i) => {
    const startPct = ((s.start_ms - dayStart) / DAY_MS) * 100;
    const endPct = ((s.end_ms - dayStart) / DAY_MS) * 100;
    // Why: stretches under ~30 s become invisibly thin (0.03% wide) and
    // hurt the read of the strip. Floor visual width at ~0.5% so they
    // remain perceivable without lying about their actual duration.
    const widthPct = Math.max(0.5, endPct - startPct);

    const block = document.createElement('div');
    block.className = 'focus-day-stretch';
    block.style.left = `${startPct}%`;
    block.style.width = `${widthPct}%`;
    block.style.setProperty('--stretch-delay', `${i * 28}ms`);
    block.setAttribute('data-tooltip', _fmtRange(s));
    host.appendChild(block);
  });

  _advanceNowMarker(today);
}

function _advanceNowMarker(today = _lastTodayData) {
  const now = document.getElementById('focusDayNow');
  if (!now) return;
  if (!today) {
    now.style.display = 'none';
    return;
  }
  now.style.display = '';
  const nowMs = Date.now();
  const pct = ((nowMs - today.day_start_ms) / DAY_MS) * 100;
  if (pct < 0 || pct > 100) {
    now.style.display = 'none';
    return;
  }
  now.style.left = `${pct}%`;
}

// ════════════════════════════════════════════════════════════
//  WEEK — vertical bars
// ════════════════════════════════════════════════════════════
function _renderWeek(week) {
  const host = document.getElementById('focusWeekStrip');
  if (!host) return;

  const days = week.days || [];
  const maxSecs = Math.max(1, week.max_seconds || 0);
  let peakIdx = -1;
  let peakVal = 0;
  days.forEach((d, i) => {
    if (d.writing_seconds > peakVal) {
      peakVal = d.writing_seconds;
      peakIdx = i;
    }
  });

  host.replaceChildren();
  days.forEach((d, i) => {
    const col = document.createElement('div');
    col.className = 'focus-week-day';
    if (d.is_today) col.classList.add('is-today');
    if (!d.writing_seconds) col.classList.add('is-empty');
    if (peakIdx === i && peakVal > 0) col.classList.add('is-peak');

    const wrap = document.createElement('div');
    wrap.className = 'focus-week-bar-wrap';
    const bar = document.createElement('div');
    bar.className = 'focus-week-bar';
    // Why: empty days get a 3% ghost bar so the column has visual presence —
    // 7 invisible columns on a fresh install reads as a broken chart.
    const pct = d.writing_seconds > 0
      ? Math.max(4, (d.writing_seconds / maxSecs) * 100)
      : 3;
    bar.style.setProperty('--bar-target-h', `${pct}%`);
    bar.style.setProperty('--bar-delay', `${i * 60}ms`);
    wrap.appendChild(bar);

    const weekday = document.createElement('div');
    weekday.className = 'focus-week-weekday';
    weekday.textContent = d.weekday;

    const mins = document.createElement('div');
    mins.className = 'focus-week-mins';
    mins.textContent = d.writing_seconds > 0 ? _fmtMins(d.writing_seconds) : '—';

    const peak = document.createElement('div');
    peak.className = 'focus-week-peak-flag';
    peak.textContent = '/ peak';

    col.appendChild(wrap);
    col.appendChild(weekday);
    col.appendChild(mins);
    col.appendChild(peak);
    host.appendChild(col);
  });

  const metaEl = document.getElementById('focusWeekMeta');
  if (metaEl) {
    if (peakVal <= 0) {
      metaEl.textContent = 'no writing detected yet';
    } else {
      metaEl.textContent = `peak ${_fmtMins(peakVal)} · ${days[peakIdx].weekday}`;
    }
  }
}

// ════════════════════════════════════════════════════════════
//  LIVE PILL + FOOTER (per-tick from WS)
// ════════════════════════════════════════════════════════════
function _updateLivePill(inf) {
  const pill = document.getElementById('focusLivePill');
  if (!pill) return;
  const txt = pill.querySelector('.focus-live-text');
  if (!inf) {
    pill.setAttribute('data-state', 'idle');
    if (txt) txt.textContent = 'awaiting watch stream';
    return;
  }
  if (inf.rate_mismatch) {
    pill.setAttribute('data-state', 'idle');
    if (txt) txt.textContent = `rate mismatch · ${inf.fs_hz} vs ${inf.trained_fs_hz} Hz`;
    return;
  }
  pill.setAttribute('data-state', inf.writing ? 'writing' : 'idle');
  if (txt) {
    txt.textContent = inf.writing
      ? `writing · ${Math.round((inf.proba || 0) * 100)}%`
      : `idle · ${Math.round((inf.proba || 0) * 100)}%`;
  }
}

function _updateFooterModel(inf) {
  const el = document.getElementById('focusModelText');
  if (!el) return;
  if (!inf) {
    el.textContent = 'awaiting first inference tick';
    return;
  }
  const who = inf.person_id ? `${inf.person_id}` : 'cross-subject';
  el.textContent = `${who} · ${inf.model_id || 'model'} @ ${inf.fs_hz || '–'} Hz`;
}
