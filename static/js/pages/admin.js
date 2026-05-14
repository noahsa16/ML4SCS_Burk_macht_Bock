// static/js/pages/admin.js — Admin / VL monitor page
//
// A second-screen view for the experimenter (e.g. on an iPad) to watch
// a running study session: current task, live IMU chart, live pen canvas,
// sample counters and big touch-friendly VL control buttons.
//
// Key invariants:
//   - This page is INDEPENDENT of recording.js — it owns its own Chart.js
//     instance and pen canvas, with their own local buffers. The recording
//     module's module-level singletons target hardcoded IDs we do not share.
//   - This page MUST NOT trigger the study-active fullscreen takeover.
//     onShow() defensively clears `body.study-active` so navigating here
//     from a study-active recording page does not bleed the overlay in.

import { S } from '/static/js/core/state.js';

let _mounted = false;

// ════════════════════════════════════════════════════════════
//  CHART — local copy, bound to #admImuChart, with its own buffer
// ════════════════════════════════════════════════════════════
let _chart = null;
let _chartBuf = [];   // {t, acc_mag, gyro_mag, pen_writing}

function _initChart() {
  const canvas = document.getElementById('admImuChart');
  if (!canvas || typeof Chart === 'undefined') return;
  const ctx = canvas.getContext('2d');
  _chart = new Chart(ctx, {
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
        tension: 0.3,
        fill: 'origin',
      }, {
        label: '|r|',
        data: [],
        borderColor: 'oklch(0.720 0.135 88)',
        backgroundColor: 'rgba(196, 156, 30, 0.12)',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.3,
        fill: 'origin',
      }],
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
            },
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
        },
      },
      plugins: {
        legend: { display: false },
      },
    },
    plugins: [{
      id: 'admWritingBands',
      beforeDatasetsDraw(chart) {
        const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
        if (!x || !_chartBuf.length) return;
        ctx.save();
        _chartBuf.forEach((pt, i) => {
          if (!pt.pen_writing) return;
          const xPos = x.getPixelForValue(i);
          const nextX = x.getPixelForValue(i + 1);
          ctx.fillStyle = 'oklch(0.580 0.130 148 / 0.18)';
          ctx.fillRect(xPos, top, (nextX || xPos + 8) - xPos, bottom - top);
        });
        ctx.restore();
      },
    }],
  });
}

function _updateChart(chartPts) {
  if (!chartPts || !chartPts.length || !_chart) return;
  for (const pt of chartPts) {
    if (!_chartBuf.find(b => b.t === pt.t)) _chartBuf.push(pt);
  }
  if (_chartBuf.length > 60) _chartBuf = _chartBuf.slice(-60);

  const accVals = _chartBuf.map(b => Number(b.acc_mag ?? b.mag ?? 0));
  const gyroVals = _chartBuf.map(b => Number(b.gyro_mag ?? 0));
  _chart.data.labels = _chartBuf.map((_, i) => i);
  _chart.data.datasets[0].data = accVals;
  _chart.data.datasets[1].data = gyroVals;
  _chart.update('none');
}

// ════════════════════════════════════════════════════════════
//  PEN CANVAS — local copy, bound to #admPenCanvas
// ════════════════════════════════════════════════════════════
let _penCanvas = null;
let _penCtx = null;
let _penBuf = [];
let _penSeen = new Set();

const PEN_VIEW_WINDOW = 600;

function _dotKey(d) { return `${d.ts ?? ''}_${d.t ?? ''}_${d.x}_${d.y}`; }

function _updatePen(newDots) {
  if (!newDots || !newDots.length || !_penCanvas) return;
  let added = 0;
  for (const d of newDots) {
    const k = _dotKey(d);
    if (_penSeen.has(k)) continue;
    _penSeen.add(k);
    _penBuf.push(d);
    added++;
  }
  if (!added) return;

  const MAX = 2500;
  if (_penBuf.length > MAX) {
    const dropped = _penBuf.splice(0, _penBuf.length - MAX);
    dropped.forEach(d => _penSeen.delete(_dotKey(d)));
  }
  _drawPen();
}

function _drawPen() {
  if (!_penCanvas || !_penCtx) return;
  const canvas = _penCanvas;
  const ctx = _penCtx;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || canvas.offsetWidth || 600;
  const cssH = canvas.clientHeight || canvas.offsetHeight || 360;

  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }

  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  if (!_penBuf.length) { ctx.restore(); return; }

  const viewDots = _penBuf.length > PEN_VIEW_WINDOW
    ? _penBuf.slice(-PEN_VIEW_WINDOW)
    : _penBuf;
  let minX = viewDots[0].x, maxX = viewDots[0].x;
  let minY = viewDots[0].y, maxY = viewDots[0].y;
  for (let i = 1; i < viewDots.length; i++) {
    const d = viewDots[i];
    if (d.x < minX) minX = d.x;
    if (d.x > maxX) maxX = d.x;
    if (d.y < minY) minY = d.y;
    if (d.y > maxY) maxY = d.y;
  }
  const rangeX = (maxX - minX) || 1;
  const rangeY = (maxY - minY) || 1;
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

  const ink = S.theme === 'dark' ? 'oklch(0.87 0.010 80)' : 'oklch(0.22 0.025 55)';
  ctx.strokeStyle = ink;
  ctx.fillStyle = ink;
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
      if (!inStroke) { ctx.beginPath(); ctx.moveTo(cx, cy); inStroke = true; }
      else { ctx.lineTo(cx, cy); }
    } else if (dot.t === 'PEN_UP') {
      if (inStroke) { ctx.lineTo(cx, cy); ctx.stroke(); }
      inStroke = false;
    }
  }
  if (inStroke) ctx.stroke();

  for (const dot of viewDots) {
    ctx.beginPath();
    ctx.arc(toX(dot.x), toY(dot.y), 1.0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

// ════════════════════════════════════════════════════════════
//  HELPERS
// ════════════════════════════════════════════════════════════
function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(val);
}

function _fmtClock(ms) {
  if (ms == null || !Number.isFinite(ms)) return '--:--';
  const s = Math.max(0, Math.round(ms / 1000));
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function _fmtCount(n) {
  if (n == null) return '0';
  return Math.round(n).toLocaleString('de-DE');
}

function _fmtHz(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return '– Hz';
  return `${n.toFixed(n >= 10 ? 1 : 2)} Hz`;
}

// ════════════════════════════════════════════════════════════
//  LIFECYCLE
// ════════════════════════════════════════════════════════════
export function mount(container) {
  if (_mounted) return;
  _mounted = true;
  _penCanvas = document.getElementById('admPenCanvas');
  if (_penCanvas) _penCtx = _penCanvas.getContext('2d');
  _initChart();
  window.addEventListener('resize', _drawPen);
}

export function onShow() {
  // Why: navigating here from a study-active recording page would otherwise
  // leave body.study-active set, which makes study-mode.css cover this page
  // with the proband-facing overlay. The admin page is explicitly NOT a
  // proband surface.
  document.body.classList.remove('study-active');
  _drawPen();
}

export function onHide() {
  // No timers / rAF loops to cancel — chart and pen updates are synchronous.
}

export function onStatus(s) {
  if (!s) return;

  // Session id + counters
  _setText('admSessionId', s.session_id || '—');
  _setText('admWatchCount', _fmtCount(s.watch_samples));
  _setText('admPenCount', _fmtCount(s.pen_samples));
  _setText('admWatchRate', _fmtHz(s.watch_rate_hz));
  _setText('admPenRate', _fmtHz(s.pen_rate_hz));

  // Study task block vs empty state
  const active = document.getElementById('admTaskActive');
  const empty = document.getElementById('admTaskEmpty');
  const pauseBtn = document.getElementById('admBtnPause');
  const nextBtn = document.getElementById('admBtnNext');
  const abortBtn = document.getElementById('admBtnAbort');
  const studyOn = !!(s.study && s.study.active);

  if (active) active.style.display = studyOn ? '' : 'none';
  if (empty) empty.style.display = studyOn ? 'none' : '';
  // Disable VL buttons when no study is running.
  [pauseBtn, nextBtn, abortBtn].forEach(b => { if (b) b.disabled = !studyOn; });

  if (studyOn) {
    const st = s.study;
    _setText('admTaskLabel', st.task?.label ?? '—');
    _setText('admTaskRemaining', _fmtClock(st.task_remaining_ms));
    const idx = st.task_index ?? '?';
    const tot = st.task_total ?? '?';
    _setText('admTaskIndex', `${idx} / ${tot}`);
    const fill = document.getElementById('admTaskProgressFill');
    if (fill) {
      const dur = Math.max(1, Number(st.task_duration_ms) || 1);
      const pct = Math.max(0, Math.min(100,
        (1 - (Number(st.task_remaining_ms) || 0) / dur) * 100));
      fill.style.width = `${pct.toFixed(1)}%`;
    }
    // Reflect paused state in the Pause button label
    if (pauseBtn) {
      const lbl = pauseBtn.querySelector('span:last-child');
      if (lbl) lbl.textContent = (st.state === 'paused') ? 'Resume' : 'Pause';
    }
  }

  // Live streams
  if (s.chart) _updateChart(s.chart);
  if (s.pen_recent_dots) _updatePen(s.pen_recent_dots);
}
