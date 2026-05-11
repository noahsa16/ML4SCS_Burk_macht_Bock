import { toast } from '/static/js/core/toast.js';

export async function api(path, method = 'GET', body = null) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) data.http_status = res.status;
    return data;
  } catch (e) {
    toast('⚠ Server unreachable');
    return null;
  }
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
