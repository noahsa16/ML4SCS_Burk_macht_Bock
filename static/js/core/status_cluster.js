// status_cluster.js — topbar status cluster and live-status DOM handler.
//
// Chart, pen-canvas, timer, logs, and all Recording-page DOM updates
// have moved to pages/recording.js (Task 13).

import { S } from '/static/js/core/state.js';
import { clearPenPreview } from '/static/js/pages/recording.js';
import {
  fmtHz, fmtAgo, fmtUptime,
} from '/static/js/core/format.js';

// ════════════════════════════════════════════════════════════
//  ACTIVE-PAGE DISPATCHER
// ════════════════════════════════════════════════════════════
let _activePageDispatch = () => {};
export function setActivePageDispatcher(fn) { _activePageDispatch = fn; }

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
  setDot('clusterDotAirpods', s.airpods);
  setDot('clusterDotServer', s.server);

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

// ════════════════════════════════════════════════════════════
//  STATUS HOVER-CARD
// ════════════════════════════════════════════════════════════
function _hoverRow(device, info) {
  const row = document.querySelector(`.status-hover-row[data-device="${device}"]`);
  if (!row) return;
  const stateEl = row.querySelector('.status-hover-state');
  const metaEl  = row.querySelector('.status-hover-meta');
  if (stateEl) stateEl.textContent = info.state;
  if (metaEl)  metaEl.textContent  = info.meta;
  row.removeAttribute('data-device-ok');
  row.removeAttribute('data-device-warn');
  row.removeAttribute('data-device-err');
  if      (info.cls === 'ok')   row.setAttribute('data-device-ok',   '');
  else if (info.cls === 'warn') row.setAttribute('data-device-warn', '');
  else if (info.cls === 'err')  row.setAttribute('data-device-err',  '');
}

function _penStatusFromS(s) {
  if (!s) return { cls: 'err', state: 'offline', meta: '— Hz · —' };
  const ok  = !!s.pen_connected;
  const hz  = s.pen_rate_hz != null ? fmtHz(s.pen_rate_hz) : '—';
  const ago = s.pen_last_seen_ms_ago != null ? fmtAgo(s.pen_last_seen_ms_ago) : '—';
  return { cls: ok ? 'ok' : 'err', state: ok ? 'connected' : 'offline', meta: `${hz} · last ${ago}` };
}

function _watchStatusFromS(s) {
  if (!s) return { cls: 'err', state: 'offline', meta: '— Hz · —' };
  const streamActive = !!(s.watch_stream_active ?? s.watch_connected);
  const bridgeReady  = !!(s.watch_bridge_connected);
  const cls   = streamActive ? 'ok' : (bridgeReady ? 'warn' : 'err');
  const state = s.watch_status_text || (streamActive ? 'streaming' : (bridgeReady ? 'bridge ready' : 'offline'));
  const hz    = s.watch_rate_hz != null ? fmtHz(s.watch_rate_hz) : '—';
  const samp  = s.watch_samples != null ? `${s.watch_samples} samples` : '—';
  return { cls, state, meta: `${hz} · ${samp}` };
}

function _airpodsStatusFromS(s) {
  if (!s) return { cls: 'err', state: 'offline', meta: '— Hz · —' };
  const ok  = !!(s.airpods_connected || s.airpods_paired || s.airpods_streaming);
  const hz  = s.airpods_rate_hz != null ? fmtHz(s.airpods_rate_hz) : '—';
  const samp = s.airpods_samples != null ? `${s.airpods_samples} samples` : '—';
  return { cls: ok ? 'ok' : 'err', state: ok ? 'connected' : 'offline', meta: `${hz} · ${samp}` };
}

function _serverStatusFromS(s) {
  if (!s) return { cls: 'err', state: 'connecting', meta: '—' };
  const uptime = s.uptime_seconds != null ? `up ${fmtUptime(s.uptime_seconds)}` : '—';
  return { cls: 'ok', state: 'ok', meta: uptime };
}

export function _renderStatusHoverCard(s) {
  _hoverRow('pen',     _penStatusFromS(s));
  _hoverRow('watch',   _watchStatusFromS(s));
  _hoverRow('airpods', _airpodsStatusFromS(s));
  _hoverRow('server',  _serverStatusFromS(s));
}

export function setPill(id, ok, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'pill ' + (cls || '');
  document.getElementById(id + 'Txt').textContent = text;
}

export function setBadge(id, ok, text, cls = null) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'status-badge ' + (cls || (ok ? 'badge-ok' : 'badge-err'));
  el.textContent = text;
}

export function setHealth(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'v ' + (cls || '');
  el.textContent = text;
}

// ════════════════════════════════════════════════════════════
//  STATUS HANDLER
// ════════════════════════════════════════════════════════════
export function handleStatus(s, prevSessionId) {
  // S.xxx state mutations already applied by updateFromStatus(s) before this call.
  // prevSessionId captured by caller BEFORE updateFromStatus so session-change
  // detection sees the correct old value.
  if (s.session_id !== prevSessionId) clearPenPreview();

  const watchRate = Number(s.watch_rate_hz || 0);
  const validation = s.validation || {};
  const clients = s.connected_clients || {};
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

  // Topbar status cluster
  const penDotState = s.pen_connected ? 'ok' : 'err';
  const watchDotState = (watchStreamActive || watchReachable || watchPolling)
    ? 'ok' : (watchBridgeConnected ? 'warn' : 'err');
  const airpodsUiOnline = !!(s.airpods_connected || s.airpods_paired || s.airpods_streaming);
  const airpodsDotState = airpodsUiOnline ? 'ok' : 'err';
  setStatusCluster({
    pen: penDotState, watch: watchDotState, airpods: airpodsDotState, server: 'ok',
    sessionActive: s.session_active,
    watchRate, watchStatusText,
    penDots: s.pen_samples, watchSamples: s.watch_samples,
    uptime: s.uptime_seconds,
  });
  _renderStatusHoverCard(s);

  // Route the tick to whichever page is currently visible — hidden pages skip work.
  _activePageDispatch(s);
}
