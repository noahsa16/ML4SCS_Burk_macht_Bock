// ws.js — WebSocket connection to the server, reconnection + backoff logic.
// Drives handleStatus on every 'status' tick and dispatches toast on
// session start/stop events.

import { S, updateFromStatus } from '/static/js/core/state.js';
import { handleStatus } from '/static/js/core/status_cluster.js';
import { toast } from '/static/js/core/toast.js';

// Temporary: loadSessions moves to pages/sessions.js in Task 9
import { loadSessions } from '/static/dashboard.js';

let ws, wsReconnectTimer;

export function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setWsStatus('ok');
    ws.send(JSON.stringify({ type: 'hello', client: 'dashboard' }));
  };

  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.type === 'status') {
      // Capture prevSessionId before updateFromStatus overwrites S.lastStatus
      const prevSessionId = S.lastStatus?.session_id ?? null;
      updateFromStatus(msg);
      handleStatus(msg, prevSessionId);
    } else if (msg.type === 'start') {
      toast(`▶ Session ${msg.session_id} started`);
    } else if (msg.type === 'stop') {
      toast(`■ Session ${msg.session_id} stopped`);
      if (document.querySelector('.tab.active')?.dataset.page === 'sessions') loadSessions();
    }
  };

  ws.onclose = () => {
    setWsStatus('err');
    wsReconnectTimer = setTimeout(connectWs, 3000);
  };

  ws.onerror = () => { ws.close(); };
}

export function setWsStatus(st) {
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
