export function fmtDuration(sec) {
  const h = Math.floor(sec / 3600).toString().padStart(2, '0');
  const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
  const s = (sec % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

export function fmtHz(value) {
  const n = Number(value || 0);
  return n > 0 ? `${n.toFixed(n >= 10 ? 1 : 2)} Hz` : '– Hz';
}

export function fmtNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : '–';
}

export function fmtMs(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '–';
  const rounded = `${Math.round(n)}ms`;
  const abs = Math.abs(n);
  if (abs >= 86400000) return `${rounded} (~${(n / 86400000).toFixed(1)}d)`;
  if (abs >= 3600000) return `${rounded} (~${(n / 3600000).toFixed(1)}h)`;
  if (abs >= 60000) return `${rounded} (~${(n / 60000).toFixed(1)}min)`;
  if (abs >= 1000) return `${rounded} (~${(n / 1000).toFixed(1)}s)`;
  return rounded;
}

export function fmtSec(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n)}s` : '–';
}

export function fmtAgo(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n)) return '–';
  if (n < 1200) return 'just now';
  if (n < 60000) return `${Math.round(n / 1000)}s ago`;
  return `${Math.round(n / 60000)}m ago`;
}

export function fmtClock(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n)) return '--:--:--';
  return new Date(n).toLocaleTimeString('de-DE', { hour12: false });
}

export function fmtCommand(cmd) {
  if (!cmd || !cmd.command) return '–';
  const ok = cmd.ok === true ? 'ok' : (cmd.ok === false ? 'failed' : 'pending');
  return `${cmd.command} · ${ok}`;
}

export function fmtUptime(sec) {
  if (!sec) return '–';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`;
  return `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`;
}

export function statusBadgeClass(status) {
  if (status === 'ok') return 'badge-ok';
  if (status === 'bad') return 'badge-err';
  if (status === 'warn') return 'badge-warn';
  return 'badge-warn';
}

export function scoreBadge(score) {
  const status = score?.status || 'unknown';
  return `<span class="status-badge ${statusBadgeClass(status)}">${esc(status)}</span>`;
}

export function scoreTooltip(score) {
  const parts = [
    ...(score?.blockers || []),
    ...(score?.warnings || []),
    ...(score?.info || []),
  ].map(i => i.code);
  return parts.length ? parts.join(', ') : 'ready';
}

export function syncDiagnostic(q, validation) {
  const fromQuality = q?.diagnostics?.sync_diagnostic;
  const fromValidation = validation?.sync_diagnostic;
  const sync = q?.diagnostics?.sync_estimate || validation?.sync_estimate || {};
  const diagnostic = fromQuality || fromValidation;
  if (diagnostic) {
    return {
      label: diagnostic.label || diagnostic.status || 'not required',
      message: diagnostic.message || 'Optional sync diagnostic; not used for quality.',
      cls: diagnostic.status === 'needs_explicit_tap_protocol' ? 'badge-warn' : 'badge-ok',
    };
  }
  if (sync.usable) {
    return {
      label: `estimated (${sync.confidence || 'unknown'})`,
      message: 'Optional tap/peak calibration estimate is available.',
      cls: 'badge-ok',
    };
  }
  return {
    label: 'not required',
    message: sync.reason || 'No explicit tap/peak calibration pattern was detected; this is not a quality failure.',
    cls: 'badge-ok',
  };
}

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[ch]));
}

export function escAttr(value) {
  return esc(value).replace(/`/g, '&#096;');
}

let toastTimer;
export function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}
