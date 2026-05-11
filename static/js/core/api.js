import { toast } from '/static/js/core/toast.js';

/**
 * Run an HTTP request and return a typed envelope.
 *
 *   { ok: true,  data }                              // 2xx
 *   { ok: false, error: { kind, status?, message } } // network or non-2xx
 *
 * Caller decides how to surface the error (toast, inline state, retry, etc.).
 * This function does NOT toast or log on its own.
 *
 * @param {string} path
 * @param {string} [method='GET']
 * @param {object|null} [body=null]
 */
export async function apiResult(path, method = 'GET', body = null) {
  let res;
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    res = await fetch(path, opts);
  } catch (e) {
    return { ok: false, error: { kind: 'network', message: e?.message || 'Fetch failed' } };
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return {
      ok: false,
      error: { kind: 'http', status: res.status, message: data?.detail || res.statusText || 'HTTP error' },
    };
  }
  return { ok: true, data };
}

/**
 * Convenience wrapper around apiResult — for existing call sites that want
 * fire-and-forget behaviour. On network failure it toasts and returns null;
 * on HTTP error it returns the parsed body with `http_status` attached
 * (preserved from earlier behaviour). New code that wants typed error
 * handling should call apiResult() directly.
 */
export async function api(path, method = 'GET', body = null) {
  const r = await apiResult(path, method, body);
  if (r.ok) return r.data;
  if (r.error.kind === 'network') {
    toast('⚠ Server unreachable');
    return null;
  }
  // HTTP error: keep legacy shape (parsed body + http_status field).
  const fallback = { http_status: r.error.status };
  return fallback;
}

export async function downloadDebugPackage() {
  const pkg = await api('/debug/package');
  if (!pkg) return;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ml4scs_debug_${stamp}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast('Debug package exported');
}
