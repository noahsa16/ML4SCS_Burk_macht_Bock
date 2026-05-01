import { api } from './api.js';
import { updateChart } from './chart.js';
import { S } from './state.js';
import { esc, fmtAgo, fmtClock, fmtCommand, fmtDuration, fmtHz, fmtNum, fmtUptime, toast } from './utils.js';

export function handleStatus(s) {
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
export async function toggleSession() {
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
//  CONNECTIONS PAGE
// ════════════════════════════════════════════════════════════
export function updateConnectionsPage() {
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

export function clearVisualLogs() {
  S.sampleLog = [];
  S.eventLog = [];
  renderLogs();
}

export function setTheme(theme) {
  S.theme = theme === 'dark' ? 'dark' : 'light';
  localStorage.setItem('theme', S.theme);
  document.body.dataset.theme = S.theme;
  document.getElementById('themeSelect').value = S.theme;
}

export function setLogRows(value) {
  S.logRows = Number(value) || 24;
  localStorage.setItem('logRows', String(S.logRows));
  document.getElementById('logRowsSelect').value = String(S.logRows);
  renderLogs();
}

