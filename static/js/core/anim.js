// Skeleton: Mindest-Anzeigedauer ab Page-Load, damit der Loader nicht
// nur für 50 ms aufblitzt bevor die ersten WS-Daten ankommen.
const _PAGE_LOAD_T0 = performance.now();
export const SKEL_MIN_MS = 600;

const _numAnim = new Map();
let _animLoopRunning = false;
let _animLastFrame = 0;

export function setNumberSmooth(elementId, value, opts = {}) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const fmt = opts.format || ((v) => Math.round(v).toString());
  const target = Number(value);
  const timeConstant = opts.timeConstant ?? 350;
  const wantsSkel = el.dataset.skel !== undefined;

  if (!Number.isFinite(target)) {
    _numAnim.delete(elementId);
    // Skeleton nur solange wir noch nie einen echten Wert hatten — vermeidet
    // dass Werte zwischen Sessions in Loading-State zurückspringen.
    if (wantsSkel && el.dataset.skelDone === undefined) {
      el.classList.add('skel-loading');
    }
    el.textContent = opts.fallback ?? '–';
    return;
  }

  // Wenn Skeleton noch aktiv: Mindestanzeigedauer einhalten, sonst defer
  if (wantsSkel && el.classList.contains('skel-loading')) {
    const elapsed = performance.now() - _PAGE_LOAD_T0;
    if (elapsed < SKEL_MIN_MS) {
      setTimeout(() => setNumberSmooth(elementId, value, opts), SKEL_MIN_MS - elapsed);
      return;
    }
    el.classList.remove('skel-loading');
    el.dataset.skelDone = '1';
  } else if (wantsSkel) {
    el.dataset.skelDone = '1';
  }

  let st = _numAnim.get(elementId);
  if (!st) {
    // Erste Anzeige: direkt setzen, ohne 0 → real Animation
    st = { el, fmt, timeConstant, displayed: target, target, lastShownText: '' };
    _numAnim.set(elementId, st);
    const txt = fmt(target);
    el.textContent = txt;
    el.dataset.numValue = String(target);
    st.lastShownText = txt;
    return;
  }

  st.fmt = fmt;
  st.timeConstant = timeConstant;
  st.target = target;

  if (!_animLoopRunning) _startAnimLoop();
}

export function _startAnimLoop() {
  _animLoopRunning = true;
  _animLastFrame = performance.now();
  function tick(now) {
    const dt = Math.min(100, now - _animLastFrame); // cap to avoid big jumps after tab inactive
    _animLastFrame = now;
    let active = false;
    for (const [, st] of _numAnim) {
      const diff = st.target - st.displayed;
      if (Math.abs(diff) < 1e-4) {
        if (st.displayed !== st.target) {
          st.displayed = st.target;
          const txt = st.fmt(st.displayed);
          if (txt !== st.lastShownText) {
            st.el.textContent = txt;
            st.el.dataset.numValue = String(st.displayed);
            st.lastShownText = txt;
          }
        }
        continue;
      }
      active = true;
      const alpha = 1 - Math.exp(-dt / st.timeConstant);
      st.displayed += diff * alpha;
      const txt = st.fmt(st.displayed);
      if (txt !== st.lastShownText) {
        st.el.textContent = txt;
        st.el.dataset.numValue = String(st.displayed);
        st.lastShownText = txt;
      }
    }
    if (active) requestAnimationFrame(tick);
    else _animLoopRunning = false;
  }
  requestAnimationFrame(tick);
}
