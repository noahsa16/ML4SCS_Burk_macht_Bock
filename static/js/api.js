import { toast } from './utils.js';

let ws;
let wsReconnectTimer;
let wsHandlers = { handleStatus: () => {}, loadSessions: () => {} };

export function connectWs(handlers = {}) {
  wsHandlers = { ...wsHandlers, ...handlers };
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    setWsStatus('ok');
    ws.send(JSON.stringify({ type: 'hello', client: 'dashboard' }));
  };

  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.type === 'status') wsHandlers.handleStatus(msg);
    else if (msg.type === 'start') toast(`▶ Session ${msg.session_id} started`);
    else if (msg.type === 'stop') {
      toast(`■ Session ${msg.session_id} stopped`);
      if (document.querySelector('.nav-item.active')?.dataset.page === 'sessions') wsHandlers.loadSessions();
    }
  };

  ws.onclose = () => {
    setWsStatus('err');
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(() => connectWs(wsHandlers), 3000);
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

export async function api(path, method = 'GET', body = null) {
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
