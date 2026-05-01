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
  selectedSessionId: null,
  watchStatusText: 'Offline',
  watchBadgeClass: 'badge-err',
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

document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    const p = el.dataset.page;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
    document.getElementById('page-' + p).classList.add('active');
    const m = pageMeta[p];
    document.getElementById('pageTitle').textContent = m.title;
    document.getElementById('pageSub').textContent = m.sub;
    if (p === 'sessions') loadSessions();
    if (p === 'connections') updateConnectionsPage();
  });
});

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

  document.getElementById('statMag').textContent = curAcc.toFixed(3);
  document.getElementById('statGyro').textContent = curGyro.toFixed(3);
  document.getElementById('statWritePct').textContent = writePct + '%';
}

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
    else if (msg.type === 'stop') { toast(`■ Session ${msg.session_id} stopped`); if (document.querySelector('.nav-item.active')?.dataset.page === 'sessions') loadSessions(); }
  };

  ws.onclose = () => {
    setWsStatus('err');
    wsReconnectTimer = setTimeout(connectWs, 3000);
  };

  ws.onerror = () => { ws.close(); };
}

function setWsStatus(st) {
  const dot = document.getElementById('wsDot');
  const lbl = document.getElementById('wsLabel');
  dot.className = 'ws-dot';
  if (st === 'ok') { dot.classList.add('ok'); lbl.textContent = 'WS connected'; }
  else { lbl.textContent = 'WS reconnecting…'; }
  document.getElementById('uptimeWs').textContent = st === 'ok' ? 'Connected' : 'Reconnecting';
}

// ════════════════════════════════════════════════════════════
//  STATUS HANDLER
// ════════════════════════════════════════════════════════════
function handleStatus(s) {
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
  const watchUiOnline = watchStreamActive || watchDirectConnected || watchReachable || watchBridgeConnected;
  const watchStatusText = watchStreamActive
    ? 'Streaming'
    : (watchDirectConnected ? 'Direct · Connected'
    : (watchReachable ? 'Reachable' : (watchBridgeConnected ? 'Bridge ready' : 'Offline')));
  const watchBadgeClass = watchStreamActive || watchDirectConnected || watchReachable ? 'badge-ok' : (watchBridgeConnected ? 'badge-warn' : 'badge-err');
  S.watchConnected = watchUiOnline;
  S.watchStatusText = watchStatusText;
  S.watchBadgeClass = watchBadgeClass;

  // Pills
  setPill('pillPen', s.pen_connected, `Pen · ${s.pen_samples} dots`, s.pen_connected ? 'ok' : 'err');
  setPill('pillWatch', watchUiOnline, `Watch · ${watchStatusText} · ${fmtHz(watchRate)}`, watchStreamActive || watchReachable ? 'ok' : (watchBridgeConnected ? 'warn' : 'err'));
  setPill('pillServer', true, `Server · ${fmtUptime(s.uptime_seconds)}`, 'ok');

  // Counts
  document.getElementById('watchCount').textContent = s.watch_samples.toLocaleString();
  document.getElementById('penCount').textContent = s.pen_samples.toLocaleString();
  document.getElementById('sessionIdDisp').textContent = s.session_id || '—';
  document.getElementById('watchRateMain').textContent = fmtHz(watchRate);
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
  document.getElementById('penRateSide').textContent = fmtHz(penRate);
  document.getElementById('watchRateSide').textContent = fmtHz(watchRate);
  document.getElementById('watchGyroSide').textContent = lastWatch.gyro_mag != null ? fmtNum(lastWatch.gyro_mag) : '–';
  document.getElementById('watchLastTs').textContent = s.watch_last_seen_ms_ago != null ? fmtAgo(s.watch_last_seen_ms_ago) : '–';

  // Health metrics
  setHealth('watchHz', fmtHz(watchRate), watchRate > 40 ? 'ok' : (watchRate > 0 ? 'warn' : 'err'));
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
  document.getElementById('connPenHz').textContent = fmtHz(penRate);
  document.getElementById('connPenLast').textContent = lastPen.dot_type ? `${lastPen.dot_type} · ${fmtNum(lastPen.x)}, ${fmtNum(lastPen.y)}` : '–';
  document.getElementById('connPenClock').textContent = penClockOk ? 'ok' : 'legacy/missing';
  document.getElementById('connWatchBridge').textContent = watchBridgeConnected ? 'connected' : 'not connected';
  document.getElementById('connWatchReachable').textContent = s.watch_reachable === true ? 'yes' : (s.watch_reachable === false ? 'no' : 'unknown');
  document.getElementById('connWatchStream').textContent = watchStreamActive ? 'active' : 'idle/no samples';
  document.getElementById('connWatchHz').textContent = fmtHz(watchRate);
  document.getElementById('connWatchBatchHz').textContent = fmtHz(s.watch_batch_rate_hz || 0);
  document.getElementById('connWatchGyro').textContent = gyroOk ? 'yes' : 'no';
  document.getElementById('connWatchSkew').textContent = s.watch_clock_skew_ms != null ? `${s.watch_clock_skew_ms} ms` : '–';
  document.getElementById('connWatchGaps').textContent = s.watch_sequence_gaps ?? 0;
  document.getElementById('connWatchCommand').textContent = fmtCommand(s.watch_command);

  // System checks
  document.getElementById('checkAccel').textContent = validation.watch_has_accelerometer ? 'ok' : 'missing';
  document.getElementById('checkGyro').textContent = gyroOk ? 'ok' : 'missing';
  document.getElementById('checkPenTime').textContent = penClockOk ? 'ok' : 'new recordings only';
  document.getElementById('checkRate').textContent = `${fmtHz(watchRate)} watch · ${fmtHz(penRate)} pen`;

  renderLogs();

  // Chart
  if (s.chart) updateChart(s.chart);

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
  el.className = 'pill ' + (cls || '');
  document.getElementById(id + 'Txt').textContent = text;
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
    await api('/session/stop', 'POST');
    toast('Session stopped');
    S.chartMax = 0;
  } else {
    const pid = document.getElementById('personId').value.trim() || 'unknown';
    const description = document.getElementById('sessionDescription').value.trim();
    const res = await api('/session/start', 'POST', { person_id: pid, description });
    if (res?.session_id) toast(`▶ Session ${res.session_id} started`);
  }
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
  S.validationBySession = {};
  const validations = await Promise.all((S.allSessions || []).map(s =>
    api(`/sessions/${encodeURIComponent(s.session_id)}/validation`, 'GET')
      .then(v => ({ sid: s.session_id, validation: v }))
  ));
  validations.forEach(({ sid, validation }) => {
    if (validation) S.validationBySession[sid] = validation;
  });
  renderQualitySummary();
  renderSessions(S.allSessions);
  if (S.selectedSessionId) renderSessionValidation(S.selectedSessionId);
}

function filterSessions() {
  const q = document.getElementById('sessionSearch').value.toLowerCase();
  renderSessions(S.allSessions.filter(s =>
    s.session_id?.toLowerCase().includes(q) ||
    s.person_id?.toLowerCase().includes(q) ||
    s.description?.toLowerCase().includes(q)
  ));
}

function renderSessions(rows) {
  const tbody = document.getElementById('sessionsBody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="13" class="table-empty">No sessions found</td></tr>';
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
    return `<tr class="click-row${activeRow}" onclick="selectSession('${escAttr(s.session_id)}')">
      <td class="mono bold">${esc(s.session_id)}</td>
      <td>${esc(s.person_id || '–')}</td>
      <td title="${escAttr(s.description || '')}">${esc(s.description || '–')}</td>
      <td class="mono" style="font-size:11px;color:var(--text2)">${startFmt}</td>
      <td class="mono">${dur}</td>
      <td class="mono">${Number(s.watch_samples || 0).toLocaleString()}</td>
      <td class="mono">${Number(s.pen_samples || 0).toLocaleString()}</td>
      <td class="mono">${watch.estimated_hz ? fmtHz(watch.estimated_hz) : '–'}</td>
      <td class="mono" title="${esc(signalText)}">${esc(signalText)}</td>
      <td title="${escAttr(scoreTooltip(ml))}">${scoreBadge(ml)}</td>
      <td title="${escAttr(scoreTooltip(recording))}">${scoreBadge(recording)}</td>
      <td title="${escAttr(diag.message)}"><span class="status-badge ${diag.cls}">${esc(diag.label)}</span></td>
      <td><span class="status-badge ${statusCls}">${esc(s.status || 'completed')}</span></td>
    </tr>`;
  }).join('');
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
  renderSessionValidation(sessionId);
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
  document.getElementById('driftSyncOffset').textContent = v.source_clocks?.source_clock_offset_gap_ms != null
    ? fmtMs(v.source_clocks.source_clock_offset_gap_ms)
    : (v.sync_estimate?.usable ? fmtMs(v.sync_estimate.median_offset_ms) : 'not estimated');

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
  document.getElementById('themeSelect').value = S.theme;
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
    return await res.json();
  } catch (e) {
    toast('⚠ Server unreachable');
    return null;
  }
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
  return `${cmd.command} · ${ok}`;
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
