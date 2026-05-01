import { api, connectWs } from './api.js';
import { S } from './state.js';
import { clearVisualLogs, handleStatus, penConnect, penDisconnect, setLogRows, setTheme, toggleSession, updateConnectionsPage, watchCmd } from './live.js';
import { filterSessions, loadSessions, selectSession } from './sessions.js';

const pageMeta = {
  recording:   { title: 'Live Recording',   sub: 'Pen + Watch data capture' },
  sessions:    { title: 'Session History',  sub: 'All recorded sessions' },
  connections: { title: 'Connections',      sub: 'Device & server management' },
  system:      { title: 'System & Schema',  sub: 'Data structure · API reference · Project info' },
};

function setupNavigation() {
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
}

function exposeInlineHandlers() {
  Object.assign(window, {
    clearVisualLogs,
    filterSessions,
    loadSessions,
    penConnect,
    penDisconnect,
    selectSession,
    setLogRows,
    setTheme,
    toggleSession,
    watchCmd,
  });
}

function init() {
  exposeInlineHandlers();
  setupNavigation();
  document.getElementById('timer').textContent = '00:00:00';
  setTheme(S.theme);
  setLogRows(S.logRows);
  api('/status').then(s => { if (s) handleStatus({ type: 'status', ...s, chart: [] }); });
  connectWs({ handleStatus, loadSessions });
}

init();
