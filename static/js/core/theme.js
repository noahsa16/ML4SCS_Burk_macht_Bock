import { S } from '/static/js/core/state.js';

export function setTheme(theme) {
  S.theme = theme === 'dark' ? 'dark' : 'light';
  localStorage.setItem('theme', S.theme);
  document.body.dataset.theme = S.theme;
  // Optionaler Settings-Select auf der System-Page bleibt synchron
  const sel = document.getElementById('themeSelect');
  if (sel) sel.value = S.theme;
  // Glyph im Topbar-Toggle: zeige das *gegenteilige* Symbol (was man kriegt
  // wenn man klickt). Light → Mond, Dark → Sonne.
  const glyph = document.getElementById('themeToggleGlyph');
  if (glyph) glyph.textContent = S.theme === 'dark' ? '☀' : '☾';
}

export function toggleTheme() {
  setTheme(S.theme === 'dark' ? 'light' : 'dark');
}
