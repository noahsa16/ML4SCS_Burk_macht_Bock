/**
 * Render an empty / loading state into a slot. See plan task 1 for the slot-
 * mode contract.
 *
 * @param {HTMLElement} slot
 * @param {'loading' | 'empty' | 'clear'} kind
 * @param {object} [opts]
 * @param {string} [opts.title]   - first line, required for loading/empty
 * @param {string} [opts.hint]    - second line, optional
 * @param {string} [opts.glyph]   - override the default '/' glyph
 * @param {{ label: string, onClick: () => void }} [opts.action] - empty only
 * @param {boolean} [opts.inline] - compact one-line variant (replace mode only)
 */
export function renderState(slot, kind, opts = {}) {
  if (!slot) return;
  const mode = slot.dataset.stateMode === 'overlay' ? 'overlay' : 'replace';
  if (mode === 'overlay') {
    _overlay(slot, kind, opts);
  } else {
    _replace(slot, kind, opts);
  }
}

function _overlay(slot, kind, opts) {
  const wrap = slot.parentElement;
  if (kind === 'clear') {
    if (wrap) wrap.classList.add('has-data');
    return;
  }
  if (wrap) wrap.classList.remove('has-data');
  const titleEl = slot.querySelector('.empty-state-title');
  const hintEl = slot.querySelector('.empty-state-hint');
  if (titleEl && opts.title != null) titleEl.textContent = opts.title;
  if (hintEl && opts.hint != null) hintEl.textContent = opts.hint;
  const block = slot.querySelector('.empty-state');
  if (block) block.classList.toggle('empty-state--loading', kind === 'loading');
}

function _replace(slot, kind, opts) {
  if (kind === 'clear') {
    const child = slot.querySelector(':scope > .empty-state');
    if (child) child.remove();
    return;
  }
  const block = _buildBlock(kind, opts);
  slot.replaceChildren(block);
  if (kind === 'empty' && opts.action) {
    const btn = block.querySelector('.empty-state-action');
    if (btn) btn.addEventListener('click', opts.action.onClick);
  }
}

function _buildBlock(kind, opts) {
  const inline = opts.inline === true;
  const tag = inline ? 'span' : 'div';
  const root = document.createElement(tag);
  root.className = 'empty-state'
    + (kind === 'loading' ? ' empty-state--loading' : '')
    + (inline ? ' empty-state--inline' : '');

  const glyph = document.createElement(inline ? 'span' : 'div');
  glyph.className = 'empty-state-glyph';
  glyph.textContent = opts.glyph || '/';
  root.appendChild(glyph);

  const title = document.createElement(inline ? 'span' : 'div');
  title.className = 'empty-state-title';
  title.textContent = opts.title || '';
  root.appendChild(title);

  if (!inline && opts.hint) {
    const hint = document.createElement('div');
    hint.className = 'empty-state-hint';
    hint.textContent = opts.hint;
    root.appendChild(hint);
  }

  if (!inline && kind === 'empty' && opts.action) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'empty-state-action';
    btn.textContent = opts.action.label;
    root.appendChild(btn);
  }

  return root;
}
