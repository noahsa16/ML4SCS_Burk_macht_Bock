// Web-Training-Cockpit — Page-Modul (mount/onStatus/onShow/onHide).
// Rendert den Live-Lauf aus dem `training`-Block des WS-Status-Ticks.
import { api } from '/static/js/core/api.js';
import { toast } from '/static/js/core/toast.js';
import { createSeparationLoader } from '/static/js/pages/training_loader.js';

let root = null;
let _runId = null;
let _poolN = {};  // pool-id -> {n_subjects, n_sessions} aus /training/pools
let _modelFamily = {};  // model-id -> family (classical|deep|foundation)
let _est = {};  // "model|pool" -> {per_fold_sec, n_runs} aus /training/estimate
let _loader = null;  // Lade-Animation (nur während eines laufenden Runs aktiv)
let _viewingIdle = true;     // true → onStatus lässt den idle-Screen stehen
let _detailLoadedFor = null; // run_id, für den die Done-Analyse schon geholt wurde

// Deep-Sequenz-Modelle sind eval-only (kein sklearn-Joblib für die Live-
// Inferenz) → Promote/Sandbox gesperrt.
function _isDeep(model) { return _modelFamily[model] === 'deep'; }

export function mount(container) {
  root = container;
  _loader = createSeparationLoader(_q('#trn-loader'));
  _loadModels();
  _loadRuns();
  _loadPools();  // fetch N je Pool, dann Pool-Dropdown enhancen (Labels mit N)
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
  _q('#trn-promote').addEventListener('click', () => _runId && _promoteRun(_runId));
  _q('#trn-sandbox').addEventListener('click', () => _runId && api(`/training/runs/${_runId}/sandbox`, 'POST'));
  _q('#trn-analysis').addEventListener('click', (e) => {
    const card = e.target.closest('.trn-drill');
    if (card) _openInfoDrawer(card.dataset.drill);
  });
  _setState('idle');
}

export function onShow() { _loadRuns(); }
export function onHide() { _closeAllDropdowns(); if (_loader) _loader.stop(); }

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
      // Why: bubbles:true, sonst erreicht das change-Event den root-Listener
      // (_updatePreview) nicht — die Live-Vorschau bliebe stehen.
      sel.dispatchEvent(new Event('change', { bubbles: true }));
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

// Sekunden → menschenlesbare Dauer ("45 s" · "3 min" · "1 h 10 min").
function _humanDur(sec) {
  if (sec < 90) return `${Math.max(1, Math.round(sec))} s`;
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

// Holt die Dauer-Schätzung für die aktuelle Modell/Pool-Wahl (gecacht pro
// Kombination) und rendert die Vorschau neu. Kein Treffer im Cache → ein Fetch,
// dann Re-Render; in-flight wird mit null markiert (kein Doppel-Fetch).
async function _refreshEstimate() {
  const model = _q('#trn-model'), pool = _q('#trn-pool');
  if (!model || !pool || !model.value || !pool.value) return;
  const key = `${model.value}|${pool.value}`;
  if (key in _est) { _updatePreview(); return; }
  _est[key] = null;
  try {
    const e = await api(`/training/estimate?model=${encodeURIComponent(model.value)}`
      + `&pool=${encodeURIComponent(pool.value)}`);
    _est[key] = (e && typeof e.per_fold_sec !== 'undefined')
      ? e : { per_fold_sec: null, n_runs: 0 };
  } catch { _est[key] = { per_fold_sec: null, n_runs: 0 }; }
  _updatePreview();
}

// Live-Vorschau rechts: spiegelt die aktuelle Auswahl in Prosa.
function _updatePreview() {
  if (!root || !_q('#trn-preview')) return;
  const model = _q('#trn-model'), pool = _q('#trn-pool'), by = _q('#trn-by');
  const deep = model && _isDeep(model.value);
  const modelTxt = (model && model.selectedOptions[0])
    ? model.selectedOptions[0].textContent.split(' · ')[0] : '—';
  _setText('#trn-pv-model', modelTxt);
  _setText('#trn-pv-pool', (pool && pool.selectedOptions[0])
    ? pool.selectedOptions[0].textContent : '—');
  // Deep läuft fix: person-LOSO, 1-s-Input, feste 5/10/30-Burst — die Vorschau
  // zeigt das statt der (gesperrten) Regler-Werte.
  _setText('#trn-pv-axis', deep ? 'LOSO person · raw-Sequenz'
    : ((by && by.selectedOptions[0]) ? `LOSO ${by.selectedOptions[0].textContent}` : '—'));
  _setText('#trn-pv-z', (_q('#trn-zscore') && _q('#trn-zscore').checked) ? 'an' : 'aus');
  const win = _q('#trn-window') ? parseFloat(_q('#trn-window').value) : 1;
  _setText('#trn-pv-window', deep ? '1 s · raw-Sequenz (fix)' : `${win} s · stride ${win / 2} s`);
  const gap = _q('#trn-gap') ? _q('#trn-gap').value : '2500';
  _setText('#trn-pv-gap', `${gap} ms`);
  const scales = _burstScales();
  _setText('#trn-pv-burst', deep ? '5·10·30 s (fix)'
    : (scales ? `1s + ${scales.split(',').join('·')} s` : 'nur 1s'));
  // Probanden (N) + Fold-Zahl aus /training/pools — immer gezeigt, datengetrieben.
  const counts = pool && pool.value ? _poolN[pool.value] : null;
  _setText('#trn-pv-subjects', counts ? `N=${counts.n_subjects}` : '—');
  const folds = counts
    ? (by && by.value === 'session' ? counts.n_sessions : counts.n_subjects)
    : null;
  // Datengetriebene Dauer aus vergangenen Läufen (per_fold_sec × Folds).
  // Keine Historie → nur die Fold-Zahl, keine erfundene Zeit.
  const key = (model && pool && model.value && pool.value)
    ? `${model.value}|${pool.value}` : null;
  const est = key ? _est[key] : null;
  let estText;
  if (!folds) estText = 'LOSO-Lauf';
  else if (est && est.per_fold_sec != null)
    estText = `≈ ${_humanDur(est.per_fold_sec * folds)} · ${folds} Folds`;
  else estText = `${folds} Folds`;
  _setText('#trn-pv-est', estText);
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
      _modelFamily[m.id] = m.family;
      const o = document.createElement('option');
      o.value = m.id;
      // Kein hartkodiertes fast/slow mehr — die Familie steht im Optgroup-Header,
      // die echte gemessene Dauer in der Vorschau. "(bald)" = nicht verdrahtet.
      o.textContent = m.enabled ? m.label : `${m.label} (bald)`;
      o.disabled = !m.enabled;
      o.title = m.description || '';
      o.dataset.desc = m.description || '';
      o.dataset.family = m.family;
      og.appendChild(o);
    }
    sel.appendChild(og);
  }
  const firstEnabled = models.find(m => m.enabled);
  if (firstEnabled) sel.value = firstEnabled.id;
  _syncModelTooltip();
  sel.addEventListener('change', _syncModelTooltip);
  sel.addEventListener('change', _applyDeepMode);
  sel.addEventListener('change', _refreshEstimate);  // Modellwechsel → neue Dauer-Schätzung
  _enhanceSelect(sel);  // Why: nach dem Befüllen, damit das Panel die Optgroups spiegelt.
  _applyDeepMode();     // setzt Deep-Look + sperrt nicht zutreffende Regler (ruft _updatePreview)
  _refreshEstimate();   // initiale Schätzung für die Default-Wahl
  _loadRuns();          // Familien bekannt → Deep-Runs grauen ihren Promote-Button korrekt aus
}

// Deep-Modus: nicht zutreffende Regler dimmen/sperren (rein funktional, keine
// Optik). Deep-Sequenz-Modelle laufen fix person-LOSO, 1-s-Input, 5/10/30-Burst
// und ohne Per-Session-Z-Score (BatchNorm übernimmt) — die zugehörigen Regler
// gelten nicht und werden gesperrt, statt still ignoriert zu werden.
function _applyDeepMode() {
  const sel = _q('#trn-model');
  const deep = sel ? _isDeep(sel.value) : false;
  const z = _q('#trn-zscore');
  if (deep && z) z.checked = false;  // Deep-Default: kein Z-Score
  for (const id of ['#trn-window', '#trn-by', '#trn-burst-chips']) {
    const el = _q(id);
    const label = el && el.closest('label');
    if (label) label.classList.toggle('trn-ctl-off', deep);
  }
  _updatePreview();
}

function _syncModelTooltip() {
  const opt = _q('#trn-model').selectedOptions[0];
  const q = _q('#trn-model-q');
  const desc = opt ? (opt.dataset.desc || '') : '';
  if (desc) q.setAttribute('data-tip', desc);
  else q.removeAttribute('data-tip');  // Why: leeres data-tip würde eine leere Tooltip-Box zeigen.
}

async function _loadPools() {
  const sel = _q('#trn-pool');
  try {
    const pools = await api('/training/pools');
    if (Array.isArray(pools)) {
      // Why: N nur in der Probanden-Zeile der Vorschau führen, nicht (hardcoded
      // oder injiziert) im Pool-Label — eine Quelle für die Probandenzahl.
      for (const p of pools) {
        _poolN[p.id] = { n_subjects: p.n_subjects, n_sessions: p.n_sessions };
      }
    }
  } catch { /* offline → Probanden-Zeile bleibt "—" */ }
  sel.addEventListener('change', _refreshEstimate);  // Poolwechsel → neue Dauer-Schätzung
  _enhanceSelect(sel);  // nach dem Label-Update, damit das Panel N zeigt
  _refreshEstimate();   // ruft _updatePreview, wenn die Schätzung da ist
}

async function _loadRuns() {
  const tbody = _q('#trn-runs-body');
  if (!tbody) return;
  const runs = await api('/training/runs');
  if (!Array.isArray(runs) || runs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="trn-runs-empty">Noch keine Läufe.</td></tr>';
    return;
  }
  const fmt = (v) => (v != null) ? Number(v).toFixed(3) : '–';
  tbody.innerHTML = '';
  for (const r of runs) {
    const tr = document.createElement('tr');
    // Why: ganze Zeile öffnet die Insights; die Action-Buttons stoppen
    // die Propagation, damit Promote/Delete nicht zusätzlich den Drawer öffnen.
    tr.className = 'trn-runs-row';
    tr.tabIndex = 0;
    tr.setAttribute('role', 'button');
    const when = _runWhen(r.run_id);
    tr.addEventListener('click', () => _openRunDrawer(r));
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _openRunDrawer(r); }
    });
    const cells = [
      [when, 'mono'], [r.model || '–', ''], [r.pool || '–', ''],
      [fmt(r.mean_acc), 'mono'], [fmt(r.mean_auc), 'mono'],
      [(r.n_folds != null ? String(r.n_folds) : '–'), 'mono'],
      [(r.total_sec != null ? _humanDur(r.total_sec) : '–'), 'mono'],
    ];
    for (const [txt, cls] of cells) {
      const td = document.createElement('td');
      if (cls) td.className = cls;
      td.textContent = txt;
      tr.appendChild(td);
    }
    const td = document.createElement('td');
    td.className = 'trn-runs-action';
    const promote = document.createElement('button');
    promote.type = 'button';
    promote.className = 'trn-ghost';
    promote.textContent = 'als Headline';
    if (_isDeep(r.model)) { promote.disabled = true; promote.title = 'eval-only — nicht promotebar'; }
    promote.addEventListener('click', (e) => { e.stopPropagation(); _promoteRun(r.run_id); });
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'trn-ghost trn-del';
    del.textContent = 'löschen';
    del.addEventListener('click', (e) => { e.stopPropagation(); _confirmDelete(r, when); });
    td.appendChild(promote);
    td.appendChild(del);
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

// run_id = "YYYY-MM-DD_HH-MM_model_pool" → "YYYY-MM-DD · HH:MM"
function _runWhen(runId) {
  const parts = String(runId).split('_');
  return parts.length >= 2 ? `${parts[0]} · ${parts[1].replace('-', ':')}` : runId;
}

async function _promoteRun(runId) {
  const res = await api(`/training/runs/${runId}/promote`, 'POST');
  toast((res && !res.http_status) ? 'Als Headline gespeichert' : 'Promote fehlgeschlagen');
}

function _confirmDelete(run, when, after) {
  // Why: Löschen ist nicht-reversibel — harter Bestätigungs-Gate (analog zur
  // Spill-Verwerfen-Bestätigung auf der iPhone-Seite).
  if (!window.confirm(`Run „${when}" löschen?\nDas Verzeichnis wird endgültig entfernt.`)) return;
  _deleteRun(run.run_id, after);
}

async function _deleteRun(runId, after) {
  const res = await api(`/training/runs/${runId}`, 'DELETE');
  if (res && res.deleted) {
    toast('Run gelöscht');
    if (after) after();
    _loadRuns();
  } else {
    toast('Löschen fehlgeschlagen');
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
  const errored = t.phase === 'error';
  // Jede nicht-laufende Phase ist terminal → das Cockpit settled, statt für
  // immer „läuft" zu zeigen (Fix: error/abgebrochene Läufe blieben hängen).
  const terminal = done || errored;
  _setState(terminal ? 'done' : 'running');

  // Running-Visual: Deep-Läufe zeigen ihre echte Loss-Kurve (sobald das erste
  // Epoch-Event da ist), klassische die ambiente Trennungs-Animation. Bis Epoch-
  // Daten eintreffen, dient der Loader auch beim Deep-Lauf als Platzhalter.
  const hist = t.loss_hist || [];
  const hasEpoch = !terminal && _isDeep(t.model) && t.epoch != null && hist.length > 0;
  const epochEl = _q('#trn-epoch');
  if (epochEl) {
    epochEl.hidden = !hasEpoch;
    if (hasEpoch) {
      _q('#trn-epoch-label').textContent =
        `Epoche ${t.epoch + 1} · loss ${Number(t.epoch_loss).toFixed(3)}`;
      _renderLoss(hist);
    }
  }
  const loaderEl = _q('#trn-loader');
  if (loaderEl && _loader) {
    if (!terminal && !hasEpoch) { loaderEl.hidden = false; _loader.start(); }
    else { _loader.stop(); loaderEl.hidden = true; }
  }

  _q('#trn-title').textContent = `${t.model || 'rf'} · ${t.pool || ''}`;
  const statusPill = _q('#trn-status');
  statusPill.classList.toggle('running', !terminal);
  _q('#trn-status-text').textContent = errored
    ? 'Fehler'
    : done
      ? (t.partial ? `gestoppt · ${t.summary?.n_done ?? t.folds?.length ?? '?'}/${t.n}` : 'fertig')
      : (t.stopping ? 'wird gestoppt…' : `läuft · Fold ${t.fold}/${t.n}`);
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
  _q('#trn-foldnow').textContent = terminal ? '—' : `Fold ${t.fold} / ${t.n}`;
  const last = (t.log || [])[t.log.length - 1];
  if (last) _q('#trn-log').innerHTML = `<span class="s">/</span> ${last}`;

  // Buttons. Stop blendet aus, sobald terminal; während des Stoppens deaktiviert
  // + Label „wird gestoppt…", damit der Klick sofort quittiert wird.
  const stopBtn = _q('#trn-stop');
  stopBtn.hidden = terminal;
  stopBtn.disabled = !!t.stopping && !terminal;
  stopBtn.textContent = (!terminal && t.stopping) ? 'wird gestoppt…' : 'Stop';
  _q('#trn-again').hidden = !terminal;
  _q('#trn-analysis').hidden = !done;
  // Promote/Sandbox laden ein sklearn-Joblib in die Live-Inferenz — nur bei
  // echtem done; für Deep-Runs (eval-only) sichtbar, aber ausgegraut.
  const deepRun = _isDeep(t.model);
  const promote = _q('#trn-promote'), sandbox = _q('#trn-sandbox');
  promote.hidden = !done; sandbox.hidden = !done;
  promote.disabled = deepRun; sandbox.disabled = deepRun;
  promote.title = deepRun ? 'eval-only — Deep-Modelle sind nicht promotebar' : '';
  sandbox.title = deepRun ? 'eval-only — Deep-Modelle laufen nicht im Live-Tracker' : '';

  if (done) _renderDone(t);
  else if (errored) _renderError(t);
}

// Terminal-Fehler (Runner-Crash): Cockpit settled mit Fehlertext statt für
// immer „läuft" zu zeigen. Nutzer-Stops landen dagegen als done(partial).
function _renderError(t) {
  const v = _q('#trn-verdict');
  v.hidden = false;
  _q('#trn-verdict-title').textContent = 'Lauf fehlgeschlagen';
  _q('#trn-verdict-sub').textContent = t.error || 'unbekannter Fehler';
  _q('#trn-verdict-acc').textContent = '—';
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

// Echte Loss-Kurve eines Deep-Folds: fallender Verlauf, vertikal auf min..max
// des Folds skaliert (hoher Loss oben). vector-effect, da das viewBox x-streckt.
function _renderLoss(hist) {
  const svg = _q('#trn-loss');
  if (!svg || !hist.length) return;
  const W = 160, H = 48, pad = 4, n = hist.length;
  const losses = hist.map(h => h.loss);
  const lo = Math.min(...losses), span = (Math.max(...losses) - lo) || 1;
  let lx = 0, ly = 0;
  const pts = hist.map((h, i) => {
    lx = pad + (n <= 1 ? 0 : (i / (n - 1)) * (W - 2 * pad));
    ly = pad + (1 - (h.loss - lo) / span) * (H - 2 * pad);
    return `${lx},${ly}`;
  }).join(' ');
  svg.innerHTML =
    `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2" `
    + `vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`
    + `<circle cx="${lx}" cy="${ly}" r="2.6" fill="var(--accent)"/>`;
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

function _renderRoc(roc) { _renderRocInto(_q('#trn-roc'), roc); }

function _renderRocInto(svg, roc) {
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

// Run-Insights: ganze Run-Zeile angeklickt → cv (per-Fold), Feature-Gruppen,
// ROC und Fehler-nach-Task in den geteilten #trn-drawer, plus Promote/Delete.
async function _openRunDrawer(run) {
  const d = _q('#trn-drawer');
  d.hidden = false;
  const when = _runWhen(run.run_id);
  const f = (v) => (v != null) ? Number(v).toFixed(3) : '—';
  d.innerHTML = `<button class="trn-ghost" id="trn-drawer-x">schließen</button>
    <h2 id="trn-rd-when"></h2>
    <div class="trn-muted" id="trn-rd-meta"></div>
    <div class="trn-dkpi">
      <div><b>${f(run.mean_acc)}</b><small>accuracy</small></div>
      <div><b>${f(run.mean_auc)}</b><small>ROC-AUC</small></div>
      <div><b>${run.n_folds != null ? run.n_folds : '—'}</b><small>Folds</small></div>
    </div>
    <div class="trn-label">Per-Fold</div>
    <div id="trn-rd-folds" class="trn-muted">lädt…</div>
    <div class="trn-label">ROC-Kurve</div>
    <svg id="trn-rd-roc" viewBox="0 0 160 130"></svg>
    <div class="trn-label">Feature-Gruppen-Importance</div>
    <div id="trn-rd-feat" class="trn-muted">lädt…</div>
    <div class="trn-label">Fehler nach Task</div>
    <div id="trn-rd-tasks" class="trn-muted">lädt…</div>
    <div class="trn-drawer-actions">
      <button class="trn-ghost trn-del" id="trn-rd-del">löschen</button>
      <button class="trn-cta" id="trn-rd-promote">als Headline speichern</button>
    </div>`;
  // Why: data-abgeleitete Strings via textContent (kein innerHTML-Inject).
  d.querySelector('#trn-rd-when').textContent = when;
  d.querySelector('#trn-rd-meta').textContent = `${run.model || '–'} · ${run.pool || '–'}`;
  d.querySelector('#trn-drawer-x').addEventListener('click', () => { d.hidden = true; });
  const rdPromote = d.querySelector('#trn-rd-promote');
  if (_isDeep(run.model)) { rdPromote.disabled = true; rdPromote.title = 'eval-only — nicht promotebar'; }
  rdPromote.addEventListener('click', () => _promoteRun(run.run_id));
  d.querySelector('#trn-rd-del').addEventListener('click',
    () => _confirmDelete(run, when, () => { d.hidden = true; }));

  const det = await api(`/training/runs/${run.run_id}`);
  if (d.hidden || d.querySelector('#trn-rd-folds') == null) return;  // zwischenzeitlich geschlossen
  const foldsBox = d.querySelector('#trn-rd-folds');
  if (det && !det.http_status && Array.isArray(det.cv) && det.cv.length) {
    foldsBox.classList.remove('trn-muted');
    const acc = (c) => Number(c.accuracy) || 0;
    foldsBox.innerHTML = det.cv.map(c =>
      `<div class="trn-bar">${c.held_out ?? '–'}`
      + `<i style="width:${Math.round(acc(c) * 100)}%;background:${acc(c) >= 0.87 ? 'var(--green)' : 'var(--yellow)'}"></i>`
      + `${f(c.accuracy)}</div>`).join('');
  } else {
    foldsBox.textContent = 'keine cv-Daten für diesen Run';
  }
  const featBox = d.querySelector('#trn-rd-feat');
  if (det && !det.http_status && Array.isArray(det.feature_groups) && det.feature_groups.length) {
    featBox.classList.remove('trn-muted');
    const max = Math.max(...det.feature_groups.map(g => g.imp), 1e-9);
    featBox.innerHTML = det.feature_groups.map(g =>
      `<div class="trn-bar">${g.group}<i style="width:${Math.round(g.imp / max * 100)}%;background:var(--accent)"></i></div>`).join('');
  } else {
    featBox.textContent = 'keine Feature-Importance (Modell nicht gespeichert)';
  }
  if (det && Array.isArray(det.roc) && det.roc.length) _renderRocInto(d.querySelector('#trn-rd-roc'), det.roc);

  const tr = await api(`/training/runs/${run.run_id}/tasks`);
  if (d.hidden) return;
  const tasksBox = d.querySelector('#trn-rd-tasks');
  const tasks = (tr && tr.tasks) || [];
  if (tasksBox && tasks.length) {
    tasksBox.classList.remove('trn-muted');
    const maxErr = Math.max(...tasks.map(t => t.fp + t.fn), 1);
    tasksBox.innerHTML = tasks.slice(0, 8).map(t => {
      const col = t.category === 'writing' ? 'var(--accent)' : 'var(--yellow)';
      return `<div class="trn-bar">${t.task}`
        + `<i style="width:${Math.round((t.fp + t.fn) / maxErr * 100)}%;background:${col}"></i>`
        + `${t.fp}FP/${t.fn}FN</div>`;
    }).join('');
  } else if (tasksBox) {
    tasksBox.textContent = 'keine Marker-Daten';
  }
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
