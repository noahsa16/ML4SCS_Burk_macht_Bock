// static/js/pages/connections.js — Connections page module

import { setBadge } from '/static/js/core/status_cluster.js';
import { setNumberSmooth } from '/static/js/core/anim.js';
import {
  fmtUptime, fmtAgo, fmtHz, fmtCommand, fmtNum,
} from '/static/js/core/format.js';
import { renderState } from '/static/js/core/states.js';

let _mounted = false;
let _container = null;

// ────────────────────────────────────────────────────────────
//  MODULE-PRIVATE HELPERS (moved out of status_cluster.js)
// ────────────────────────────────────────────────────────────
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

const _smoothFmt = {
  hz: (v) => v > 0 ? `${v.toFixed(v >= 10 ? 1 : 2)} Hz` : '– Hz',
};

function _toggleConnEmpty(slotId, connected, title) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  if (connected) {
    slot.style.display = 'none';
    renderState(slot, 'clear');
  } else {
    slot.style.display = '';
    renderState(slot, 'empty', { title, inline: true });
  }
}

// ────────────────────────────────────────────────────────────
//  PAGE LIFECYCLE
// ────────────────────────────────────────────────────────────
export function mount(container) {
  if (_mounted) return;
  _container = container;
  // Why: no Connections-specific one-time DOM wiring needed; all inline
  // onclick handlers (penConnect, penDisconnect, watchCmd, downloadDebugPackage)
  // are already exposed on window from dashboard.js.
  _mounted = true;
}

export function onStatus(s) {
  const watchRate = Number(s.watch_rate_hz || 0);
  const penRate = Number(s.pen_rate_hz || 0);
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

  setBadge('connPenBadge', s.pen_connected, s.pen_connected ? 'Connected' : 'Disconnected');
  setBadge('connWatchBadge', watchUiOnline, watchStatusText, watchBadgeClass);
  _toggleConnEmpty('connPenEmpty', !!s.pen_connected,
    'Connect the pen to populate live data');
  _toggleConnEmpty('connWatchEmpty', !!watchUiOnline,
    'Connect the watch app to populate live data');
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
}

export function onShow() {
  // Why: onStatus is called each tick, so state is already fresh on entry.
  // No additional refresh needed here.
}

export function onHide() {
  // No rAF loops or timers to clean up.
}
