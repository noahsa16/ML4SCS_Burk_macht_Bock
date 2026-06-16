// Web-Training-Cockpit — Page-Modul (mount/onStatus/onShow/onHide).
// Rendert den Live-Lauf aus dem `training`-Block des WS-Status-Ticks.
import { api } from '/static/js/core/api.js';

let root = null;
let _runId = null;
let _viewingIdle = true;     // true → onStatus lässt den idle-Screen stehen
let _detailLoadedFor = null; // run_id, für den die Done-Analyse schon geholt wurde

export function mount(container) {
  root = container;
  _loadModels();
  _loadRuns();
  _q('#trn-start').addEventListener('click', _start);
  _q('#trn-stop').addEventListener('click', () => api('/training/stop', 'POST'));
  _q('#trn-again').addEventListener('click', _again);
  _q('#trn-promote').addEventListener('click', () => _runId && api(`/training/runs/${_runId}/promote`, 'POST'));
  _q('#trn-sandbox').addEventListener('click', () => _runId && api(`/training/runs/${_runId}/sandbox`, 'POST'));
  _setState('idle');
}

export function onShow() { _loadRuns(); }
export function onHide() {}

function _q(sel) { return root.querySelector(sel); }

async function _loadModels() {
  const models = await api('/training/models');
  if (!Array.isArray(models)) return;
  const sel = _q('#trn-model');
  sel.innerHTML = '';
  for (const m of models) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = `${m.label} (${m.speed})`;
    o.title = m.description || '';
    sel.appendChild(o);
  }
  const cur = models.find(m => m.id === sel.value) || models[0];
  if (cur) _q('#trn-model-q').title = cur.description || '';
}

async function _loadRuns() {
  const runs = await api('/training/runs');
  const t = _q('#trn-runs');
  if (!t) return;
  if (!Array.isArray(runs) || runs.length === 0) {
    t.innerHTML = '<tr><td class="trn-muted">Noch keine Läufe.</td></tr>';
    return;
  }
  t.innerHTML = '<tr style="color:var(--text3);text-align:left">'
    + '<th>Run</th><th>Modell</th><th>Pool</th><th>acc</th><th></th></tr>';
  for (const r of runs) {
    const tr = document.createElement('tr');
    const acc = (r.mean_acc != null) ? Number(r.mean_acc).toFixed(3) : '–';
    for (const txt of [r.run_id, r.model, r.pool, acc]) {
      const td = document.createElement('td');
      td.style.padding = '6px 8px';
      td.style.borderBottom = '1px solid var(--border)';
      td.textContent = txt;
      tr.appendChild(td);
    }
    const td = document.createElement('td');
    td.style.padding = '6px 8px';
    const btn = document.createElement('button');
    btn.className = 'trn-ghost';
    btn.textContent = 'als Headline';
    btn.addEventListener('click', () => api(`/training/runs/${r.run_id}/promote`, 'POST'));
    td.appendChild(btn);
    tr.appendChild(td);
    t.appendChild(tr);
  }
}

async function _start() {
  const body = {
    model: _q('#trn-model').value,
    pool: _q('#trn-pool').value,
    by: _q('#trn-by').value,
  };
  const res = await api('/training/start', 'POST', body);
  if (res && res.run_id) {
    _runId = res.run_id;
    _viewingIdle = false;
    _detailLoadedFor = null;
    _setState('running');
  }
}

function _again() {
  _viewingIdle = true;
  _setState('idle');
  _loadRuns();
}

function _setState(phase) {
  for (const s of root.querySelectorAll('.trn-state')) {
    const owns = (s.dataset.state || '').split(' ').includes(phase);
    s.hidden = !owns;
  }
}

export function onStatus(payload) {
  const t = payload && payload.training;
  if (!t) return;
  if (t.phase === 'running') _viewingIdle = false;
  if (_viewingIdle && t.phase !== 'running') return;  // idle-Screen stehen lassen
  if (t.phase === 'idle') return;

  _runId = t.run_id || _runId;
  const done = t.phase === 'done';
  _setState(done ? 'done' : 'running');

  _q('#trn-title').textContent = `${t.model || 'rf'} · ${t.pool || ''}`;
  const statusPill = _q('#trn-status');
  statusPill.classList.toggle('running', !done);
  _q('#trn-status-text').textContent = done
    ? (t.partial ? `partial ${t.summary?.n_done ?? '?'}/${t.n}` : 'fertig')
    : `läuft · Fold ${t.fold}/${t.n}`;
  _q('#trn-folds').textContent = `${t.fold} / ${t.n}`;

  const s = t.summary || {};
  const mean = (arr, key) => arr.length ? arr.reduce((a, f) => a + (f[key] || 0), 0) / arr.length : null;
  _num('#trn-acc', done ? s.mean_acc : mean(t.folds, 'acc'));
  _num('#trn-auc', done ? s.auc : mean(t.folds, 'auc'));
  _num('#trn-f1', done ? s.f1 : mean(t.folds, 'f1'));

  _renderGrid(t);
  _renderConfusion(t.confusion || {});
  _renderConvergence(t.folds || [], t.n || 1);
  _q('#trn-hw').textContent = t.hw
    ? `CPU ${Math.round(t.hw.cpu_pct)}% · RAM ${Number(t.hw.ram_gb).toFixed(1)} GB` : '';
  _q('#trn-foldnow').textContent = done ? '—' : `Fold ${t.fold} / ${t.n}`;
  const last = (t.log || [])[t.log.length - 1];
  if (last) _q('#trn-log').innerHTML = `<span class="s">/</span> ${last}`;

  // Buttons
  _q('#trn-stop').hidden = done;
  _q('#trn-again').hidden = !done;
  _q('#trn-promote').hidden = !done;
  _q('#trn-sandbox').hidden = !done;
  _q('#trn-analysis').hidden = !done;

  if (done) _renderDone(t);
}

function _num(sel, v) { _q(sel).textContent = (v == null || Number.isNaN(v)) ? '—' : Number(v).toFixed(3); }

function _renderGrid(t) {
  const g = _q('#trn-grid');
  g.innerHTML = '';
  const folds = t.folds || [];
  const n = t.n || folds.length;
  for (const f of folds) {
    const cls = f.acc >= 0.87 ? 'good' : 'warn';
    g.appendChild(_tile(cls, f.person, Number(f.acc).toFixed(3), () => _openDrawer(f)));
  }
  if (t.phase !== 'done' && folds.length < n) {
    g.appendChild(_tile('live', `Fold ${t.fold}`, '…'));
    for (let i = folds.length + 1; i < n; i++) g.appendChild(_tile('pend', '·', '·'));
  }
}

function _tile(cls, who, v, onClick) {
  const d = document.createElement('div');
  d.className = `trn-tile ${cls}`;
  d.innerHTML = `<div class="who">${who}</div><div class="v">${v}</div>`;
  if (onClick) d.addEventListener('click', onClick);
  return d;
}

function _renderConfusion(c) {
  _q('#trn-confusion').innerHTML =
    `<div></div><div>pred 0</div><div>pred 1</div>`
    + `<div>true 0</div><div class="trn-cell diag">${c.tn ?? 0}</div><div class="trn-cell off">${c.fp ?? 0}</div>`
    + `<div>true 1</div><div class="trn-cell off">${c.fn ?? 0}</div><div class="trn-cell diag">${c.tp ?? 0}</div>`;
}

function _renderConvergence(folds, n) {
  const svg = _q('#trn-conv');
  if (!folds.length) { svg.innerHTML = ''; return; }
  const W = 480, H = 170, pad = 28;
  const xy = (i, auc) => {
    const x = pad + (n <= 1 ? 0 : (i / (n - 1)) * (W - 2 * pad));
    const y = H - pad - Math.max(0, Math.min(1, (auc - 0.5) / 0.5)) * (H - 2 * pad);
    return [x, y];
  };
  const pts = folds.map((f, i) => xy(i, f.auc || 0.5).join(',')).join(' ');
  const dots = folds.map((f, i) => {
    const [x, y] = xy(i, f.auc || 0.5);
    const col = f.acc >= 0.87 ? 'var(--green)' : 'var(--yellow)';
    return `<circle cx="${x}" cy="${y}" r="3.5" fill="${col}"/>`;
  }).join('');
  svg.innerHTML =
    `<line x1="${pad}" y1="10" x2="${pad}" y2="${H - pad}" stroke="var(--border)"/>`
    + `<line x1="${pad}" y1="${H - pad}" x2="${W - 8}" y2="${H - pad}" stroke="var(--border)"/>`
    + `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>${dots}`;
}

function _renderBurst(burst) {
  const svg = _q('#trn-burst');
  if (!svg || !burst) return;
  const scales = ['5s', '10s', '30s'].filter(k => burst[k] != null);
  if (!scales.length) { svg.innerHTML = ''; return; }
  const series = [['1s', null], ...scales.map(k => [k, burst[k]])];
  const W = 160, H = 130, pad = 22;
  const pts = series.map(([, v], i) => {
    if (v == null) return null;
    const x = pad + (i / (series.length - 1)) * (W - 2 * pad);
    const y = H - pad - Math.max(0, Math.min(1, (v - 0.5) / 0.5)) * (H - 2 * pad);
    return `${x},${y}`;
  }).filter(Boolean).join(' ');
  svg.innerHTML =
    `<line x1="${pad}" y1="8" x2="${pad}" y2="${H - pad}" stroke="var(--border)"/>`
    + `<line x1="${pad}" y1="${H - pad}" x2="${W - 6}" y2="${H - pad}" stroke="var(--border)"/>`
    + `<polyline points="${pts}" fill="none" stroke="var(--green)" stroke-width="2.5"/>`;
}

function _renderDone(t) {
  const v = _q('#trn-verdict');
  v.hidden = false;
  _q('#trn-verdict-title').textContent = t.partial ? 'Lauf gestoppt (partial)' : 'Lauf abgeschlossen';
  _q('#trn-verdict-sub').textContent = `${t.summary?.n_done ?? t.folds.length}/${t.n} Folds`;
  _q('#trn-verdict-acc').textContent = (t.summary?.mean_acc != null)
    ? Number(t.summary.mean_acc).toFixed(3) : '—';
  _renderBurst(t.summary?.burst);
  if (_runId && _detailLoadedFor !== _runId) {
    _detailLoadedFor = _runId;
    _loadDetail(_runId);
  }
}

// ROC + Feature-Gruppen aus dem Run-Detail-Endpoint (wird in Task 13 geliefert).
// Graceful: fehlt der Endpoint noch, bleibt die Sektion leer.
async function _loadDetail(runId) {
  const d = await api(`/training/runs/${runId}`);
  if (!d || d.http_status || !d.feature_groups) return;
  const feat = _q('#trn-feat');
  const max = Math.max(...d.feature_groups.map(g => g.imp), 1e-9);
  feat.innerHTML = d.feature_groups.map(g =>
    `<div class="trn-bar">${g.group}<i style="width:${Math.round(g.imp / max * 100)}%;background:var(--accent)"></i></div>`
  ).join('');
  if (d.roc) _renderRoc(d.roc);
}

function _renderRoc(roc) {
  const svg = _q('#trn-roc');
  if (!svg || !Array.isArray(roc)) return;
  const W = 160, H = 130, pad = 18;
  const pts = roc.map(([fpr, tpr]) =>
    `${pad + fpr * (W - 2 * pad)},${H - pad - tpr * (H - 2 * pad)}`).join(' ');
  svg.innerHTML =
    `<line x1="${pad}" y1="${H - pad}" x2="${W - 6}" y2="${H - pad}" stroke="var(--border)"/>`
    + `<line x1="${pad}" y1="8" x2="${pad}" y2="${H - pad}" stroke="var(--border)"/>`
    + `<line x1="${pad}" y1="${H - pad}" x2="${W - 6}" y2="8" stroke="var(--border)" stroke-dasharray="3 3"/>`
    + `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>`;
}

function _openDrawer(fold) {
  const d = _q('#trn-drawer');
  d.hidden = false;
  d.innerHTML = `<button class="trn-ghost" id="trn-drawer-x">schließen</button>
    <h2>${fold.person}</h2>
    <div class="trn-dkpi">
      <div><b>${Number(fold.acc).toFixed(3)}</b><small>accuracy</small></div>
      <div><b>${Number(fold.auc).toFixed(3)}</b><small>ROC-AUC</small></div>
      <div><b>${Number(fold.f1 || 0).toFixed(3)}</b><small>F1</small></div>
    </div>
    <p class="trn-muted">Per-Task-Aufschlüsselung aus Markern: folgt (post-MVP).</p>`;
  d.querySelector('#trn-drawer-x').addEventListener('click', () => { d.hidden = true; });
}
