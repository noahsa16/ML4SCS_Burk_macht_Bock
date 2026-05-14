// static/js/pages/recording.js — Recording page module
//
// Owns: chart, pen canvas, timer, session control, logs rendering.
// Chart and pen canvas were previously in status_cluster.js (Task 8 note);
// they move here in Task 13 so status_cluster.js has no Recording-page DOM deps.

import { api } from '/static/js/core/api.js';
import { esc } from '/static/js/core/dom.js';
import { fmtDuration, fmtNum, fmtClock, fmtHz } from '/static/js/core/format.js';
import { S } from '/static/js/core/state.js';
import { setNumberSmooth } from '/static/js/core/anim.js';
import { toast } from '/static/js/core/toast.js';
import { renderState } from '/static/js/core/states.js';
import { renderStudyView } from '/static/js/pages/recording-study.js';

// ════════════════════════════════════════════════════════════
//  STUDY MODE — toggle + protocol picker
// ════════════════════════════════════════════════════════════
let _recMode = 'free';
let _protocolsLoaded = false;

export function setRecMode(mode) {
  _recMode = (mode === 'study') ? 'study' : 'free';
  document.querySelectorAll('.rec-mode-opt').forEach((b) => {
    const isActive = b.dataset.mode === _recMode;
    b.classList.toggle('is-active', isActive);
    b.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
  const isStudy = _recMode === 'study';
  const protoField = document.getElementById('protocolField');
  if (protoField) protoField.style.display = isStudy ? '' : 'none';
  const testField = document.getElementById('testModeField');
  if (testField) testField.style.display = isStudy ? '' : 'none';
  // Toggle grid-column class on the controls stripe so the protocol field
  // gets a real third column instead of relying on `:has()` selector hacks.
  const controls = document.querySelector('.rec-console-controls');
  if (controls) controls.classList.toggle('has-protocol', isStudy);
  const btnLabel = document.querySelector('#sessionBtn .rec-action-btn-label');
  if (btnLabel && !S.sessionActive) {
    btnLabel.textContent = (_recMode === 'study') ? 'START STUDY' : 'START';
  }
  if (_recMode === 'study') _ensureProtocolsLoaded();
}

async function _ensureProtocolsLoaded() {
  if (_protocolsLoaded) return;
  const list = await api('/study/protocols');
  const sel = document.getElementById('protocolSelect');
  if (!sel || !Array.isArray(list)) return;
  sel.replaceChildren();
  for (const p of list) {
    const opt = document.createElement('option');
    opt.value = String(p.id);
    opt.textContent = String(p.name);
    sel.appendChild(opt);
  }
  _protocolsLoaded = true;
}

let _mounted = false;

// ════════════════════════════════════════════════════════════
//  CHART
// ════════════════════════════════════════════════════════════
let _imuChart = null;

const _smoothFmt = {
  hz: (v) => v > 0 ? `${v.toFixed(v >= 10 ? 1 : 2)} Hz` : '– Hz',
  count: (v) => Math.round(v).toLocaleString('de-DE'),
  decimal3: (v) => v.toFixed(3),
  pct: (v) => `${Math.round(v)}%`,
};

function _initChart() {
  const canvas = document.getElementById('imuChart');
  if (!canvas) return;
  const chartCtx = canvas.getContext('2d');
  _imuChart = new Chart(chartCtx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: '|a|',
        data: [],
        borderColor: 'oklch(0.595 0.165 43)',
        backgroundColor: 'rgba(229, 126, 60, 0.12)',
        borderWidth: 1.8,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.3,
        fill: 'origin',
      }, {
        label: '|r|',
        data: [],
        borderColor: 'oklch(0.720 0.135 88)',
        backgroundColor: 'rgba(196, 156, 30, 0.12)',
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.3,
        fill: 'origin',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          ticks: {
            maxTicksLimit: 7,
            color: 'oklch(0.650 0.018 58)',
            font: { family: "'IBM Plex Mono', monospace", size: 10 },
            callback: (_, i, arr) => {
              const sec = -(arr.length - 1 - i);
              return sec === 0 ? 'now' : sec + 's';
            }
          },
          grid: { color: 'oklch(0.880 0.018 72)' },
        },
        y: {
          min: 0,
          ticks: {
            color: 'oklch(0.650 0.018 58)',
            font: { family: "'IBM Plex Mono', monospace", size: 10 },
            maxTicksLimit: 5,
          },
          grid: { color: 'oklch(0.880 0.018 72)' },
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'oklch(0.175 0.025 55)',
          titleFont: { family: "'IBM Plex Mono', monospace", size: 11 },
          bodyFont: { family: "'IBM Plex Mono', monospace", size: 11 },
          callbacks: {
            title: (items) => items[0].label + 's',
            label: (item) => ` ${item.dataset.label} = ${(item.raw || 0).toFixed(3)}`,
          }
        }
      }
    },
    plugins: [{
      id: 'writingBands',
      beforeDatasetsDraw(chart) {
        const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
        if (!x || !S.chartBuffer.length) return;
        ctx.save();
        S.chartBuffer.forEach((pt, i) => {
          if (!pt.pen_writing) return;
          const xPos = x.getPixelForValue(i);
          const nextX = x.getPixelForValue(i + 1);
          ctx.fillStyle = 'oklch(0.580 0.130 148 / 0.18)';
          ctx.fillRect(xPos, top, (nextX || xPos + 8) - xPos, bottom - top);
        });
        ctx.restore();
      }
    }]
  });
}

export function updateChart(chartPts) {
  if (!chartPts || !chartPts.length || !_imuChart) return;
  chartPts.forEach(pt => {
    if (!S.chartBuffer.find(b => b.t === pt.t)) {
      S.chartBuffer.push(pt);
    }
  });
  if (S.chartBuffer.length > 60) S.chartBuffer = S.chartBuffer.slice(-60);

  const accVals = S.chartBuffer.map(b => Number(b.acc_mag ?? b.mag ?? 0));
  const gyroVals = S.chartBuffer.map(b => Number(b.gyro_mag ?? 0));
  _imuChart.data.labels = S.chartBuffer.map((_, i) => i);
  _imuChart.data.datasets[0].data = accVals;
  _imuChart.data.datasets[1].data = gyroVals;
  _imuChart.update('none');

  const curAcc = accVals[accVals.length - 1] || 0;
  const curGyro = gyroVals[gyroVals.length - 1] || 0;
  S.chartMax = Math.max(S.chartMax, ...accVals, ...gyroVals);
  const writePct = S.chartBuffer.length
    ? Math.round(S.chartBuffer.filter(b => b.pen_writing).length / S.chartBuffer.length * 100)
    : 0;

  setNumberSmooth('statMag', curAcc, { format: _smoothFmt.decimal3 });
  setNumberSmooth('statGyro', curGyro, { format: _smoothFmt.decimal3 });
  setNumberSmooth('statWritePct', writePct, { format: _smoothFmt.pct });
}

// ════════════════════════════════════════════════════════════
//  PEN HANDWRITING CANVAS
// ════════════════════════════════════════════════════════════
let _penCanvas = null;
let _penCtx = null;
let _penSeenTs = new Set();

export function updatePenCanvas(newDots) {
  if (!newDots || !newDots.length || !_penCanvas) return;

  const dotKey = (d) => `${d.ts ?? ''}_${d.t ?? ''}_${d.x}_${d.y}`;
  let added = 0;
  for (const d of newDots) {
    const key = dotKey(d);
    if (_penSeenTs.has(key)) continue;
    _penSeenTs.add(key);
    S.penDotBuffer.push(d);
    added++;
  }
  if (!added) return;

  const MAX_DOTS = 2500;
  if (S.penDotBuffer.length > MAX_DOTS) {
    const dropped = S.penDotBuffer.splice(0, S.penDotBuffer.length - MAX_DOTS);
    dropped.forEach(d => _penSeenTs.delete(dotKey(d)));
  }

  // Track which physical page is being written on right now — last
  // dot's Ncode IDs win. Updates the page-info pill in the UI.
  const last = S.penDotBuffer[S.penDotBuffer.length - 1];
  const lastPage = _dotPageId(last);
  if (lastPage && !_samePage(_penCurrentPage, lastPage)) {
    _penCurrentPage = lastPage;
  }

  drawPenCanvas();
}

// Sliding view: only the last N dots count for the visible bbox so the
// preview doesn't slowly zoom out as more is written. Tune as needed —
// 600 ≈ a few seconds of fast writing at ~80 Hz pen rate.
const PEN_VIEW_WINDOW = 600;

// Two viewing modes for the handwriting preview:
//   'live' — sliding window, follows the most recent strokes (default)
//   'page' — full current Ncode page, lets the user explore what was written
let _penViewMode = 'live';
// Latest physical-page identity, derived from the Ncode IDs each dot
// carries (section / owner / note / page). When the user turns to a new
// page, this auto-updates so live view follows them.
let _penCurrentPage = null;

function _dotPageId(d) {
  // Why: pen_logger emits these as ints; treat undefined / 0 as missing.
  if (d == null) return null;
  if (d.section == null && d.owner == null && d.note == null && d.page == null) return null;
  return {
    section: d.section ?? 0,
    owner:   d.owner   ?? 0,
    note:    d.note    ?? 0,
    page:    d.page    ?? 0,
  };
}

function _samePage(a, b) {
  if (!a || !b) return false;
  return a.section === b.section && a.owner === b.owner
    && a.note === b.note && a.page === b.page;
}

function _computePenBoundsFrom(dots) {
  if (!dots.length) return null;
  let minX = dots[0].x, maxX = dots[0].x, minY = dots[0].y, maxY = dots[0].y;
  for (let i = 1; i < dots.length; i++) {
    const d = dots[i];
    if (d.x < minX) minX = d.x;
    if (d.x > maxX) maxX = d.x;
    if (d.y < minY) minY = d.y;
    if (d.y > maxY) maxY = d.y;
  }
  return { minX, maxX, minY, maxY };
}

export function setPenViewMode(mode) {
  _penViewMode = mode === 'page' ? 'page' : 'live';
  document.querySelectorAll('.rec-pen-mode-opt').forEach(b => {
    b.classList.toggle('is-active', b.dataset.mode === _penViewMode);
    b.setAttribute('aria-pressed', b.dataset.mode === _penViewMode ? 'true' : 'false');
  });
  drawPenCanvas();
}

export function clearPenPreview() {
  S.penDotBuffer = [];
  S.penBounds = null;
  _penSeenTs = new Set();
  _penCurrentPage = null;
  drawPenCanvas();
  const info = document.getElementById('penCanvasInfo');
  if (info) info.textContent = 'Cleared - waiting for new pen data';
}

export function drawPenCanvas() {
  if (!_penCanvas || !_penCtx) return;
  const canvas = _penCanvas;
  const ctx = _penCtx;
  const dpr = window.devicePixelRatio || 1;
  // Read both dimensions from the actual rendered element so the canvas
  // fills whatever the parent panel gives us (no hard-coded 200 height).
  const cssW = canvas.clientWidth || canvas.offsetWidth || 600;
  const cssH = canvas.clientHeight || canvas.offsetHeight || 200;
  const penCanvasEmpty = document.getElementById('penCanvasEmpty');
  if (S.penDotBuffer.length > 0) {
    renderState(penCanvasEmpty, 'clear');
  } else {
    renderState(penCanvasEmpty, 'empty', {
      title: 'Waiting for pen strokes',
      hint: 'Connect the Smart Pen, start a session, and write — strokes will appear here in real time.',
    });
  }

  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    // Leave the inline style.height alone — CSS controls layout height.
  }

  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  if (!S.penDotBuffer.length) {
    ctx.restore();
    return;
  }

  // Restrict the view to the dots of the page the user is currently
  // writing on (or, if no Ncode IDs yet, the whole buffer).
  const pageDots = _penCurrentPage
    ? S.penDotBuffer.filter(d => _samePage(_dotPageId(d), _penCurrentPage))
    : S.penDotBuffer;

  // Mode picks the slicing strategy:
  //   live → last PEN_VIEW_WINDOW dots (scrolling notebook view)
  //   page → ALL dots on the current page (zoomed-out exploration)
  const viewDots = _penViewMode === 'page'
    ? pageDots
    : (pageDots.length > PEN_VIEW_WINDOW
        ? pageDots.slice(-PEN_VIEW_WINDOW)
        : pageDots);
  if (!viewDots.length) { ctx.restore(); return; }
  const bounds = _computePenBoundsFrom(viewDots);
  if (!bounds) { ctx.restore(); return; }
  S.penBounds = bounds;   // kept on state so meta-line can still report it
  const { minX, maxX, minY, maxY } = bounds;
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const pad = 20;
  const scaleX = (cssW - pad * 2) / rangeX;
  const scaleY = (cssH - pad * 2) / rangeY;
  const scale = Math.min(scaleX, scaleY);
  const drawW = rangeX * scale;
  const drawH = rangeY * scale;
  const ox = pad + (cssW - pad * 2 - drawW) / 2;
  const oy = pad + (cssH - pad * 2 - drawH) / 2;

  const toX = (x) => ox + (x - minX) * scale;
  const toY = (y) => oy + (y - minY) * scale;

  const inkColor = S.theme === 'dark' ? 'oklch(0.87 0.010 80)' : 'oklch(0.22 0.025 55)';
  ctx.strokeStyle = inkColor;
  ctx.fillStyle = inkColor;
  ctx.lineWidth = 2.0;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  let inStroke = false;
  for (const dot of viewDots) {
    const cx = toX(dot.x);
    const cy = toY(dot.y);
    if (dot.t === 'PEN_DOWN') {
      if (inStroke) ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      inStroke = true;
    } else if (dot.t === 'PEN_MOVE') {
      if (!inStroke) {
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        inStroke = true;
      } else {
        ctx.lineTo(cx, cy);
      }
    } else if (dot.t === 'PEN_UP') {
      if (inStroke) { ctx.lineTo(cx, cy); ctx.stroke(); }
      inStroke = false;
    }
  }
  if (inStroke) ctx.stroke();

  // Why: must iterate viewDots (not the whole buffer) — otherwise old
  // strokes that scrolled out of the live window (or are on another page)
  // still leak in as 1px ghost dots, since their x/y get mapped through
  // bounds computed from viewDots. That's what made completed letters
  // appear as point clouds without their connecting strokes.
  for (const dot of viewDots) {
    ctx.beginPath();
    ctx.arc(toX(dot.x), toY(dot.y), 1.0, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();

  const moveDots = S.penDotBuffer.filter(d => d.t !== 'PEN_UP').length;
  const info = document.getElementById('penCanvasInfo');
  if (info) info.textContent =
    `${moveDots} ink dots · x ${minX.toFixed(1)}–${maxX.toFixed(1)} · y ${minY.toFixed(1)}–${maxY.toFixed(1)}`;

  // Visible page-info pill — only show when we have Ncode IDs from a real dot
  const pill = document.getElementById('penPagePill');
  if (pill) {
    if (_penCurrentPage) {
      pill.textContent = `p. ${_penCurrentPage.page} · note ${_penCurrentPage.note}`;
      pill.style.display = '';
    } else {
      pill.style.display = 'none';
    }
  }
}

// ════════════════════════════════════════════════════════════
//  TIMER
// ════════════════════════════════════════════════════════════
export function startTimer() {
  S.timerInterval = setInterval(() => {
    if (!S.startTime) return;
    const elapsed = Math.floor((Date.now() - S.startTime.getTime()) / 1000);
    const timerEl = document.getElementById('timer');
    if (timerEl) timerEl.textContent = fmtDuration(elapsed);
    const labelEl = document.getElementById('timerLabel');
    if (labelEl) labelEl.textContent = `Recording session ${S.sessionId || ''}`;
  }, 1000);
}

// ════════════════════════════════════════════════════════════
//  SESSION CONTROL
// ════════════════════════════════════════════════════════════
export async function toggleSession() {
  if (S.sessionActive) {
    const res = await api('/session/stop', 'POST');
    toast('Session stopped');
    if (res?.command_id) console.info('Stop command_id', res.command_id);
    S.chartMax = 0;
    return;
  }

  const pid = document.getElementById('personId').value.trim() || 'unknown';
  const description = document.getElementById('sessionDescription').value.trim();
  const preflight = await runStartPreflight();
  if (!preflight.canStart) return;

  if (_recMode === 'study') {
    const protocolId = document.getElementById('protocolSelect')?.value || 'v1';
    const testMode = document.getElementById('testModeCheck')?.checked === true;
    const res = await api('/study/start', 'POST', {
      protocol_id: protocolId,
      person_id: pid,
      description,
      force_preflight: preflight.force,
      test_mode: testMode,
    });
    if (res?.preflight && !res.session_id) {
      showPreflightResult(res.preflight);
      return;
    }
    if (res?.session_id) {
      const n = res.schedule?.length ?? 0;
      const tm = res.test_mode ? ' · TEST' : '';
      toast(`Study ${res.session_id} started (${n} slots${tm})`);
    }
    return;
  }

  // free mode (legacy path)
  const res = await api('/session/start', 'POST', {
    person_id: pid,
    description,
    force_preflight: preflight.force,
  });
  if (res?.preflight && !res.session_id) {
    showPreflightResult(res.preflight);
    return;
  }
  if (res?.session_id) toast(`Recording session ${res.session_id} started`);
}

async function runStartPreflight() {
  const preflight = await api('/session/preflight');
  if (!preflight) return { canStart: false, force: false };
  if (preflight.blockers?.length) {
    showPreflightResult(preflight);
    document.querySelector('.tab[data-page="settings"]')?.click();
    return { canStart: false, force: false };
  }
  if (preflight.warnings?.length) {
    showPreflightResult(preflight);
    const lines = preflight.warnings.map(item => `* ${item.message || item.code}`).join('\n');
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
export async function penConnect() {
  const r = await api('/pen/connect', 'POST');
  if (r?.ok) toast('Pen logger started - switch pen on');
  else toast('Warning: ' + (r?.error || 'Error'));
}

export async function penDisconnect() {
  await api('/pen/disconnect', 'POST');
  toast('Pen disconnected');
}

export async function watchCmd(cmd) {
  await api(`/watch/${cmd}`, 'POST');
  toast(`Watch command: ${cmd}`);
}

export async function airpodsCmd(cmd) {
  await api(`/airpods/${cmd}`, 'POST');
  toast(`AirPods command: ${cmd}`);
}

// ════════════════════════════════════════════════════════════
//  CARD DETAILS TOGGLE
// ════════════════════════════════════════════════════════════
export function toggleCardDetails(btn) {
  btn.closest('.card')?.classList.toggle('expanded');
}

// ════════════════════════════════════════════════════════════
//  WELCOME CARD
// ════════════════════════════════════════════════════════════
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
  const noWatch = !S.watchConnected;
  const airpodsUiOnline = !!(s?.airpods_connected || s?.airpods_paired || s?.airpods_streaming);
  const noAirpods = !airpodsUiOnline;
  const show = noSessions && noPen && noWatch && noAirpods && !_isWelcomeDismissed();
  card.style.display = show ? '' : 'none';
}


// ════════════════════════════════════════════════════════════
//  LOG RENDERING + SETTINGS
// ════════════════════════════════════════════════════════════
export function renderLogs() {
  const sampleRows = (S.sampleLog || []).slice(-S.logRows).reverse();
  const eventRows = (S.eventLog || []).slice(-S.logRows).reverse();

  const sampleEl = document.getElementById('sampleLog');
  const eventEl = document.getElementById('eventLog');

  if (sampleEl) {
    if (sampleRows.length === 0) {
      renderState(sampleEl, 'empty', {
        title: 'No samples yet',
        hint: 'Sample stream begins once a session is recording.',
      });
    } else {
      sampleEl.innerHTML = sampleRows.map(renderSampleRow).join('');
    }
  }

  if (eventEl) {
    if (eventRows.length === 0) {
      renderState(eventEl, 'empty', {
        title: 'No events yet',
        hint: 'Server and device events will appear here.',
      });
    } else {
      eventEl.innerHTML = eventRows.map(renderEventRow).join('');
    }
  }
}

function renderSampleRow(row) {
  const d = row.data || {};
  const msg = row.source === 'watch'
    ? `acc=(${fmtNum(d.ax)}, ${fmtNum(d.ay)}, ${fmtNum(d.az)}) gyro=(${fmtNum(d.rx)}, ${fmtNum(d.ry)}, ${fmtNum(d.rz)}) |a|=${fmtNum(d.acc_mag)} |r|=${fmtNum(d.gyro_mag)}`
    : `${d.dot_type || 'dot'} x=${fmtNum(d.x)} y=${fmtNum(d.y)} p=${d.pressure ?? '-'}`;
  return `<div class="log-row sample-row"><span class="log-time">${fmtClock(row.ts)}</span><span class="sample-pill">${esc(row.source || 'sample')}</span><span class="log-msg">${esc(msg)}</span></div>`;
}

function renderEventRow(row) {
  const cls = row.level === 'error' ? 'error' : (row.level === 'warn' ? 'warn' : '');
  const extra = row.data ? ` ${JSON.stringify(row.data)}` : '';
  return `<div class="log-row"><span class="log-time">${fmtClock(row.ts)}</span><span class="log-src">${esc(row.source || 'log')}</span><span class="log-msg ${cls}">${esc((row.message || '') + extra)}</span></div>`;
}

export function clearVisualLogs() {
  S.sampleLog = [];
  S.eventLog = [];
  renderLogs();
}

export function setLogRows(value) {
  S.logRows = Number(value) || 24;
  localStorage.setItem('logRows', String(S.logRows));
  const sel = document.getElementById('logRowsSelect');
  if (sel) sel.value = String(S.logRows);
  renderLogs();
}

// ════════════════════════════════════════════════════════════
//  PAGE LIFECYCLE
// ════════════════════════════════════════════════════════════
export function mount(container) {
  if (_mounted) return;
  _mounted = true;

  // Lazy-init canvas refs now that recording DOM is in the page.
  _penCanvas = document.getElementById('penCanvas');
  if (_penCanvas) _penCtx = _penCanvas.getContext('2d');

  // Chart.js chart constructed once DOM is ready.
  _initChart();

  // Resize redraws pen canvas; wired once after canvas is in DOM.
  window.addEventListener('resize', drawPenCanvas);

  // Initialise timer display and log rows now that DOM elements exist.
  const timerEl = document.getElementById('timer');
  if (timerEl) timerEl.textContent = '00:00:00';
  setLogRows(S.logRows);

  const dismissBtn = document.getElementById('welcomeDismiss');
  if (dismissBtn) {
    dismissBtn.addEventListener('click', () => {
      try { localStorage.setItem('welcomeDismissed', '1'); } catch {}
      const card = document.getElementById('welcomeCard');
      if (card) card.style.display = 'none';
    });
  }
}

export function onShow() {
  // Redraw pen canvas in case it was resized while hidden.
  drawPenCanvas();
}

export function onHide() {
  // No rAF loops to cancel - chart and pen canvas updates are synchronous.
  // Timer keeps running regardless of active tab (session continues in background).
}

export function onStatus(s) {
  // Session btn
  const btn = document.getElementById('sessionBtn');
  if (btn) {
    if (s.session_active) {
      btn.textContent = 'STOP'; btn.classList.add('stop');
    } else {
      btn.textContent = 'START'; btn.classList.remove('stop');
    }
  }

  // Input disabled state
  const personIdEl = document.getElementById('personId');
  const descEl = document.getElementById('sessionDescription');
  if (personIdEl) personIdEl.disabled = s.session_active;
  if (descEl) descEl.disabled = s.session_active;

  // Session counters
  setNumberSmooth('watchCount', s.watch_samples, { format: _smoothFmt.count });
  setNumberSmooth('penCount', s.pen_samples, { format: _smoothFmt.count });
  const sessionIdEl = document.getElementById('sessionIdDisp');
  if (sessionIdEl) sessionIdEl.textContent = s.session_id || '—';
  setNumberSmooth('watchRateMain', Number(s.watch_rate_hz || 0), { format: _smoothFmt.hz });

  // Hero live mode
  document.getElementById('liveRecordingHero')?.classList.toggle('live', !!s.session_active);

  // Timer label (idle state only - running timer updates its own label)
  if (!s.session_active && !S.timerInterval) {
    const labelEl = document.getElementById('timerLabel');
    if (labelEl) labelEl.textContent = 'Ready for a new recording';
  }

  // Timer start/stop
  if (s.session_active && !S.timerInterval && S.startTime) {
    startTimer();
  } else if (!s.session_active && S.timerInterval) {
    clearInterval(S.timerInterval); S.timerInterval = null;
    const labelEl = document.getElementById('timerLabel');
    if (labelEl) labelEl.textContent = 'Session ended';
  }

  // Welcome card
  _updateWelcomeCard(s);

  // Chart
  if (s.chart) updateChart(s.chart);
  const chartCanvasEmpty = document.querySelector('.chart-canvas-empty');
  if (S.chartBuffer.length > 0) {
    renderState(chartCanvasEmpty, 'clear');
  } else {
    renderState(chartCanvasEmpty, 'empty', {
      title: 'Waiting for IMU stream',
      hint: 'Start a session and accelerometer + gyroscope magnitudes will draw here in real time.',
    });
  }

  // Pen handwriting canvas
  if (s.pen_recent_dots) updatePenCanvas(s.pen_recent_dots);

  // Logs
  renderLogs();

  // Render study view (no-op when s.study is absent or inactive).
  renderStudyView(s.study);
  // Hide regular live-streams while a study runs to give the proband-facing
  // surface the full page.
  const streamsSec = document.getElementById('rec-sec-streams');
  if (streamsSec) streamsSec.style.display = s.study?.active ? 'none' : '';
}
