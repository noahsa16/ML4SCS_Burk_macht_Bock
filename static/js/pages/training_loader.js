// "Zwei Klassen trennen sich" — Lade-Animation für den Running-State des
// Training-Cockpits. Rein ambient: keine Zahlen, keine Modell-Interna, nur das
// Prinzip der binären Trennung (verstreute, unsichere Punkte sortieren sich in
// zwei kräftiger werdende Wolken; die Trennachse bleibt unsichtbar). Läuft nur,
// solange phase==='running' — start()/stop() steuert das Page-Modul.
export function createSeparationLoader(canvas) {
  if (!canvas) return { start() {}, stop() {} };
  const css = getComputedStyle(document.documentElement);
  const tok = (n) => css.getPropertyValue(n).trim();
  const COL = { accent: tok('--accent'), idle: tok('--text3') };
  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeInOut = (t) => t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  const CYC = 7.5, SEP = 0.46, HOLD = 0.78;  // mischen → trennen → halten → zurück

  let ctx, w = 0, h = 0, pts = [], T = 0, last = 0, raf = 0, on = false;

  function makePoints() {
    const n = clamp(Math.round(w / 13), 22, 64);  // Dichte skaliert mit Breite
    let s = 7; const rng = () => (s = (s * 9301 + 49297) % 233280) / 233280;
    pts = [];
    for (let i = 0; i < n; i++) pts.push({
      cls: i % 2,
      sx: 14 + rng() * (w - 28), sy: 12 + rng() * (h - 24),  // vermischte Streulage
      ty: 12 + rng() * (h - 24),                              // Ziel-Höhe getrennt
      gap: w * 0.05 + rng() * w * 0.16, jit: rng() * Math.PI * 2, r: 1.6 + rng() * 0.9,
    });
  }
  function fit() {
    const r = canvas.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.max(1, r.width * dpr); canvas.height = Math.max(1, r.height * dpr);
    ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    w = r.width; h = r.height; makePoints();
  }
  function draw(dt) {
    T += dt; const L = T % CYC;
    let p;
    if (L < SEP * CYC) p = easeInOut(L / (SEP * CYC));
    else if (L < HOLD * CYC) p = 1;
    else p = 1 - easeInOut((L - HOLD * CYC) / ((1 - HOLD) * CYC));
    ctx.clearRect(0, 0, w, h);
    const cx = w * 0.5;
    for (const pt of pts) {
      const bx = cx + (pt.ty - h * 0.5) * 0.10;  // unsichtbare, leicht geneigte Trennachse
      const tx = pt.cls === 0 ? bx - pt.gap : bx + pt.gap;
      const life = REDUCED ? 0 : 1.4;
      const x = lerp(pt.sx, tx, p) + Math.sin(T * 0.6 + pt.jit) * life * p;
      const y = lerp(pt.sy, pt.ty, p) + Math.cos(T * 0.5 + pt.jit) * life * p;
      ctx.fillStyle = pt.cls === 0 ? COL.accent : COL.idle;
      ctx.globalAlpha = lerp(0.38, 0.9, p);  // vermischt = unsicher, getrennt = sicher
      ctx.beginPath(); ctx.arc(x, y, pt.r, 0, 7); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  function loop(now) {
    if (!on) return;
    let dt = (now - last) / 1000; last = now; dt = Math.min(dt, 0.05);
    if (REDUCED) dt *= 0.5;
    draw(dt); raf = requestAnimationFrame(loop);
  }
  const onResize = () => { if (on) fit(); };
  function start() {
    if (on) return; on = true; fit();
    addEventListener('resize', onResize);
    last = performance.now(); raf = requestAnimationFrame(loop);
  }
  function stop() {
    on = false; cancelAnimationFrame(raf);
    removeEventListener('resize', onResize);
    if (ctx) ctx.clearRect(0, 0, w, h);
  }
  return { start, stop };
}
