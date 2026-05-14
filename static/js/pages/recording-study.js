// ════════════════════════════════════════════════════════════
//  RECORDING — Study Mode renderer
//  Driven entirely by `s.study` from the WS status payload.
//  All user-derived strings (task label, instruction, content) are
//  inserted via textContent — never innerHTML — to avoid XSS even
//  though protocol JSON is repo-controlled.
// ════════════════════════════════════════════════════════════

import { api } from '/static/js/core/api.js';

function _fmtClock(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function _el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = String(text);
  return e;
}

function _renderContent(task) {
  if (!task) return _el('div');
  if (task.content_type === 'list' && Array.isArray(task.content)) {
    const ol = _el('ol', 'study-content-list');
    for (const item of task.content) {
      ol.appendChild(_el('li', null, String(item)));
    }
    return ol;
  }
  return _el('div', 'study-content-text', String(task.content ?? ''));
}

function _buildPreTask(s) {
  const root = _el('div', 'study-pre-task');
  root.appendChild(_el('div', 'study-eyebrow',
    `/ task ${s.task_index} of ${s.task_total} · gleich beginnt`));
  root.appendChild(_el('div', 'study-title-big', s.task.label));
  root.appendChild(_el('div', 'study-instruction', s.task.instruction));
  root.appendChild(_el('div', 'study-timer-big', _fmtClock(s.task_remaining_ms)));
  root.appendChild(_el('div', 'study-hint',
    `starts in ${_fmtClock(s.task_remaining_ms)} · ready your pen`));
  return root;
}

function _buildRunning(s, paused) {
  const root = _el('div', `study-running${paused ? ' is-paused' : ''}`);
  const topbar = _el('div', 'study-topbar');
  const left = _el('div', 'study-topbar-left');
  left.appendChild(_el('span', 'study-eyebrow',
    `/ task ${s.task_index}/${s.task_total}`));
  left.appendChild(_el('span', 'study-topbar-title', s.task.label));
  topbar.appendChild(left);

  const right = _el('div', 'study-topbar-right');
  const progressOuter = _el('div', 'study-progress');
  const progressFill = _el('div', 'study-progress-fill');
  const pct = (1 - (s.task_remaining_ms / Math.max(1, s.task_duration_ms))) * 100;
  progressFill.style.width = `${pct.toFixed(1)}%`;
  progressOuter.appendChild(progressFill);
  right.appendChild(progressOuter);
  right.appendChild(_el('div', 'study-timer-small', _fmtClock(s.task_remaining_ms)));
  topbar.appendChild(right);
  root.appendChild(topbar);

  const content = _el('div', 'study-content-area');
  content.appendChild(_el('div', 'study-instruction-small', s.task.instruction));
  content.appendChild(_renderContent(s.task));
  root.appendChild(content);

  if (paused) {
    root.appendChild(_el('div', 'study-paused-overlay', 'Paused — VL override'));
  }
  return root;
}

function _buildDone() {
  const root = _el('div', 'study-done');
  root.appendChild(_el('div', 'study-done-glyph', '✓'));
  root.appendChild(_el('div', 'study-done-title', 'Studie abgeschlossen'));
  root.appendChild(_el('div', 'study-done-hint',
    'Die Aufnahme läuft weiter — Versuchsleiter kann jetzt stoppen.'));
  return root;
}

function _buildVLPanel() {
  const panel = _el('div', 'study-vl-panel');
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', 'Experimenter controls');

  const mk = (label, action, title, danger) => {
    const b = _el('button', `study-vl-btn${danger ? ' study-vl-btn--danger' : ''}`, label);
    b.type = 'button';
    b.title = title;
    b.addEventListener('click', () => studyCmd(action));
    return b;
  };

  panel.appendChild(mk('⏸', 'pause', 'Pause / resume (Space)', false));
  panel.appendChild(mk('⏭', 'next',  'Next task (→)', false));
  panel.appendChild(mk('✕', 'abort', 'Abort (Esc)', true));
  return panel;
}

export function renderStudyView(s) {
  const wrap = document.getElementById('rec-study-view');
  const stage = document.getElementById('recStudyStage');
  if (!wrap || !stage) return;

  if (!s || !s.active) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = '';

  stage.replaceChildren();  // clear previous frame
  if (s.state === 'pre_task')      stage.appendChild(_buildPreTask(s));
  else if (s.state === 'running')  stage.appendChild(_buildRunning(s, false));
  else if (s.state === 'paused')   stage.appendChild(_buildRunning(s, true));
  else if (s.state === 'done')     stage.appendChild(_buildDone());

  if (s.state !== 'done') stage.appendChild(_buildVLPanel());
}

export async function studyCmd(cmd) {
  const endpoint = cmd === 'pause' ? '/study/pause'
                 : cmd === 'next'  ? '/study/next'
                 : cmd === 'abort' ? '/study/abort'
                 : null;
  if (!endpoint) return;
  await api(endpoint, 'POST');
}

// Keyboard shortcuts — only fire while study view is visible.
function _isStudyActive() {
  const wrap = document.getElementById('rec-study-view');
  return wrap && wrap.style.display !== 'none';
}

function _onKey(e) {
  if (!_isStudyActive()) return;
  if (e.target.matches('input, textarea, select')) return;
  if (e.key === ' ')             { e.preventDefault(); studyCmd('pause'); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); studyCmd('next'); }
  else if (e.key === 'Escape')     { e.preventDefault(); studyCmd('abort'); }
}

if (typeof window !== 'undefined' && !window.__studyKeyboardWired) {
  window.addEventListener('keydown', _onKey);
  window.__studyKeyboardWired = true;
}
