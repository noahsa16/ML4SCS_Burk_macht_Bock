// ════════════════════════════════════════════════════════════
//  STATE
// ════════════════════════════════════════════════════════════
const S = {
  sessionActive: false,
  sessionId: null,
  personId: null,
  startTime: null,
  watchSamples: 0,
  penSamples: 0,
  penConnected: false,
  watchConnected: false,
  uptime: 0,
  timerInterval: null,
  allSessions: [],
  chartBuffer: [],   // {t, mag, pen_writing}
  chartMax: 0,
  eventLog: [],
  sampleLog: [],
  logRows: Number(localStorage.getItem('logRows') || 24),
  theme: localStorage.getItem('theme') || 'light',
  qualityBySession: {},
  qualitySummary: null,
  validationBySession: {},
  alignmentBySession: {},
  alignmentCharts: { variance: null, timeline: null },
  selectedSessionId: null,
  penDotBuffer: [],   // {x, y, t, ts} — last ~500 pen dots for canvas
  penBounds: null,    // {minX, maxX, minY, maxY} — auto-scale bounds
  watchStatusText: 'Offline',
  watchBadgeClass: 'badge-err',
  lastStatus: null,
};

// ════════════════════════════════════════════════════════════
//  NAVIGATION
// ════════════════════════════════════════════════════════════
const pageMeta = {
  recording:   { title: 'Live Recording',   sub: 'Pen + Watch data capture' },
  sessions:    { title: 'Session History',  sub: 'All recorded sessions' },
  connections: { title: 'Connections',      sub: 'Device & server management' },
  system:      { title: 'System & Schema',  sub: 'Data structure · API reference · Project info' },
};

document.querySelectorAll('.tab').forEach(el => {
  el.addEventListener('click', () => {
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
    if (p === 'sessions') loadSessions();
    if (p === 'connections') updateConnectionsPage();
    updateTabIndicator();
  });
});

// Slidender Tab-Underline: misst Position+Breite des aktiven Tabs und
// translatet ein einzelnes Indicator-Element dahin. CSS macht den Slide.
function updateTabIndicator() {
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

// Initial nach Font-Load (sonst stimmt die Breite nicht), und bei Resize
window.addEventListener('load', () => requestAnimationFrame(updateTabIndicator));
if (document.fonts?.ready) {
  document.fonts.ready.then(updateTabIndicator);
}
window.addEventListener('resize', updateTabIndicator);

// Status-Cluster im Topbar → springt direkt zur Connections-Page für Detail-Diagnose
document.getElementById('statusCluster')?.addEventListener('click', () => {
  document.querySelector('.tab[data-page="connections"]')?.click();
});

// ════════════════════════════════════════════════════════════
//  SMOOTH NUMBER UPDATES (Low-Pass / Exponential Smoothing)
//  Anzeige strebt kontinuierlich in Richtung Zielwert. Bei jedem
//  Frame: displayed += (target - displayed) * α(dt). Kein diskreter
//  Tween, kein Plateau am Ende, kein Restart-Artefakt bei jitterigen
//  Broadcasts — das ist mathematisch genau das, was du als smooth
//  empfindest. timeConstant steuert die "Trägheit" (kleiner = schneller).
// ════════════════════════════════════════════════════════════
const _numAnim = new Map();
let _animLoopRunning = false;
let _animLastFrame = 0;
// Skeleton: Mindest-Anzeigedauer ab Page-Load, damit der Loader nicht
// nur für 50 ms aufblitzt bevor die ersten WS-Daten ankommen.
const _PAGE_LOAD_T0 = performance.now();
const SKEL_MIN_MS = 600;

function setNumberSmooth(elementId, value, opts = {}) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const fmt = opts.format || ((v) => Math.round(v).toString());
  const target = Number(value);
  const timeConstant = opts.timeConstant ?? 350;
  const wantsSkel = el.dataset.skel !== undefined;

  if (!Number.isFinite(target)) {
    _numAnim.delete(elementId);
    // Skeleton nur solange wir noch nie einen echten Wert hatten — vermeidet
    // dass Werte zwischen Sessions in Loading-State zurückspringen.
    if (wantsSkel && el.dataset.skelDone === undefined) {
      el.classList.add('skel-loading');
    }
    el.textContent = opts.fallback ?? '–';
    return;
  }

  // Wenn Skeleton noch aktiv: Mindestanzeigedauer einhalten, sonst defer
  if (wantsSkel && el.classList.contains('skel-loading')) {
    const elapsed = performance.now() - _PAGE_LOAD_T0;
    if (elapsed < SKEL_MIN_MS) {
      setTimeout(() => setNumberSmooth(elementId, value, opts), SKEL_MIN_MS - elapsed);
      return;
    }
    el.classList.remove('skel-loading');
    el.dataset.skelDone = '1';
  } else if (wantsSkel) {
    el.dataset.skelDone = '1';
  }

  let st = _numAnim.get(elementId);
  if (!st) {
    // Erste Anzeige: direkt setzen, ohne 0 → real Animation
    st = { el, fmt, timeConstant, displayed: target, target, lastShownText: '' };
    _numAnim.set(elementId, st);
    const txt = fmt(target);
    el.textContent = txt;
    el.dataset.numValue = String(target);
    st.lastShownText = txt;
    return;
  }

  st.fmt = fmt;
  st.timeConstant = timeConstant;
  st.target = target;

  if (!_animLoopRunning) _startAnimLoop();
}

function _startAnimLoop() {
  _animLoopRunning = true;
  _animLastFrame = performance.now();
  function tick(now) {
    const dt = Math.min(100, now - _animLastFrame); // cap to avoid big jumps after tab inactive
    _animLastFrame = now;
    let active = false;
    for (const [, st] of _numAnim) {
      const diff = st.target - st.displayed;
      if (Math.abs(diff) < 1e-4) {
        if (st.displayed !== st.target) {
          st.displayed = st.target;
          const txt = st.fmt(st.displayed);
          if (txt !== st.lastShownText) {
            st.el.textContent = txt;
            st.el.dataset.numValue = String(st.displayed);
            st.lastShownText = txt;
          }
        }
        continue;
      }
      active = true;
      const alpha = 1 - Math.exp(-dt / st.timeConstant);
      st.displayed += diff * alpha;
      const txt = st.fmt(st.displayed);
      if (txt !== st.lastShownText) {
        st.el.textContent = txt;
        st.el.dataset.numValue = String(st.displayed);
        st.lastShownText = txt;
      }
    }
    if (active) requestAnimationFrame(tick);
    else _animLoopRunning = false;
  }
  requestAnimationFrame(tick);
}

// Format-Helper für die Smooth-Updates
const _smoothFmt = {
  hz: (v) => v > 0 ? `${v.toFixed(v >= 10 ? 1 : 2)} Hz` : '– Hz',
  count: (v) => Math.round(v).toLocaleString('de-DE'),
  decimal3: (v) => v.toFixed(3),
  pct: (v) => `${Math.round(v)}%`,
};

// ════════════════════════════════════════════════════════════
//  CHART
// ════════════════════════════════════════════════════════════
const chartCtx = document.getElementById('imuChart').getContext('2d');
const imuChart = new Chart(chartCtx, {
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

function updateChart(chartPts) {
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

function updatePenCanvas(newDots) {
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

function clearPenPreview() {
  S.penDotBuffer = [];
  S.penBounds = null;
  _penSeenTs = new Set();
  drawPenCanvas();
  document.getElementById('penCanvasInfo').textContent = 'Cleared · waiting for new pen data';
}

function drawPenCanvas() {
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
//  WEBSOCKET
// ════════════════════════════════════════════════════════════
let ws, wsReconnectTimer;

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setWsStatus('ok');
    ws.send(JSON.stringify({ type: 'hello', client: 'dashboard' }));
  };

  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.type === 'status') handleStatus(msg);
    else if (msg.type === 'start') toast(`▶ Session ${msg.session_id} started`);
    else if (msg.type === 'stop') { toast(`■ Session ${msg.session_id} stopped`); if (document.querySelector('.tab.active')?.dataset.page === 'sessions') loadSessions(); }
  };

  ws.onclose = () => {
    setWsStatus('err');
    wsReconnectTimer = setTimeout(connectWs, 3000);
  };

  ws.onerror = () => { ws.close(); };
}

function setWsStatus(st) {
  // wsDot / wsLabel waren in der alten Sidebar — im neuen Topbar zeigt der
  // Server-Dot im Status-Cluster die WS-Verbindung. Defensives null-checking,
  // damit ältere uptime-Anzeigen weiter laufen.
  const dot = document.getElementById('wsDot');
  if (dot) {
    dot.className = 'ws-dot' + (st === 'ok' ? ' ok' : '');
  }
  const lbl = document.getElementById('wsLabel');
  if (lbl) lbl.textContent = st === 'ok' ? 'WS connected' : 'WS reconnecting…';
  const uptimeWs = document.getElementById('uptimeWs');
  if (uptimeWs) uptimeWs.textContent = st === 'ok' ? 'Connected' : 'Reconnecting';
}

// Brand-Klick → zurück zur Recording-Page (Home-Behavior)
function goHome() {
  document.querySelector('.tab[data-page="recording"]')?.click();
}

// Details-Toggle: Sekundär-Metriken auf einer Card ein-/ausklappen
function toggleCardDetails(btn) {
  btn.closest('.card')?.classList.toggle('expanded');
}

function setNetworkNode(id, state, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('ok', 'warn', 'err');
  el.classList.add(state);
  const status = document.getElementById(`${id}Status`);
  if (status) status.textContent = text;
}

function setNetworkLine(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('ok', 'warn', 'err');
  if (state) el.classList.add(state);
}

// ════════════════════════════════════════════════════════════
//  STATUS HANDLER
// ════════════════════════════════════════════════════════════
function handleStatus(s) {
  S.lastStatus = s;
  // Clear canvas when session changes so strokes from different sessions don't mix
  if (s.session_id !== S.sessionId) clearPenPreview();
  S.sessionActive = s.session_active;
  S.sessionId = s.session_id;
  S.personId = s.person_id;
  S.startTime = s.start_time ? new Date(s.start_time) : null;
  S.watchSamples = s.watch_samples;
  S.penSamples = s.pen_samples;
  S.penConnected = s.pen_connected;
  S.uptime = s.uptime_seconds;
  S.eventLog = s.event_log || S.eventLog;
  S.sampleLog = s.sample_log || S.sampleLog;

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

  // Connections page
  setBadge('connPenBadge', s.pen_connected, s.pen_connected ? 'Connected' : 'Disconnected');
  setBadge('connWatchBadge', watchUiOnline, watchStatusText, watchBadgeClass);
  document.getElementById('connWatchLast').textContent = s.watch_last_packet
    ? `${fmtAgo(Date.now() - s.watch_last_packet.server_received_ms)} · seq ${s.watch_last_packet.sequence ?? '–'}`
    : '–';
  document.getElementById('uptimeVal').textContent = fmtUptime(s.uptime_seconds);
  document.getElementById('uptimeSession').textContent = s.session_id || 'None';
  document.getElementById('uptimeBridge').textContent = watchBridgeConnected ? 'Connected' : '–';
  document.getElementById('penPid').textContent = s.pen_pid || '–';
  setNumberSmooth('connPenHz', penRate, { format: _smoothFmt.hz });
  document.getElementById('connPenLast').textContent = lastPen.dot_type ? `${lastPen.dot_type} · ${fmtNum(lastPen.x)}, ${fmtNum(lastPen.y)}` : '–';
  document.getElementById('connPenClock').textContent = penClockOk ? 'ok' : 'legacy/missing';
  document.getElementById('connWatchBridge').textContent = watchBridgeConnected ? 'connected' : 'not connected';
  document.getElementById('connWatchReachable').textContent = watchPolling
    ? `polling${s.watch_poll_age_ms != null ? ` · ${fmtAgo(s.watch_poll_age_ms)}` : ''}`
    : (s.watch_reachable === true ? 'yes' : (s.watch_reachable === false ? 'no' : 'unknown'));
  document.getElementById('connWatchStream').textContent = watchStreamActive ? 'active' : 'idle/no samples';
  setNumberSmooth('connWatchHz', watchRate, { format: _smoothFmt.hz });
  setNumberSmooth('connWatchBatchHz', s.watch_batch_rate_hz || 0, { format: _smoothFmt.hz });
  document.getElementById('connWatchGyro').textContent = gyroOk ? 'yes' : 'no';
  document.getElementById('connWatchSkew').textContent = s.watch_clock_skew_ms != null ? `${s.watch_clock_skew_ms} ms` : '–';
  document.getElementById('connWatchGaps').textContent = s.watch_sequence_gaps ?? 0;
  document.getElementById('connWatchCommand').textContent = fmtCommand(s.watch_command);

  // Live connectivity map
  const pollDetail = watchPolling
    ? `polling · ${s.watch_poll_age_ms != null ? fmtAgo(s.watch_poll_age_ms) : 'fresh'}`
    : 'no command_poll from Watch';
  const watchState = s.watch_running
    ? `running · ${s.watch_bridge_session_id || s.session_id || 'session'}`
    : (s.session_active ? 'expected running, waiting' : 'idle');
  const sampleBridge = `${s.watch_bridge_samples ?? 0} watch · ${s.watch_bridge_delivered_samples ?? 0} delivered · ${s.watch_bridge_queued_samples ?? 0} queued`;
  const failureReason = !watchBridgeConnected
    ? 'iPhone bridge WebSocket is not connected'
    : (!watchPolling
      ? 'Watch app has not polled the iPhone yet'
      : (s.watch_bridge_failed_batches > 0
        ? `${s.watch_bridge_failed_batches} bridge batch failure(s)`
        : (watchStreamActive || !s.session_active ? 'none' : 'waiting for first /watch POST')));

  setNetworkNode('netServer', 'ok', 'status online');
  setNetworkNode('netPhone', watchBridgeConnected ? 'ok' : 'err',
                 watchBridgeConnected ? 'bridge websocket' : 'no iPhone WS');
  setNetworkNode('netWatch', watchPolling ? 'ok' : (watchBridgeConnected ? 'warn' : 'err'),
                 watchPolling ? pollDetail : 'no poll');
  setNetworkLine('netLineServerPhone', watchBridgeConnected ? 'ok' : 'err');
  setNetworkLine('netLinePhoneWatch', watchPolling ? 'ok' : (watchBridgeConnected ? 'warn' : 'err'));
  document.getElementById('netWatchPollDetail').textContent = pollDetail;
  document.getElementById('netWatchStateDetail').textContent = watchState;
  document.getElementById('netSampleBridgeDetail').textContent = sampleBridge;
  document.getElementById('netFailureDetail').textContent = failureReason;

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
}

function setPill(id, ok, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'pill ' + (cls || '');
  document.getElementById(id + 'Txt').textContent = text;
}

function setStatusCluster(s) {
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

function setBadge(id, ok, text, cls = null) {
  const el = document.getElementById(id);
  el.className = 'status-badge ' + (cls || (ok ? 'badge-ok' : 'badge-err'));
  el.textContent = text;
}

function setHealth(id, text, cls) {
  const el = document.getElementById(id);
  el.className = 'v ' + (cls || '');
  el.textContent = text;
}

// ════════════════════════════════════════════════════════════
//  TIMER
// ════════════════════════════════════════════════════════════
function startTimer() {
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

// ════════════════════════════════════════════════════════════
//  SESSION VERDICT — single 3-level summary used by both
//  the triage list (filter target) and the detail page header.
// ════════════════════════════════════════════════════════════
// Thresholds match docs/superpowers/specs/2026-05-11-sessions-tab-redesign-design.md
// and src/training docs in CLAUDE.md (σ ≤ -3 trainable, ≥ 5 min within-session).
const VERDICT_TRAINABLE = 'trainable';
const VERDICT_USABLE    = 'usable';
const VERDICT_SKIP      = 'skip';

function computeVerdict(quality, alignment, durationSec) {
  const ml = quality?.ml_readiness?.status || quality?.quality || 'unknown';
  const issues = [
    ...(quality?.ml_readiness?.blockers || []),
    ...(quality?.recording_health?.blockers || []),
  ].map(i => i.code);
  if (ml === 'bad' || issues.includes('sync_failed') || issues.includes('streams_do_not_overlap')) {
    return { level: VERDICT_SKIP, label: 'Skip' };
  }
  const sigma = alignment?.sigma_minimal_variance;
  const dur = Number(durationSec || 0);
  if (ml === 'ok' && Number.isFinite(sigma) && sigma <= -3 && dur >= 300) {
    return { level: VERDICT_TRAINABLE, label: 'Trainable' };
  }
  return { level: VERDICT_USABLE, label: 'Usable' };
}

// Filter state persists in localStorage so reloads don't drop user intent.
const FILTERS_KEY = 'sessionsFilter.v1';
const DEFAULT_FILTERS = { q: '', ml: 'all', align: 'all', minFive: false };

function loadFilters() {
  try {
    const raw = localStorage.getItem(FILTERS_KEY);
    if (!raw) return { ...DEFAULT_FILTERS };
    return { ...DEFAULT_FILTERS, ...JSON.parse(raw) };
  } catch { return { ...DEFAULT_FILTERS }; }
}
function saveFilters(f) {
  try { localStorage.setItem(FILTERS_KEY, JSON.stringify(f)); } catch {}
}
function resetFilters() { localStorage.removeItem(FILTERS_KEY); }

// ════════════════════════════════════════════════════════════
//  SESSIONS TABLE
// ════════════════════════════════════════════════════════════
async function loadSessions() {
  const [data, quality] = await Promise.all([
    api('/sessions', 'GET'),
    api('/sessions/quality', 'GET'),
  ]);
  S.allSessions = data || [];
  S.qualitySummary = quality?.summary || null;
  S.qualityBySession = {};
  (quality?.sessions || []).forEach(q => { S.qualityBySession[q.session_id] = q; });
  if (!S.validationBySession) S.validationBySession = {};
  renderQualitySummary();
  renderSessions(S.allSessions);
  if (S.selectedSessionId) await loadValidationIfNeeded(S.selectedSessionId);
}

async function loadValidationIfNeeded(sessionId) {
  if (S.validationBySession[sessionId]) {
    renderSessionValidation(sessionId);
    return;
  }
  renderSessionValidation(sessionId); // show "Loading…" panel immediately
  const v = await api(`/sessions/${encodeURIComponent(sessionId)}/validation`, 'GET');
  if (v) S.validationBySession[sessionId] = v;
  if (S.selectedSessionId === sessionId) renderSessionValidation(sessionId);
}

let _filterDebounce;
function filterSessions() {
  clearTimeout(_filterDebounce);
  _filterDebounce = setTimeout(() => {
    const q = document.getElementById('sessionSearch').value.toLowerCase();
    renderSessions(S.allSessions.filter(s =>
      s.session_id?.toLowerCase().includes(q) ||
      s.person_id?.toLowerCase().includes(q) ||
      s.description?.toLowerCase().includes(q)
    ));
  }, 200);
}

function renderSessions(rows) {
  const tbody = document.getElementById('sessionsBody');
  // Detach the validation panel before we wipe tbody.innerHTML — otherwise
  // it gets destroyed together with the detail-row that hosts it.
  const panel = document.getElementById('sessionValidationPanel');
  if (panel && panel.parentElement && panel.parentElement.classList.contains('session-detail-mount')) {
    document.getElementById('page-sessions').appendChild(panel);
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="14">
      <div class="empty-state">
        <div class="empty-state-glyph">/</div>
        <div class="empty-state-title">No recordings yet</div>
        <div class="empty-state-hint">Once you start a session from the Recording tab, it will appear here with its quality scores and a downloadable report.</div>
        <button class="empty-state-action" onclick="goHome()">Open Recording →</button>
      </div>
    </td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(s => {
    const q = S.qualityBySession[s.session_id] || {};
    const validation = S.validationBySession[s.session_id] || {};
    const watch = q.watch || {};
    const pen = q.pen || {};
    const dur = s.start_time && s.end_time
      ? fmtDuration(Math.floor((new Date(s.end_time) - new Date(s.start_time)) / 1000))
      : (s.status === 'active' ? '<em style="color:var(--accent)">live</em>' : '–');
    const startFmt = s.start_time
      ? new Date(s.start_time).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' })
      : '–';
    const statusCls = s.status === 'active' ? 'badge-warn' : 'badge-ok';
    const ml = q.ml_readiness || { status: q.quality || 'unknown', blockers: [], warnings: [], info: [] };
    const recording = q.recording_health || { status: 'unknown', blockers: [], warnings: [], info: [] };
    const diag = syncDiagnostic(q, validation);
    const signalText = [
      watch.has_gyroscope ? 'gyro' : 'no gyro',
      watch.has_accelerometer ? 'accel' : 'no accel',
      pen.has_server_time ? 'pen time' : 'legacy pen',
    ].join(' · ');
    const activeRow = S.selectedSessionId === s.session_id ? ' active' : '';
    const personLabel = (s.person_id || '').trim();
    const personCell = personLabel
      ? `<div class="session-person">${esc(personLabel)}</div>
         <div class="session-caption">${esc(s.session_id)}</div>`
      : `<div class="session-person anonymous">Anonymous</div>
         <div class="session-caption">${esc(s.session_id)}</div>`;
    const rowHtml = `<tr class="click-row${activeRow}" onclick="selectSession('${escAttr(s.session_id)}')">
      <td class="session-cell">${personCell}</td>
      <td title="${escAttr(s.description || '')}">${esc(s.description || '–')}</td>
      <td class="mono" style="font-size:11px;color:var(--text2)">${startFmt}</td>
      <td class="mono">${dur}</td>
      <td class="mono">${Number(s.watch_samples || 0).toLocaleString()}</td>
      <td class="mono">${Number(s.pen_samples || 0).toLocaleString()}</td>
      <td class="mono">${Number(s.airpods_samples || 0).toLocaleString()}</td>
      <td class="mono">${watch.estimated_hz ? fmtHz(watch.estimated_hz) : '–'}</td>
      <td class="mono" title="${esc(signalText)}">${esc(signalText)}</td>
      <td title="${escAttr(scoreTooltip(ml))}">${scoreBadge(ml)}</td>
      <td title="${escAttr(scoreTooltip(recording))}">${scoreBadge(recording)}</td>
      <td title="${escAttr(diag.message)}"><span class="status-badge ${diag.cls}">${esc(diag.label)}</span></td>
      <td><span class="status-badge ${statusCls}">${esc(s.status || 'completed')}</span></td>
      <td><a class="export-link" href="/sessions/${encodeURIComponent(s.session_id)}/report?format=md" onclick="event.stopPropagation()" title="Download Markdown report">⤓ md</a></td>
    </tr>`;
    const detailHtml = activeRow
      ? `<tr class="detail-row" data-detail-for="${escAttr(s.session_id)}"><td colspan="14"><div class="session-detail-mount" id="sessionDetailMount"></div></td></tr>`
      : '';
    return rowHtml + detailHtml;
  }).join('');

  _mountValidationPanel();
}

function _mountValidationPanel() {
  const panel = document.getElementById('sessionValidationPanel');
  if (!panel) return;
  const mount = document.getElementById('sessionDetailMount');
  if (mount) {
    if (panel.parentElement !== mount) mount.appendChild(panel);
  } else if (panel.parentElement && panel.parentElement.classList.contains('session-detail-mount')) {
    // No row selected — return panel to its original home so it stays in the DOM tree.
    document.getElementById('page-sessions').appendChild(panel);
    panel.classList.remove('active');
  }
}

function renderQualitySummary() {
  const summary = S.qualitySummary || { total: 0, ok: 0, warn: 0, bad: 0 };
  const ml = summary.ml_readiness || summary;
  document.getElementById('qualityTotal').textContent = summary.total ?? 0;
  document.getElementById('qualityOk').textContent = ml.ok ?? 0;
  document.getElementById('qualityWarn').textContent = ml.warn ?? 0;
  document.getElementById('qualityBad').textContent = ml.bad ?? 0;
}

function selectSession(sessionId) {
  S.selectedSessionId = sessionId;
  renderSessions(S.allSessions);
  loadValidationIfNeeded(sessionId);
  loadAlignmentIfNeeded(sessionId);
}

async function loadAlignmentIfNeeded(sessionId) {
  if (S.alignmentBySession[sessionId]) {
    renderAlignment(sessionId);
    return;
  }
  renderAlignment(sessionId); // show loading state
  const a = await api(`/sessions/${encodeURIComponent(sessionId)}/alignment`, 'GET');
  if (a) S.alignmentBySession[sessionId] = a;
  if (S.selectedSessionId === sessionId) renderAlignment(sessionId);
}

function _alignFmtDelta(d) {
  if (d == null || !isFinite(d)) return '–';
  const ms = d * 1000;
  if (Math.abs(ms) < 1) return '0 ms';
  if (Math.abs(d) < 1) return `${ms.toFixed(0)} ms`;
  return `${d.toFixed(2)} s`;
}

function renderAlignment(sessionId) {
  const section = document.getElementById('alignmentSection');
  const empty = document.getElementById('alignmentEmpty');
  const status = document.getElementById('alignmentStatus');
  const explainer = document.getElementById('alignmentExplainer');
  if (!section) return;
  section.style.display = 'block';

  const a = S.alignmentBySession[sessionId];

  // Loading or unavailable
  if (!a) {
    status.textContent = 'Loading…';
    status.className = 'alignment-status';
    empty.style.display = 'none';
    return;
  }
  if (a.available === false || a.error) {
    status.textContent = 'unavailable';
    status.className = 'alignment-status err';
    empty.style.display = 'block';
    document.getElementById('alignDelta').textContent = '–';
    document.getElementById('alignSigma').textContent = '–';
    document.getElementById('alignStrokes').textContent = '–';
    document.getElementById('alignFactor').textContent = '–';
    _destroyAlignCharts();
    return;
  }
  empty.style.display = 'none';

  if (a.applied) {
    status.textContent = 'angewandt';
    status.className = 'alignment-status ok';
  } else {
    status.textContent = 'verworfen (σ > −2)';
    status.className = 'alignment-status skip';
  }

  document.getElementById('alignDelta').textContent = _alignFmtDelta(a.delta_sec);
  document.getElementById('alignSigma').textContent =
    a.sigma == null ? '–' : a.sigma.toFixed(2);
  document.getElementById('alignStrokes').textContent =
    a.n_strokes != null ? a.n_strokes.toLocaleString() : '–';
  document.getElementById('alignFactor').textContent =
    a.improvement_factor != null ? `${a.improvement_factor.toFixed(1)}×` : '–';

  // Plain-language explainer
  const factorTxt = a.improvement_factor != null
    ? `Während der Pen-Striche ist die Hand <strong>${a.improvement_factor.toFixed(1)}× ruhiger</strong> als im Mittel über alle möglichen δ.`
    : '';
  let verdict = '';
  if (a.applied) {
    verdict = ` Confidence σ = <strong>${a.sigma.toFixed(2)}</strong> (Schwelle ≤ −2 für "anwenden") → der Shift von <strong>${_alignFmtDelta(a.delta_sec)}</strong> wird auf die Pen-Zeitstempel angewandt, bevor gemerged wird.`;
  } else if (a.sigma != null) {
    verdict = ` Confidence σ = <strong>${a.sigma.toFixed(2)}</strong> ist über der Schwelle (≤ −2) — die Suchkurve ist zu flach, also wird kein Shift angewandt und der Merge läuft auf den Roh-Zeitstempeln.`;
  }
  explainer.innerHTML =
    `Beim Schreiben hält die schreibende Hand die Uhr ruhig — Pausen und Gesten erzeugen mehr Bewegung. ` +
    `Der Algorithmus probiert verschiedene Zeitverschiebungen δ aus und wählt die, bei der die Pen-Striche auf die ruhigsten Phasen fallen. ` +
    factorTxt + verdict;

  _drawAlignVarianceCurve(a);
  _drawAlignTimeline(a);
}

function _destroyAlignCharts() {
  if (S.alignmentCharts.variance) { S.alignmentCharts.variance.destroy(); S.alignmentCharts.variance = null; }
  if (S.alignmentCharts.timeline) { S.alignmentCharts.timeline.destroy(); S.alignmentCharts.timeline = null; }
}

function _drawAlignVarianceCurve(a) {
  const ctx = document.getElementById('alignVarCanvas');
  if (!ctx || !window.Chart) return;
  if (S.alignmentCharts.variance) { S.alignmentCharts.variance.destroy(); S.alignmentCharts.variance = null; }
  const points = (a.variance_curve || []).filter(p => p.v != null).map(p => ({ x: p.d, y: p.v }));
  if (!points.length) return;
  const minPt = points.reduce((best, p) => (best == null || p.y < best.y) ? p : best, null);
  const ys = points.map(p => p.y);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const yPad = (yMax - yMin) * 0.12 || 0.01;

  const mean = a.mean_variance;
  const min  = a.min_variance;
  // Acceptance threshold mapped to variance scale: σ ≤ -2 means
  // variance ≤ mean + threshold*std. Reconstruct std from σ at the min:
  // σ = (min - mean) / std  ⇒  std = (min - mean) / σ
  let acceptVar = null;
  if (a.sigma != null && a.sigma !== 0 && mean != null && min != null) {
    const std = (min - mean) / a.sigma;
    if (isFinite(std) && std > 0) acceptVar = mean + a.sigma_threshold * std;
  }

  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#c79a3a';
  const text2  = css.getPropertyValue('--text2').trim() || '#555';
  const text3  = css.getPropertyValue('--text3').trim() || '#888';
  const border = css.getPropertyValue('--border').trim() || '#ddd';
  const okGreen = '#2c8a47';
  const skipAmber = '#c98c1a';
  const minColor = a.applied ? okGreen : skipAmber;

  // Annotation lines drawn via a custom plugin (no chartjs-plugin-annotation needed).
  const overlayPlugin = {
    id: 'alignVarOverlay',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: ca, scales: { x, y } } = chart;
      ctx.save();
      // Mean reference (dashed grey)
      if (mean != null && mean >= y.min && mean <= y.max) {
        const yp = y.getPixelForValue(mean);
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = text3;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(ca.left, yp); ctx.lineTo(ca.right, yp); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = text3;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
        ctx.fillText('Ø Varianz', ca.right - 4, yp - 2);
      }
      // Acceptance threshold (dashed red)
      if (acceptVar != null && acceptVar >= y.min && acceptVar <= y.max) {
        const yp = y.getPixelForValue(acceptVar);
        ctx.setLineDash([2, 4]);
        ctx.strokeStyle = '#c54a4a';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(ca.left, yp); ctx.lineTo(ca.right, yp); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#c54a4a';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillText('Akzeptanz σ ≤ −2', ca.left + 4, yp + 2);
      }
      // Vertical guide at min δ
      if (minPt) {
        const xp = x.getPixelForValue(minPt.x);
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = minColor;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(xp, ca.top); ctx.lineTo(xp, ca.bottom); ctx.stroke();
        ctx.setLineDash([]);
        // Min point dot
        const yp = y.getPixelForValue(minPt.y);
        ctx.fillStyle = minColor;
        ctx.beginPath(); ctx.arc(xp, yp, 5, 0, Math.PI * 2); ctx.fill();
        // Label
        ctx.font = '11px system-ui, sans-serif';
        const label = `δ = ${_alignFmtDelta(minPt.x)}` + (a.sigma != null ? `   σ = ${a.sigma.toFixed(2)}` : '');
        const tw = ctx.measureText(label).width + 10;
        const lx = Math.min(xp + 8, ca.right - tw - 4);
        const ly = Math.max(yp - 22, ca.top + 4);
        ctx.fillStyle = minColor;
        ctx.globalAlpha = 0.92;
        _roundRect(ctx, lx, ly, tw, 18, 4); ctx.fill();
        ctx.globalAlpha = 1;
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(label, lx + 5, ly + 9);
      }
      ctx.restore();
    },
  };

  S.alignmentCharts.variance = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Mittlere Varianz unter Stroke-Maske',
          data: points,
          borderColor: accent,
          backgroundColor: accent + '26',
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.25,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      scales: {
        x: { type: 'linear', title: { display: true, text: 'Zeitverschiebung δ (Sekunden)', color: text2, font: { size: 11 } },
             ticks: { color: text3, font: { size: 10 }, maxTicksLimit: 9 },
             grid: { color: border + '40' } },
        y: { title: { display: true, text: 'Bewegung während Strichen', color: text2, font: { size: 11 } },
             ticks: { color: text3, font: { size: 10 }, maxTicksLimit: 5 },
             grid: { color: border + '40' },
             min: yMin - yPad, suggestedMax: yMax + yPad },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: ([it]) => `δ = ${it.parsed.x.toFixed(3)} s`,
            label: (it) => `Varianz: ${it.parsed.y.toFixed(4)}`,
          },
        },
      },
    },
    plugins: [overlayPlugin],
  });
}

function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function _drawAlignTimeline(a) {
  const ctx = document.getElementById('alignTimelineCanvas');
  if (!ctx || !window.Chart) return;
  if (S.alignmentCharts.timeline) { S.alignmentCharts.timeline.destroy(); S.alignmentCharts.timeline = null; }
  const tl = a.timeline || {};
  const xs = tl.watch_var_t || [];
  const ys = tl.watch_var_y || [];
  const rawPoints = xs.map((x, i) => ({ x, y: ys[i] })).filter(p => p.y != null);
  if (!rawPoints.length) return;
  const delta = tl.delta_sec_applied || 0;
  const strokes = tl.strokes_raw || [];

  // Normalize motion intensity to 0..1 so the rails (top/bottom) and the
  // motion line use a stable shared y-axis regardless of unit.
  const yVals = rawPoints.map(p => p.y);
  const yLo = Math.min(...yVals);
  const yHi = Math.max(...yVals);
  const yRange = yHi - yLo || 1;
  const points = rawPoints.map(p => ({ x: p.x, y: (p.y - yLo) / yRange }));

  const css = getComputedStyle(document.documentElement);
  const text2  = css.getPropertyValue('--text2').trim() || '#555';
  const text3  = css.getPropertyValue('--text3').trim() || '#888';
  const border = css.getPropertyValue('--border').trim() || '#ddd';
  const accent = css.getPropertyValue('--accent').trim() || '#c79a3a';

  const beforeColor = '#c54a4a';
  const afterColor  = '#2c8a47';

  // Reserve y-bands: rails sit at y in [1.05, 1.18] (red, before)
  // and [-0.18, -0.05] (green, after). Motion lives in [0, 1].
  const RAIL_TOP_Y0 = 1.05, RAIL_TOP_Y1 = 1.20;
  const RAIL_BOT_Y0 = -0.20, RAIL_BOT_Y1 = -0.05;

  const railsPlugin = {
    id: 'alignRails',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: ca, scales: { x, y } } = chart;
      ctx.save();

      const drawRail = (start, end, color, yTop, yBottom, alpha) => {
        const x0 = x.getPixelForValue(start);
        const x1 = x.getPixelForValue(end);
        if (x1 < ca.left || x0 > ca.right) return;
        const yA = y.getPixelForValue(yTop);
        const yB = y.getPixelForValue(yBottom);
        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.fillRect(
          Math.max(x0, ca.left), Math.min(yA, yB),
          Math.max(1.5, Math.min(x1, ca.right) - Math.max(x0, ca.left)),
          Math.abs(yB - yA),
        );
      };

      // Background tracks for rails (so empty regions still read as rails)
      ctx.fillStyle = beforeColor;
      ctx.globalAlpha = 0.06;
      const yT0 = y.getPixelForValue(RAIL_TOP_Y0), yT1 = y.getPixelForValue(RAIL_TOP_Y1);
      ctx.fillRect(ca.left, Math.min(yT0, yT1), ca.right - ca.left, Math.abs(yT1 - yT0));
      if (delta) {
        ctx.fillStyle = afterColor;
        const yB0 = y.getPixelForValue(RAIL_BOT_Y0), yB1 = y.getPixelForValue(RAIL_BOT_Y1);
        ctx.fillRect(ca.left, Math.min(yB0, yB1), ca.right - ca.left, Math.abs(yB1 - yB0));
      }
      ctx.globalAlpha = 1;

      // Strokes (before shift) on top rail
      strokes.forEach(s => drawRail(s.start_s, s.end_s, beforeColor, RAIL_TOP_Y0, RAIL_TOP_Y1, 0.85));
      // Strokes (after shift) on bottom rail — only meaningful if shift applied
      if (delta) {
        strokes.forEach(s => drawRail(s.start_s + delta, s.end_s + delta, afterColor, RAIL_BOT_Y0, RAIL_BOT_Y1, 0.85));
      }

      // Rail labels
      ctx.fillStyle = beforeColor;
      ctx.font = '10px system-ui, sans-serif';
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      const yTopMid = y.getPixelForValue((RAIL_TOP_Y0 + RAIL_TOP_Y1) / 2);
      ctx.fillText('Pen-Striche · roh', ca.left + 6, yTopMid);
      if (delta) {
        ctx.fillStyle = afterColor;
        const yBotMid = y.getPixelForValue((RAIL_BOT_Y0 + RAIL_BOT_Y1) / 2);
        ctx.fillText(`Pen-Striche · nach δ = ${_alignFmtDelta(delta)}`, ca.left + 6, yBotMid);
      }

      ctx.restore();
    },
  };

  const datasets = [
    {
      label: 'Watch-Bewegung',
      data: points,
      borderColor: accent,
      backgroundColor: accent + '1f',
      borderWidth: 1.6,
      pointRadius: 0,
      tension: 0.3,
      fill: 'origin',
    },
  ];

  S.alignmentCharts.timeline = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      scales: {
        x: { type: 'linear',
             title: { display: true, text: 'Zeit seit Watch-Start (s)', color: text2, font: { size: 11 } },
             ticks: { color: text3, font: { size: 10 }, maxTicksLimit: 8 },
             grid: { color: border + '40' } },
        y: { title: { display: true, text: 'Bewegung (normalisiert)', color: text2, font: { size: 11 } },
             ticks: {
               color: text3, font: { size: 10 },
               callback: (v) => (v >= 0 && v <= 1) ? v.toFixed(1) : '',
               stepSize: 0.25,
             },
             grid: { color: border + '40' },
             min: RAIL_BOT_Y0 - 0.02, max: RAIL_TOP_Y1 + 0.02 },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (it) => it.datasetIndex === 0,
          callbacks: {
            title: ([it]) => `t = ${it.parsed.x.toFixed(2)} s`,
            label: (it) => `Bewegung: ${(it.parsed.y * 100).toFixed(0)}%`,
          },
        },
      },
    },
    plugins: [railsPlugin],
  });
}

function renderSessionValidation(sessionId) {
  const panel = document.getElementById('sessionValidationPanel');
  const v = S.validationBySession[sessionId];
  const q = S.qualityBySession[sessionId] || {};
  panel.classList.add('active');

  if (!v) {
    document.getElementById('validationTitle').textContent = `Session ${sessionId}`;
    document.getElementById('validationOverall').textContent = 'Loading…';
    document.getElementById('validationTimeline').innerHTML = '';
    document.getElementById('validationSummary').textContent = 'Validation is loading or unavailable.';
    return;
  }

  const duration = v.timeline_for_chart?.duration_s ?? v.watch?.duration_seconds ?? 0;
  const ml = q.ml_readiness || { status: v.status || q.quality || 'unknown', blockers: [], warnings: [], info: [] };
  const recording = q.recording_health || { status: 'unknown', blockers: [], warnings: [], info: [] };
  const diag = syncDiagnostic(q, v);
  document.getElementById('validationTitle').textContent = `Session ${sessionId} — ${fmtDuration(Math.round(duration || 0))} duration`;
  document.getElementById('validationOverall').textContent =
    `ML: ${ml.status || 'unknown'} · Recording: ${recording.status || 'unknown'}`;
  document.getElementById('validationMlReady').textContent = ml.status || 'unknown';
  document.getElementById('validationRecording').textContent = recording.status || 'unknown';
  document.getElementById('validationPenPct').textContent = v.overlap?.pen_dots_in_watch_range_pct != null
    ? `${Math.round(v.overlap.pen_dots_in_watch_range_pct * 1000) / 10}%`
    : '–';
  document.getElementById('validationSyncDiagnostic').textContent = diag.label;
  document.getElementById('driftWatch').textContent = fmtMs(v.source_clocks?.watch_source_to_local_drift_ms);
  document.getElementById('driftPen').textContent = fmtMs(v.source_clocks?.pen_source_to_local_drift_ms);
  document.getElementById('driftRelative').textContent = fmtMs(v.source_clocks?.relative_pen_vs_watch_clock_drift_ms);
  document.getElementById('driftSyncOffset').textContent = fmtClockGap(
    v.source_clocks?.source_clock_offset_gap_ms,
    v.sync_estimate
  );

  document.getElementById('validationTimeline').innerHTML = renderTimeline(v);
  const intervals = v.timeline_for_chart?.pen_events?.length || 0;
  document.getElementById('validationSummary').textContent =
    `Watch: ${Number(v.watch?.total_samples || 0).toLocaleString()} samples over ${fmtSec(v.watch?.duration_seconds)} | ` +
    `Pen: ${intervals} writing intervals, ${Number(v.pen?.total_dots || 0).toLocaleString()} dots over ${fmtSec(v.pen?.duration_seconds)}. ` +
    `Sync diagnostics are optional calibration hints and do not reduce session quality.`;
  const actionableIssues = [
    ...(ml.blockers || []), ...(ml.warnings || []),
    ...(recording.blockers || []), ...(recording.warnings || []),
  ];
  document.getElementById('validationIssues').innerHTML = actionableIssues.length
    ? actionableIssues.map(i => `<span class="issue-chip" title="${escAttr(i.message || '')}">${esc(i.code)}</span>`).join('')
    : '<span class="issue-chip">no blocking issues</span>';
}

function renderTimeline(v) {
  const tl = v.timeline_for_chart || {};
  const duration = Math.max(1, Number(tl.duration_s || 1));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => {
    const sec = Math.round(duration * t);
    return `<span class="axis-tick" style="left:${t * 100}%">${sec}s</span>`;
  }).join('');
  const watchStart = pct(tl.watch_start_s || 0, duration);
  const watchWidth = pct((tl.watch_end_s || 0) - (tl.watch_start_s || 0), duration);
  const penStart = pct(tl.pen_start_s || 0, duration);
  const penWidth = pct((tl.pen_end_s || 0) - (tl.pen_start_s || 0), duration);
  const penBlocks = (tl.pen_events || []).map(ev => {
    const left = pct(ev.start_s, duration);
    const width = Math.max(0.2, pct(ev.end_s - ev.start_s, duration));
    return `<span class="timeline-bar bar-pen" title="${fmtSec(ev.duration_s)} · ${ev.dot_count || 0} dots" style="left:${left}%;width:${width}%"></span>`;
  }).join('');
  return `
    <div class="timeline-axis">${ticks}</div>
    <div class="timeline-row">
      <div class="timeline-label">Watch</div>
      <div class="timeline-track">
        <span class="timeline-bar bar-watch" style="left:${watchStart}%;width:${Math.max(0.2, watchWidth)}%"></span>
      </div>
    </div>
    <div class="timeline-row">
      <div class="timeline-label">Pen</div>
      <div class="timeline-track">
        <span class="timeline-bar bar-gap" style="left:${penStart}%;width:${Math.max(0.2, penWidth)}%"></span>
        ${penBlocks}
      </div>
    </div>`;
}

function pct(value, total) {
  const n = Number(value || 0);
  const d = Math.max(1, Number(total || 1));
  return Math.max(0, Math.min(100, n / d * 100));
}

// ════════════════════════════════════════════════════════════
//  CONNECTIONS PAGE
// ════════════════════════════════════════════════════════════
function updateConnectionsPage() {
  setBadge('connPenBadge', S.penConnected, S.penConnected ? 'Connected' : 'Disconnected');
  setBadge('connWatchBadge', S.watchConnected, S.watchStatusText || (S.watchConnected ? 'Active' : 'Offline'), S.watchBadgeClass);
  document.getElementById('uptimeVal').textContent = fmtUptime(S.uptime);
  document.getElementById('uptimeSession').textContent = S.sessionId || 'None';
}

// ════════════════════════════════════════════════════════════
//  LOG RENDERING + SETTINGS
// ════════════════════════════════════════════════════════════
function renderLogs() {
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

function setTheme(theme) {
  S.theme = theme === 'dark' ? 'dark' : 'light';
  localStorage.setItem('theme', S.theme);
  document.body.dataset.theme = S.theme;
  // Optionaler Settings-Select auf der System-Page bleibt synchron
  const sel = document.getElementById('themeSelect');
  if (sel) sel.value = S.theme;
  // Glyph im Topbar-Toggle: zeige das *gegenteilige* Symbol (was man kriegt
  // wenn man klickt). Light → Mond, Dark → Sonne.
  const glyph = document.getElementById('themeToggleGlyph');
  if (glyph) glyph.textContent = S.theme === 'dark' ? '☀' : '☾';
}

function toggleTheme() {
  setTheme(S.theme === 'dark' ? 'light' : 'dark');
}

function setLogRows(value) {
  S.logRows = Number(value) || 24;
  localStorage.setItem('logRows', String(S.logRows));
  document.getElementById('logRowsSelect').value = String(S.logRows);
  renderLogs();
}

// ════════════════════════════════════════════════════════════
//  HELPERS
// ════════════════════════════════════════════════════════════
async function api(path, method = 'GET', body = null) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) data.http_status = res.status;
    return data;
  } catch (e) {
    toast('⚠ Server unreachable');
    return null;
  }
}

async function downloadDebugPackage() {
  const pkg = await api('/debug/package');
  if (!pkg) return;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ml4scs_debug_${stamp}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast('Debug package exported');
}

function fmtDuration(sec) {
  const h = Math.floor(sec / 3600).toString().padStart(2, '0');
  const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
  const s = (sec % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function fmtHz(value) {
  const n = Number(value || 0);
  return n > 0 ? `${n.toFixed(n >= 10 ? 1 : 2)} Hz` : '– Hz';
}

function fmtNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : '–';
}

// Pen- und Watch-Geräteuhren teilen sich keine Epoche — bei großem Versatz
// zeigen wir das kategorisch statt als alarmierende Tage-Zahl. Für die
// session-level Overlap-Checks irrelevant; Sample-Level-Merge braucht
// separat einen Sync-Offset (Tap-Event o.ä.).
function fmtClockGap(gapMs, syncEstimate) {
  const n = Number(gapMs);
  if (Number.isFinite(n)) {
    if (Math.abs(n) > 300000) return 'different device clocks · sync needed for merge';
    return fmtMs(n);
  }
  return syncEstimate?.usable ? fmtMs(syncEstimate.median_offset_ms) : 'not estimated';
}

function fmtMs(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '–';
  const rounded = `${Math.round(n)}ms`;
  const abs = Math.abs(n);
  if (abs >= 86400000) return `${rounded} (~${(n / 86400000).toFixed(1)}d)`;
  if (abs >= 3600000) return `${rounded} (~${(n / 3600000).toFixed(1)}h)`;
  if (abs >= 60000) return `${rounded} (~${(n / 60000).toFixed(1)}min)`;
  if (abs >= 1000) return `${rounded} (~${(n / 1000).toFixed(1)}s)`;
  return rounded;
}

function fmtSec(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n)}s` : '–';
}

function fmtAgo(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n)) return '–';
  if (n < 1200) return 'just now';
  if (n < 60000) return `${Math.round(n / 1000)}s ago`;
  return `${Math.round(n / 60000)}m ago`;
}

function fmtClock(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n)) return '--:--:--';
  return new Date(n).toLocaleTimeString('de-DE', { hour12: false });
}

function fmtCommand(cmd) {
  if (!cmd || !cmd.command) return '–';
  const ok = cmd.ok === true ? 'ok' : (cmd.ok === false ? 'failed' : 'pending');
  const id = cmd.command_id ? ` · ${cmd.command_id}` : '';
  return `${cmd.command} · ${ok}${id}`;
}

function fmtUptime(sec) {
  if (!sec) return '–';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`;
  return `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`;
}

function statusBadgeClass(status) {
  if (status === 'ok') return 'badge-ok';
  if (status === 'bad') return 'badge-err';
  if (status === 'warn') return 'badge-warn';
  return 'badge-warn';
}

function scoreBadge(score) {
  const status = score?.status || 'unknown';
  return `<span class="status-badge ${statusBadgeClass(status)}">${esc(status)}</span>`;
}

function scoreTooltip(score) {
  const parts = [
    ...(score?.blockers || []),
    ...(score?.warnings || []),
    ...(score?.info || []),
  ].map(i => i.code);
  return parts.length ? parts.join(', ') : 'ready';
}

function syncDiagnostic(q, validation) {
  const fromQuality = q?.diagnostics?.sync_diagnostic;
  const fromValidation = validation?.sync_diagnostic;
  const sync = q?.diagnostics?.sync_estimate || validation?.sync_estimate || {};
  const diagnostic = fromQuality || fromValidation;
  if (diagnostic) {
    return {
      label: diagnostic.label || diagnostic.status || 'not required',
      message: diagnostic.message || 'Optional sync diagnostic; not used for quality.',
      cls: diagnostic.status === 'needs_explicit_tap_protocol' ? 'badge-warn' : 'badge-ok',
    };
  }
  if (sync.usable) {
    return {
      label: `estimated (${sync.confidence || 'unknown'})`,
      message: 'Optional tap/peak calibration estimate is available.',
      cls: 'badge-ok',
    };
  }
  return {
    label: 'not required',
    message: sync.reason || 'No explicit tap/peak calibration pattern was detected; this is not a quality failure.',
    cls: 'badge-ok',
  };
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[ch]));
}

function escAttr(value) {
  return esc(value).replace(/`/g, '&#096;');
}

let toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}

// ════════════════════════════════════════════════════════════
//  INIT
// ════════════════════════════════════════════════════════════
document.getElementById('timer').textContent = '00:00:00';
setTheme(S.theme);
setLogRows(S.logRows);

// Initial status fetch
api('/status').then(s => { if (s) handleStatus({ type: 'status', ...s, chart: [] }); });

connectWs();
