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
  _enhanceSelect(_q('#trn-pool'));
  _enhanceSelect(_q('#trn-by'));
  _enhanceSelect(_q('#trn-window'));
  _enhanceSelect(_q('#trn-gap'));
  _wireBurstChips();
  root.addEventListener('change', _updatePreview);  // Why: select/toggle bubbeln 'change'
  document.addEventListener('click', _onDocClick);
  document.addEventListener('keydown', _onDocKey);
  _updatePreview();
  _q('#trn-start').addEventListener('click', _start);
  _q('#trn-stop').addEventListener('click', () => api('/training/stop', 'POST'));
  _q('#trn-again').addEventListener('click', _again);
  _q('#trn-promote').addEventListener('click', () => _runId && api(`/training/runs/${_runId}/promote`, 'POST'));
  _q('#trn-sandbox').addEventListener('click', () => _runId && api(`/training/runs/${_runId}/sandbox`, 'POST'));
  _q('#trn-analysis').addEventListener('click', (e) => {
    const card = e.target.closest('.trn-drill');
    if (card) _openInfoDrawer(card.dataset.drill);
  });
  _setState('idle');
}

export function onShow() { _loadRuns(); }
export function onHide() { _closeAllDropdowns(); }

function _q(sel) { return root.querySelector(sel); }

// ── Custom dropdown: schöne Liste über dem versteckten nativen <select>. ──
// Das <select> bleibt die Wahrheit (Wert, change-Event, Tooltip-Sync); das
// Panel spiegelt nur dessen Optionen (inkl. optgroup-Header + disabled).
function _enhanceSelect(sel) {
  if (!sel || sel.dataset.enhanced) return;
  sel.dataset.enhanced = '1';

  const dd = document.createElement('div');
  dd.className = 'trn-dd';
  sel.parentNode.insertBefore(dd, sel);
  dd.appendChild(sel);
  sel.classList.add('trn-dd-native');
  sel.setAttribute('aria-hidden', 'true');
  sel.tabIndex = -1;

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'trn-dd-trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.innerHTML = '<span class="trn-dd-value"></span>'
    + '<svg class="trn-dd-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    + 'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  dd.appendChild(trigger);

  const panel = document.createElement('div');
  panel.className = 'trn-dd-panel';
  panel.setAttribute('role', 'listbox');
  panel.hidden = true;
  panel.innerHTML = '<span class="trn-dd-nub"></span>';
  dd.appendChild(panel);

  const valEl = trigger.querySelector('.trn-dd-value');
  const syncValue = () => {
    const opt = sel.selectedOptions[0];
    valEl.textContent = opt ? opt.textContent : '—';
  };
  const mkOpt = (o) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'trn-dd-opt';
    b.setAttribute('role', 'option');
    b.textContent = o.textContent;
    if (o.title) b.title = o.title;
    b.disabled = o.disabled;
    b.setAttribute('aria-selected', String(o.selected));
    if (!o.disabled) b.addEventListener('click', () => {
      sel.value = o.value;
      sel.dispatchEvent(new Event('change'));
      _closeAllDropdowns();
    });
    return b;
  };
  const buildPanel = () => {
    panel.querySelectorAll('.trn-dd-group, .trn-dd-opt').forEach(n => n.remove());
    for (const child of sel.children) {
      if (child.tagName === 'OPTGROUP') {
        const h = document.createElement('div');
        h.className = 'trn-dd-group';
        h.textContent = child.label;
        panel.appendChild(h);
        for (const o of child.children) panel.appendChild(mkOpt(o));
      } else if (child.tagName === 'OPTION') {
        panel.appendChild(mkOpt(child));
      }
    }
  };
  dd._close = () => {
    panel.hidden = true; dd.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
  };
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (dd.classList.contains('open')) { dd._close(); return; }
    _closeAllDropdowns();
    buildPanel();
    panel.hidden = false; dd.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
  });

  sel.addEventListener('change', syncValue);
  syncValue();
}

function _closeAllDropdowns() {
  if (!root) return;
  root.querySelectorAll('.trn-dd.open').forEach(d => d._close && d._close());
}
function _onDocClick(e) {
  if (root && !e.target.closest('.trn-dd')) _closeAllDropdowns();
}
function _onDocKey(e) { if (e.key === 'Escape') _closeAllDropdowns(); }

function _wireBurstChips() {
  const chips = _q('#trn-burst-chips');
  if (!chips) return;
  for (const chip of chips.querySelectorAll('.trn-chip[data-scale]')) {
    const toggle = () => {
      const on = chip.classList.toggle('on');
      chip.setAttribute('aria-pressed', String(on));
      _updatePreview();
    };
    chip.addEventListener('click', toggle);
    chip.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  }
}
function _burstScales() {
  const chips = _q('#trn-burst-chips');
  if (!chips) return null;
  return [...chips.querySelectorAll('.trn-chip[data-scale].on')]
    .map(c => c.dataset.scale).join(',');
}

function _setText(sel, v) { const e = _q(sel); if (e) e.textContent = v; }

// Live-Vorschau rechts: spiegelt die aktuelle Auswahl in Prosa.
function _updatePreview() {
  if (!root || !_q('#trn-preview')) return;
  const model = _q('#trn-model'), pool = _q('#trn-pool'), by = _q('#trn-by');
  const modelTxt = (model && model.selectedOptions[0])
    ? model.selectedOptions[0].textContent.split(' · ')[0] : '—';
  _setText('#trn-pv-model', modelTxt);
  _setText('#trn-pv-pool', (pool && pool.selectedOptions[0])
    ? pool.selectedOptions[0].textContent : '—');
  _setText('#trn-pv-axis', (by && by.selectedOptions[0])
    ? `LOSO ${by.selectedOptions[0].textContent}` : '—');
  _setText('#trn-pv-z', (_q('#trn-zscore') && _q('#trn-zscore').checked) ? 'an' : 'aus');
  const win = _q('#trn-window') ? parseFloat(_q('#trn-window').value) : 1;
  _setText('#trn-pv-window', `${win} s · stride ${win / 2} s`);
  const gap = _q('#trn-gap') ? _q('#trn-gap').value : '2500';
  _setText('#trn-pv-gap', `${gap} ms`);
  const scales = _burstScales();
  _setText('#trn-pv-burst', scales ? `1s + ${scales.split(',').join('·')} s` : 'nur 1s');
  // Folds nur ableitbar, wenn die Pool-Größe im Label steht und by=person.
  const m = pool && pool.selectedOptions[0]
    ? pool.selectedOptions[0].textContent.match(/N=(\d+)/) : null;
  _setText('#trn-pv-est', (m && by && by.value === 'person')
    ? `≈ wenige Minuten · ${m[1]} Folds` : 'LOSO-Lauf');
}

const _FAMILY_LABEL = {
  classical: 'Klassisch · 88/92 Features',
  deep: 'Deep-Sequenz · rohe IMU',
  foundation: 'Foundation · harnet',
};

async function _loadModels() {
  const models = await api('/training/models');
  if (!Array.isArray(models)) return;
  const sel = _q('#trn-model');
  sel.innerHTML = '';
  const byFam = {};
  for (const m of models) (byFam[m.family] ||= []).push(m);
  for (const fam of ['classical', 'deep', 'foundation']) {
    if (!byFam[fam]) continue;
    const og = document.createElement('optgroup');
    og.label = _FAMILY_LABEL[fam] || fam;
    for (const m of byFam[fam]) {
      const o = document.createElement('option');
      o.value = m.id;
      o.textContent = m.enabled
        ? `${m.label} · ${m.speed}`
        : `${m.label} · ${m.speed} (bald)`;
      o.disabled = !m.enabled;
      o.title = m.description || '';
      o.dataset.desc = m.description || '';
      og.appendChild(o);
    }
    sel.appendChild(og);
  }
  const firstEnabled = models.find(m => m.enabled);
  if (firstEnabled) sel.value = firstEnabled.id;
  _syncModelTooltip();
  sel.addEventListener('change', _syncModelTooltip);
  _enhanceSelect(sel);  // Why: nach dem Befüllen, damit das Panel die Optgroups spiegelt.
  _updatePreview();
}

function _syncModelTooltip() {
  const opt = _q('#trn-model').selectedOptions[0];
  const q = _q('#trn-model-q');
  const desc = opt ? (opt.dataset.desc || '') : '';
  if (desc) q.setAttribute('data-tip', desc);
  else q.removeAttribute('data-tip');  // Why: leeres data-tip würde eine leere Tooltip-Box zeigen.
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
    zscore: _q('#trn-zscore') ? _q('#trn-zscore').checked : true,
    burst_scales: _burstScales(),
    window_sec: _q('#trn-window') ? parseFloat(_q('#trn-window').value) : null,
    max_gap_ms: _q('#trn-gap') ? parseFloat(_q('#trn-gap').value) : null,
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
  _renderLeaderboard();
  _renderTasks();
  if (_runId && _detailLoadedFor !== _runId) {
    _detailLoadedFor = _runId;
    _loadDetail(_runId);
  }
}

async function _renderLeaderboard() {
  const el = _q('#trn-leaderboard');
  if (!el) return;
  const runs = await api('/training/runs');
  if (!Array.isArray(runs)) return;
  const sorted = runs.filter(r => r.mean_acc != null)
    .sort((a, b) => b.mean_acc - a.mean_acc).slice(0, 6);
  if (!sorted.length) { el.innerHTML = '<div class="trn-muted">noch keine Läufe</div>'; return; }
  el.innerHTML = sorted.map(r =>
    `<div class="trn-bar">${r.model} · ${r.pool}`
    + `<i style="width:${Math.round(Number(r.mean_acc) * 100)}%;background:var(--accent)"></i>`
    + `${Number(r.mean_acc).toFixed(3)}</div>`).join('');
}

const _DRILL = {
  roc: ['ROC-Kurve', 'Trade-off True-Positive- vs. False-Positive-Rate über alle Schwellen; '
    + 'AUC = Fläche darunter (1.0 perfekt, 0.5 Zufall). Gepoolt über alle OOF-Vorhersagen.'],
  feat: ['Feature-Gruppen-Importance', 'Summe der RF-Feature-Importances je semantischer Gruppe '
    + '(spectral, jerk, time-stats, magnitude, correlation, zcr, ggf. gravity) — worauf das Modell schaut.'],
  burst: ['Burst-Skalen', 'Accuracy über kausale Decision-Windows 1→30 s. Höhere Skala = mehr Glättung, '
    + 'gröbere Zeitauflösung — die User-facing-Metrik für Schreibzeit-Tracking.'],
  leaderboard: ['Modell-Leaderboard', 'Alle Läufe aus models/runs/, sortiert nach mean accuracy. '
    + '„Als Headline speichern" promotet einen Lauf zu den kanonischen Artefakten (rf_all.joblib / loso_cv.csv).'],
};

function _openInfoDrawer(kind) {
  const [title, note] = _DRILL[kind] || [kind, ''];
  const d = _q('#trn-drawer');
  d.hidden = false;
  d.innerHTML = `<button class="trn-ghost" id="trn-drawer-x">schließen</button>`
    + `<h2>${title}</h2><p class="trn-muted">${note}</p>`;
  d.querySelector('#trn-drawer-x').addEventListener('click', () => { d.hidden = true; });
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

async function _renderTasks() {
  const el = _q('#trn-tasks');
  if (!el || !_runId) return;
  const r = await api(`/training/runs/${_runId}/tasks`);
  const tasks = r && r.tasks;
  if (!Array.isArray(tasks) || !tasks.length) {
    el.innerHTML = '<div class="trn-muted">keine Marker-Daten</div>'; return;
  }
  const maxErr = Math.max(...tasks.map(t => t.fp + t.fn), 1);
  el.innerHTML = tasks.slice(0, 6).map(t => {
    const col = t.category === 'writing' ? 'var(--accent)' : 'var(--yellow)';
    return `<div class="trn-bar">${t.task}`
      + `<i style="width:${Math.round((t.fp + t.fn) / maxErr * 100)}%;background:${col}"></i>`
      + `${t.fp}FP/${t.fn}FN</div>`;
  }).join('');
}

async function _openDrawer(fold) {
  const d = _q('#trn-drawer');
  d.hidden = false;
  d.innerHTML = `<button class="trn-ghost" id="trn-drawer-x">schließen</button>
    <h2>${fold.person}</h2>
    <div class="trn-dkpi">
      <div><b>${Number(fold.acc).toFixed(3)}</b><small>accuracy</small></div>
      <div><b>${Number(fold.auc).toFixed(3)}</b><small>ROC-AUC</small></div>
      <div><b>${Number(fold.f1 || 0).toFixed(3)}</b><small>F1</small></div>
    </div>
    <div class="trn-label">Genauigkeit pro Task (aus Markern)</div>
    <div id="trn-drawer-tasks" class="trn-muted">lädt…</div>`;
  d.querySelector('#trn-drawer-x').addEventListener('click', () => { d.hidden = true; });
  if (!_runId) return;
  const r = await api(`/training/runs/${_runId}/tasks?person=${encodeURIComponent(fold.person)}`);
  const box = d.querySelector('#trn-drawer-tasks');
  if (!box) return;  // Drawer zwischenzeitlich geschlossen
  const tasks = (r && r.tasks) || [];
  if (!tasks.length) { box.textContent = 'keine Marker-Daten für diese Session.'; return; }
  box.classList.remove('trn-muted');
  box.innerHTML = tasks.map(t =>
    `<div class="trn-bar">${t.task}`
    + `<i style="width:${Math.round(t.acc * 100)}%;background:${t.acc >= 0.85 ? 'var(--green)' : 'var(--yellow)'}"></i>`
    + `${Number(t.acc).toFixed(3)}</div>`).join('');
}
