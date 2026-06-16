// ════════════════════════════════════════════════════════════
//  RECORDING — Study Mode renderer
//  Driven entirely by `s.study` from the WS status payload.
//  All user-derived strings (task label, instruction, content) are
//  inserted via textContent — never innerHTML — to avoid XSS even
//  though protocol JSON is repo-controlled.
// ════════════════════════════════════════════════════════════

import { api } from '/static/js/core/api.js';
import { toast } from '/static/js/core/toast.js';

// Why: the VL panel was being re-built every WS tick (~1 Hz) via
// stage.replaceChildren(), which detached/re-attached the
// Pause/Next/Abort buttons. Clicks landing in the replace window were
// silently dropped. We now rebuild only when the state KEY changes;
// tick-only refresh updates the timer + progress fill in-place.
let _renderedKey = null;
let _timerEl = null;
let _progressFillEl = null;
let _hintEl = null;

// ───── Audio cues — Web Audio API, no asset files ────────────
// Tick on each of the last 5 seconds of a phase; soft two-tone chime
// when crossing pre_task → running so the proband knows "go now".
let _audioCtx = null;
let _lastTickSec = null;
let _lastState = null;

// Why: WS-Status kommt nur ~1/s und stockt bei WLAN-Hängern — die Uhr
// fror dann ein und sprang beim Reconnect. Zwischen den Ticks zählt ein
// lokaler 250-ms-Loop die zuletzt gesyncte Restzeit weiter; jedes
// WS-Paket re-synct hart. UI-only: Task-Transitions und Marker bleiben
// server-authoritative, der Loop rendert nie einen Zustandswechsel.
let _lastStudy = null;
let _syncBaseMs = 0;
let _syncAtPerf = 0;
let _localTimer = null;

function _audio() {
  if (!_audioCtx && typeof AudioContext !== 'undefined') {
    try { _audioCtx = new AudioContext(); } catch { return null; }
  }
  if (_audioCtx && _audioCtx.state === 'suspended') {
    _audioCtx.resume().catch(() => {});
  }
  return _audioCtx;
}

// Why: AudioContext can only leave 'suspended' state in response to a
// user gesture. Tick/chime calls fire from WS ticks (no gesture stack),
// so we must construct + resume the ctx inside the START STUDY click
// handler. Plays a near-silent 1-sample tick to actually unlock audio
// on Safari (resume() alone is not always enough there).
export function primeStudyAudio() {
  const ctx = _audio();
  if (!ctx) return;
  try {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    g.gain.value = 0.0001;
    osc.connect(g);
    g.connect(ctx.destination);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.01);
  } catch { /* nothing to do */ }
}

function _tone(freq, duration, gain = 0.08) {
  const ctx = _audio();
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = 'sine';
  osc.frequency.value = freq;
  g.gain.value = 0;
  osc.connect(g);
  g.connect(ctx.destination);
  const now = ctx.currentTime;
  g.gain.linearRampToValueAtTime(gain, now + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, now + duration);
  osc.start(now);
  osc.stop(now + duration + 0.02);
}

function _playTick()  { _tone(880, 0.06, 0.05); }            // soft A5 click
function _playChime() {
  _tone(659.25, 0.16, 0.10);                                  // E5
  setTimeout(() => _tone(987.77, 0.22, 0.10), 80);            // B5 (4th-up)
}

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

// ───── Lokale Timer-Interpolation zwischen WS-Ticks ──────────
function _renderTimerTick(s, remainingMs) {
  const remainingSec = Math.ceil((remainingMs ?? 0) / 1000);
  if (remainingSec >= 1 && remainingSec <= 5 && remainingSec !== _lastTickSec) {
    _playTick();
    _lastTickSec = remainingSec;
  } else if (remainingSec > 5 || remainingSec <= 0) {
    _lastTickSec = null;
  }
  const urgent = remainingSec >= 1 && remainingSec <= 5;
  if (_timerEl) {
    _timerEl.textContent = _fmtClock(remainingMs);
    _timerEl.dataset.urgent = urgent ? '1' : '0';
  }
  if (_progressFillEl && Number.isFinite(s.task_duration_ms) && s.task_duration_ms > 0) {
    const pct = (1 - remainingMs / Math.max(1, s.task_duration_ms)) * 100;
    _progressFillEl.style.width = `${Math.min(100, Math.max(0, pct)).toFixed(1)}%`;
  }
  if (_hintEl && s.state === 'pre_task') {
    _hintEl.textContent = `starts in ${_fmtClock(remainingMs)} · ready your pen`;
  }
}

function _interpolatedRemainingMs() {
  return Math.max(0, _syncBaseMs - (performance.now() - _syncAtPerf));
}

function _startLocalTimer() {
  if (_localTimer) return;
  _localTimer = setInterval(() => {
    if (!_lastStudy) return;
    // Why: nur laufende Countdown-Phasen interpolieren — paused/done
    // stehen serverseitig still, lokales Weiterzählen wäre falsch.
    if (_lastStudy.state !== 'pre_task' && _lastStudy.state !== 'running') return;
    _renderTimerTick(_lastStudy, _interpolatedRemainingMs());
  }, 250);
}

function _stopLocalTimer() {
  if (_localTimer) { clearInterval(_localTimer); _localTimer = null; }
  _lastStudy = null;
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

  // Body class drives the fullscreen takeover via study-mode.css —
  // topbar + rec-shell fade out, #rec-study-view becomes a fixed
  // overlay covering the viewport. VL panel inside the study-view
  // stays interactive (Pause/Next/Abort + keyboard shortcuts).
  if (!s || !s.active) {
    wrap.style.display = 'none';
    document.body.classList.remove('study-active');
    _renderedKey = null;
    _timerEl = null;
    _progressFillEl = null;
    _hintEl = null;
    _lastTickSec = null;
    _lastState = null;
    _stopLocalTimer();
    return;
  }
  wrap.style.display = '';
  document.body.classList.add('study-active');

  // Chime on state crossing pre_task → running ("go now!")
  if (_lastState === 'pre_task' && s.state === 'running') {
    _playChime();
  }
  _lastState = s.state;

  // WS-Paket = Sync-Anker für die lokale Interpolation.
  _lastStudy = s;
  _syncBaseMs = s.task_remaining_ms ?? 0;
  _syncAtPerf = performance.now();
  _startLocalTimer();

  const key = `${s.state}|${s.task?.id ?? ''}|${s.task_index ?? ''}`;
  if (key !== _renderedKey) {
    stage.replaceChildren();
    if (s.state === 'pre_task')      stage.appendChild(_buildPreTask(s));
    else if (s.state === 'running')  stage.appendChild(_buildRunning(s, false));
    else if (s.state === 'paused')   stage.appendChild(_buildRunning(s, true));
    else if (s.state === 'done')     stage.appendChild(_buildDone());

    if (s.state !== 'done') stage.appendChild(_buildVLPanel());

    _timerEl = stage.querySelector('.study-timer-big, .study-timer-small');
    _progressFillEl = stage.querySelector('.study-progress-fill');
    _hintEl = stage.querySelector('.study-hint');
    _renderedKey = key;
  }
  // Timer / Progress / Urgency / Audio-Tick — gleiche Routine wie der
  // lokale 250-ms-Loop, hier mit der frischen Server-Restzeit.
  _renderTimerTick(s, s.task_remaining_ms ?? 0);
}

export async function studyCmd(cmd) {
  // Why: every VL gesture in the study view is also a chance to unlock
  // audio if the page was reloaded mid-session and missed the START click.
  primeStudyAudio();
  const endpoint = cmd === 'pause' ? '/study/pause'
                 : cmd === 'next'  ? '/study/next'
                 : cmd === 'abort' ? '/study/abort'
                 : null;
  if (!endpoint) return;
  try {
    const res = await api(endpoint, 'POST');
    if (cmd === 'abort') {
      // Why: VL expectation is "abort = end everything". /study/abort only
      // tears down the study state machine; the session keeps recording
      // until /session/stop is called.
      try { await api('/session/stop', 'POST'); } catch (e) { /* already stopped */ }
      toast('Study aborted, session stopped');
    } else if (cmd === 'pause') {
      toast(res?.action === 'resume' ? 'Resumed' : 'Paused');
    } else if (cmd === 'next') {
      toast('Next task');
    }
  } catch (e) {
    toast(`Error: ${e?.message ?? cmd}`);
  }
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
