// status_cluster.js — topbar status cluster, chart, pen canvas, and live-status DOM
// handler.  updateChart / pen-canvas helpers technically belong to Recording (Task 13);
// they live here for now to avoid a flailing intermediate state.
//
// Back-imports from dashboard.js are marked "Temporary: moves to pages/<X>.js in
// Task N" and will disappear as those page modules are extracted.

import { S } from '/static/js/core/state.js';
import * as systemPage from '/static/js/pages/system.js';
import * as connectionsPage from '/static/js/pages/connections.js';
import * as sessionsPage from '/static/js/pages/sessions.js';
import {
  fmtHz, fmtNum, fmtAgo, fmtUptime, fmtCommand,
} from '/static/js/core/format.js';
import { setNumberSmooth } from '/static/js/core/anim.js';

// Temporary: renderLogs moves to pages/recording.js in Task 13
import { renderLogs } from '/static/dashboard.js';
// Temporary: startTimer moves to pages/recording.js in Task 13
import { startTimer } from '/static/dashboard.js';

// ════════════════════════════════════════════════════════════
//  FORMAT HELPERS  (module-private, mirrors _smoothFmt in dashboard.js)
// ════════════════════════════════════════════════════════════
const _smoothFmt = {
  hz: (v) => v > 0 ? `${v.toFixed(v >= 10 ? 1 : 2)} Hz` : '– Hz',
  count: (v) => Math.round(v).toLocaleString('de-DE'),
  decimal3: (v) => v.toFixed(3),
  pct: (v) => `${Math.round(v)}%`,
};

// ════════════════════════════════════════════════════════════
//  CHART (imu live chart on the Recording page)
// ════════════════════════════════════════════════════════════
const chartCtx = document.getElementById('imuChart').getContext('2d');
export const imuChart = new Chart(chartCtx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [{
      label: '|a|',
      data: [],
      borderColor: 'oklch(0.595 0.165 43)',
      backgroundColor: (ctx) => {
        const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, 200);
        gradient.addColorStop(0, 'oklch(0.595 0.165 43 / 0.25)');
        gradient.addColorStop(1, 'oklch(0.595 0.165 43 / 0.02)');
        return gradient;
      },
      borderWidth: 1.8,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.35,
      fill: true,
    }, {
      label: '|r|',
      data: [],
      borderColor: 'oklch(0.720 0.135 88)',
      backgroundColor: 'oklch(0.720 0.135 88 / 0.06)',
      borderWidth: 1.5,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.35,
      fill: false,
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: true,
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

export function updateChart(chartPts) {
  if (!chartPts || !chartPts.length) return;
  // Merge new points into buffer (avoid duplicates by timestamp)
  chartPts.forEach(pt => {
    if (!S.chartBuffer.find(b => b.t === pt.t)) {
      S.chartBuffer.push(pt);
    }
  });
  // Keep last 60
  if (S.chartBuffer.length > 60) S.chartBuffer = S.chartBuffer.slice(-60);

  const accVals = S.chartBuffer.map(b => Number(b.acc_mag ?? b.mag ?? 0));
  const gyroVals = S.chartBuffer.map(b => Number(b.gyro_mag ?? 0));
  imuChart.data.labels = S.chartBuffer.map((_, i) => i);
  imuChart.data.datasets[0].data = accVals;
  imuChart.data.datasets[1].data = gyroVals;
  imuChart.update('none');

  // Stats
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
const _penCanvas = document.getElementById('penCanvas');
const _penCtx = _penCanvas.getContext('2d');
let _penSeenTs = new Set();   // deduplicate dots by timestamp

export function updatePenCanvas(newDots) {
  if (!newDots || !newDots.length) return;

  // Clear buffer on session change (session_id switches → fresh canvas)
  // Handled by clearPenPreview() call in handleStatus before this.

  // Composite key — local_ts_ms collisions happen at ~80 Hz when two dots
  // share the same millisecond, so include dot_type and coords as tiebreakers.
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

  // Update auto-scale bounds
  for (const d of S.penDotBuffer) {
    if (!S.penBounds) {
      S.penBounds = { minX: d.x, maxX: d.x, minY: d.y, maxY: d.y };
    } else {
      if (d.x < S.penBounds.minX) S.penBounds.minX = d.x;
      if (d.x > S.penBounds.maxX) S.penBounds.maxX = d.x;
      if (d.y < S.penBounds.minY) S.penBounds.minY = d.y;
      if (d.y > S.penBounds.maxY) S.penBounds.maxY = d.y;
    }
  }

  drawPenCanvas();
}

export function clearPenPreview() {
  S.penDotBuffer = [];
  S.penBounds = null;
  _penSeenTs = new Set();
  drawPenCanvas();
  document.getElementById('penCanvasInfo').textContent = 'Cleared · waiting for new pen data';
}

export function drawPenCanvas() {
  const canvas = _penCanvas;
  const ctx = _penCtx;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.offsetWidth || 600;
  const cssH = 200;
  // Empty-State Overlay aus-/einblenden je nach Daten-Lage
  document.getElementById('penCanvasWrap')?.classList.toggle('has-data', S.penDotBuffer.length > 0);

  if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    canvas.style.height = cssH + 'px';
  }

  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  if (!S.penDotBuffer.length || !S.penBounds) {
    ctx.restore();
    return;
  }

  const { minX, maxX, minY, maxY } = S.penBounds;
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const pad = 20;
  const scaleX = (cssW - pad * 2) / rangeX;
  const scaleY = (cssH - pad * 2) / rangeY;
  const scale = Math.min(scaleX, scaleY);
  // Centre the drawing in the available space
  const drawW = rangeX * scale;
  const drawH = rangeY * scale;
  const ox = pad + (cssW - pad * 2 - drawW) / 2;
  const oy = pad + (cssH - pad * 2 - drawH) / 2;

  const toX = (x) => ox + (x - minX) * scale;
  const toY = (y) => oy + (y - minY) * scale;

  const inkColor = S.theme === 'dark' ? 'oklch(0.87 0.010 80)' : 'oklch(0.22 0.025 55)';
  ctx.strokeStyle = inkColor;
  ctx.fillStyle = inkColor;
  ctx.lineWidth = 1.6;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // 1. Linien zwischen aufeinanderfolgenden Move-Dots (Strokes).
  //    Wenn der ursprüngliche PEN_DOWN aus dem Rolling-Window rausgefallen
  //    ist, starten wir den Stroke beim ersten gesehenen PEN_MOVE.
  let inStroke = false;
  for (const dot of S.penDotBuffer) {
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

  // 2. Sicherheitsnetz: kleine Punkte an *jedem* Dot. Selbst wenn die
  //    Stroke-Logik aus irgendeinem Grund versagt, sieht man dass Daten
  //    ankommen — dann wissen wir wo wir suchen müssen.
  for (const dot of S.penDotBuffer) {
    ctx.beginPath();
    ctx.arc(toX(dot.x), toY(dot.y), 1.0, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();

  const moveDots = S.penDotBuffer.filter(d => d.t !== 'PEN_UP').length;
  document.getElementById('penCanvasInfo').textContent =
    `${moveDots} ink dots · x ${minX.toFixed(1)}–${maxX.toFixed(1)} · y ${minY.toFixed(1)}–${maxY.toFixed(1)}`;
}

window.addEventListener('resize', drawPenCanvas);

// ════════════════════════════════════════════════════════════
//  STATUS CLUSTER (topbar)
// ════════════════════════════════════════════════════════════
export function setStatusCluster(s) {
  const setDot = (id, state) => {
    const el = document.getElementById(id);
    if (el) el.className = 'status-dot ' + (state || '');
  };
  setDot('clusterDotPen', s.pen);
  setDot('clusterDotWatch', s.watch);
  setDot('clusterDotServer', s.server);

  // Primär-Label: Worst-Case zuerst kommunizieren, dann positiv-Bestätigung.
  let label, meta = '';
  const issues = [];
  if (s.pen === 'err')   issues.push('Pen offline');
  if (s.watch === 'err') issues.push('Watch offline');
  if (s.server === 'err') issues.push('Server offline');
  if (s.pen === 'warn')   issues.push('Pen reconnecting');
  if (s.watch === 'warn') issues.push('Watch reconnecting');

  if (issues.length) {
    label = issues[0];
  } else {
    label = s.sessionActive ? 'Recording live' : 'All systems';
  }
  if (s.sessionActive && s.watchRate > 0) {
    meta = `${s.watchRate.toFixed(s.watchRate >= 10 ? 1 : 2)} Hz`;
  } else if (!s.sessionActive) {
    meta = `up ${fmtUptime(s.uptime || 0)}`;
  }

  const labelEl = document.getElementById('statusClusterLabel');
  const metaEl = document.getElementById('statusClusterMeta');
  if (labelEl) labelEl.textContent = label;
  if (metaEl) metaEl.textContent = meta;

  // Detaillierter Hover-Tooltip für Diagnose
  const tip = [
    `Pen: ${s.pen === 'ok' ? 'connected' : 'disconnected'}` +
      (s.penDots ? ` · ${s.penDots} dots` : ''),
    `Watch: ${s.watchStatusText || (s.watch === 'ok' ? 'online' : 'offline')}` +
      (s.watchRate > 0 ? ` · ${s.watchRate.toFixed(1)} Hz` : '') +
      (s.watchSamples ? ` · ${s.watchSamples} samples` : ''),
    `Server: ok · uptime ${fmtUptime(s.uptime || 0)}`,
  ].join('\n');
  const cluster = document.getElementById('statusCluster');
  if (cluster) cluster.title = tip;
}

export function setPill(id, ok, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'pill ' + (cls || '');
  document.getElementById(id + 'Txt').textContent = text;
}

export function setBadge(id, ok, text, cls = null) {
  const el = document.getElementById(id);
  el.className = 'status-badge ' + (cls || (ok ? 'badge-ok' : 'badge-err'));
  el.textContent = text;
}

export function setHealth(id, text, cls) {
  const el = document.getElementById(id);
  el.className = 'v ' + (cls || '');
  el.textContent = text;
}

// ════════════════════════════════════════════════════════════
//  STATUS HANDLER
// ════════════════════════════════════════════════════════════
export function handleStatus(s, prevSessionId) {
  // S.xxx state mutations have already been applied by updateFromStatus(s)
  // in the WS onmessage handler before this function is called.
  // prevSessionId is captured by the caller BEFORE updateFromStatus runs,
  // so the session-change detection sees the correct old value.
  if (s.session_id !== prevSessionId) clearPenPreview();

  const watchRate = Number(s.watch_rate_hz || 0);
  const penRate = Number(s.pen_rate_hz || 0);
  const lastWatch = s.watch_last_sample || {};
  const lastPen = s.pen_last_dot || {};
  const validation = s.validation || {};
  const clients = s.connected_clients || {};
  const gyroOk = validation.watch_has_gyroscope === true;
  const penClockOk = validation.pen_has_server_time === true;
  const watchStreamActive = s.watch_stream_active ?? s.watch_connected;
  const watchDirectConnected = s.watch_direct_connected === true;
  const watchBridgeConnected = s.watch_bridge_connected || Boolean(clients.iphone || clients.watch_bridge);
  const watchReachable = s.watch_reachable === true;
  const watchPolling = s.watch_polling === true;
  const watchUiOnline = watchStreamActive || watchDirectConnected || watchReachable || watchPolling || watchBridgeConnected;
  const watchStatusText = watchStreamActive
    ? 'Streaming'
    : (watchDirectConnected ? 'Direct · Connected'
    : (watchPolling ? 'Polling via iPhone'
    : (watchReachable ? 'Reachable' : (watchBridgeConnected ? 'Bridge ready' : 'Offline'))));
  const watchBadgeClass = watchStreamActive || watchDirectConnected || watchReachable || watchPolling ? 'badge-ok' : (watchBridgeConnected ? 'badge-warn' : 'badge-err');
  S.watchConnected = watchUiOnline;
  S.watchStatusText = watchStatusText;
  S.watchBadgeClass = watchBadgeClass;

  // Hero-Card "live"-Modus: aktiviert die Akzent-Stripe + LIVE-Indicator
  document.getElementById('liveRecordingHero')?.classList.toggle('live', !!s.session_active);

  // Konsolidierter Status-Cluster im Topbar — drei Dots + ein Plaintext-Label
  const penDotState = s.pen_connected ? 'ok' : 'err';
  const watchDotState = (watchStreamActive || watchReachable || watchPolling)
    ? 'ok' : (watchBridgeConnected ? 'warn' : 'err');
  const serverDotState = 'ok';
  setStatusCluster({
    pen: penDotState, watch: watchDotState, server: serverDotState,
    sessionActive: s.session_active,
    watchRate, watchStatusText,
    penDots: s.pen_samples, watchSamples: s.watch_samples,
    uptime: s.uptime_seconds,
  });

  // Counts
  setNumberSmooth('watchCount', s.watch_samples, { format: _smoothFmt.count });
  setNumberSmooth('penCount', s.pen_samples, { format: _smoothFmt.count });
  document.getElementById('sessionIdDisp').textContent = s.session_id || '—';
  setNumberSmooth('watchRateMain', watchRate, { format: _smoothFmt.hz });
  document.getElementById('personId').disabled = s.session_active;
  document.getElementById('sessionDescription').disabled = s.session_active;

  // Session btn
  const btn = document.getElementById('sessionBtn');
  if (s.session_active) {
    btn.textContent = '■  STOP'; btn.classList.add('stop');
  } else {
    btn.textContent = 'START'; btn.classList.remove('stop');
  }

  // Timer label
  if (!s.session_active && !S.timerInterval) {
    document.getElementById('timerLabel').textContent = 'Ready for a new recording';
  }

  // Pen badge
  setBadge('penBadge', s.pen_connected, s.pen_connected ? 'Connected' : 'Disconnected');
  setBadge('watchBadge', watchUiOnline, watchStatusText, watchBadgeClass);
  document.getElementById('penBleStatus').textContent = s.pen_connected ? 'Connected' : 'Idle';
  document.getElementById('dotType').textContent = lastPen.dot_type || '–';
  document.getElementById('penLastXY').textContent = lastPen.x != null ? `${fmtNum(lastPen.x)}, ${fmtNum(lastPen.y)}` : '–';
  setNumberSmooth('penRateSide', penRate, { format: _smoothFmt.hz });
  setNumberSmooth('watchRateSide', watchRate, { format: _smoothFmt.hz });
  setNumberSmooth('watchGyroSide', lastWatch.gyro_mag, { format: _smoothFmt.decimal3 });
  document.getElementById('watchLastTs').textContent = s.watch_last_seen_ms_ago != null ? fmtAgo(s.watch_last_seen_ms_ago) : '–';

  // AirPods (head motion) — tri-state: Streaming > Paired > Offline.
  // "paired" comes from the iPhone bridge (CMHeadphoneMotionManagerDelegate),
  // so the dashboard can show "AirPods on, idle" before any sample arrives.
  const airpodsRate = Number(s.airpods_rate_hz || 0);
  const lastAirpods = s.airpods_last_sample || {};
  const airpodsStreaming = !!s.airpods_connected;
  const airpodsPaired = s.airpods_paired === true;
  const airpodsListening = s.airpods_streaming === true;
  let airpodsBadgeText, airpodsBadgeClass, airpodsUiOnline;
  if (airpodsStreaming) {
    airpodsBadgeText = 'Streaming'; airpodsBadgeClass = 'badge-ok'; airpodsUiOnline = true;
  } else if (airpodsPaired) {
    airpodsBadgeText = airpodsListening ? 'Paired · listening' : 'Paired · idle';
    airpodsBadgeClass = 'badge-warn'; airpodsUiOnline = true;
  } else if (airpodsListening) {
    airpodsBadgeText = 'Waiting for AirPods'; airpodsBadgeClass = 'badge-warn'; airpodsUiOnline = false;
  } else {
    airpodsBadgeText = 'Offline'; airpodsBadgeClass = 'badge-err'; airpodsUiOnline = false;
  }
  setBadge('airpodsBadge', airpodsUiOnline, airpodsBadgeText, airpodsBadgeClass);
  setNumberSmooth('airpodsRateSide', airpodsRate, { format: _smoothFmt.hz });
  setNumberSmooth('airpodsAccSide', lastAirpods.acc_mag, { format: _smoothFmt.decimal3 });
  document.getElementById('airpodsLastTs').textContent =
    s.airpods_last_seen_ms_ago != null ? fmtAgo(s.airpods_last_seen_ms_ago) : '–';

  // Health metrics
  setHealth('watchHz', fmtHz(watchRate), watchRate > 80 ? 'ok' : (watchRate > 0 ? 'warn' : 'err'));
  setHealth('penHz', fmtHz(penRate), penRate > 0 ? 'ok' : (s.pen_connected ? 'warn' : 'err'));
  setHealth('gyroHealth', gyroOk ? 'present' : 'missing', gyroOk ? 'ok' : 'err');
  setHealth('clockHealth', penClockOk ? 'server time' : 'legacy pen time', penClockOk ? 'ok' : 'warn');

  connectionsPage.onStatus(s);
  sessionsPage.onStatus(s);

  // System checks
  document.getElementById('checkAccel').textContent = validation.watch_has_accelerometer ? 'ok' : 'missing';
  document.getElementById('checkGyro').textContent = gyroOk ? 'ok' : 'missing';
  document.getElementById('checkPenTime').textContent = penClockOk ? 'ok' : 'new recordings only';
  document.getElementById('checkRate').textContent = `${fmtHz(watchRate)} watch · ${fmtHz(penRate)} pen`;

  renderLogs();

  // Chart
  if (s.chart) updateChart(s.chart);
  // Empty-State Overlay aus-/einblenden je nach ob Chart-Daten existieren
  document.getElementById('chartCanvasWrap')?.classList.toggle('has-data', S.chartBuffer.length > 0);

  // Pen handwriting canvas
  if (s.pen_recent_dots) updatePenCanvas(s.pen_recent_dots);

  // Start timer if session active and not already running
  if (s.session_active && !S.timerInterval && S.startTime) {
    startTimer();
  } else if (!s.session_active && S.timerInterval) {
    clearInterval(S.timerInterval); S.timerInterval = null;
    document.getElementById('timerLabel').textContent = 'Session ended';
  }

  systemPage.onStatus(s);
}
