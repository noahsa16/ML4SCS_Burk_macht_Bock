import { api } from './api.js';
import { S } from './state.js';
import { esc, escAttr, fmtDuration, fmtHz, fmtMs, fmtSec, scoreBadge, scoreTooltip, syncDiagnostic } from './utils.js';

export async function loadSessions() {
  const [data, quality] = await Promise.all([
    api('/sessions', 'GET'),
    api('/sessions/quality', 'GET'),
  ]);
  S.allSessions = data || [];
  S.qualitySummary = quality?.summary || null;
  S.qualityBySession = {};
  (quality?.sessions || []).forEach(q => { S.qualityBySession[q.session_id] = q; });
  S.validationBySession = {};
  const validations = await Promise.all((S.allSessions || []).map(s =>
    api(`/sessions/${encodeURIComponent(s.session_id)}/validation`, 'GET')
      .then(v => ({ sid: s.session_id, validation: v }))
  ));
  validations.forEach(({ sid, validation }) => {
    if (validation) S.validationBySession[sid] = validation;
  });
  renderQualitySummary();
  renderSessions(S.allSessions);
  if (S.selectedSessionId) renderSessionValidation(S.selectedSessionId);
}

export function filterSessions() {
  const q = document.getElementById('sessionSearch').value.toLowerCase();
  renderSessions(S.allSessions.filter(s =>
    s.session_id?.toLowerCase().includes(q) ||
    s.person_id?.toLowerCase().includes(q) ||
    s.description?.toLowerCase().includes(q)
  ));
}

function renderSessions(rows) {
  const tbody = document.getElementById('sessionsBody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="13" class="table-empty">No sessions found</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(s => {
    const q = S.qualityBySession[s.session_id] || {};
    const validation = S.validationBySession[s.session_id] || {};
    const watch = q.watch || {};
    const pen = q.pen || {};
    const dur = s.start_time && s.end_time
      ? fmtDuration(Math.floor((new Date(s.end_time) - new Date(s.start_time)) / 1000))
      : (s.status === 'active' ? '<em style="color:var(--accent)">live</em>' : '–');
    const startFmt = s.start_time
      ? new Date(s.start_time).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' })
      : '–';
    const statusCls = s.status === 'active' ? 'badge-warn' : 'badge-ok';
    const ml = q.ml_readiness || { status: q.quality || 'unknown', blockers: [], warnings: [], info: [] };
    const recording = q.recording_health || { status: 'unknown', blockers: [], warnings: [], info: [] };
    const diag = syncDiagnostic(q, validation);
    const signalText = [
      watch.has_gyroscope ? 'gyro' : 'no gyro',
      watch.has_accelerometer ? 'accel' : 'no accel',
      pen.has_server_time ? 'pen time' : 'legacy pen',
    ].join(' · ');
    const activeRow = S.selectedSessionId === s.session_id ? ' active' : '';
    return `<tr class="click-row${activeRow}" onclick="selectSession('${escAttr(s.session_id)}')">
      <td class="mono bold">${esc(s.session_id)}</td>
      <td>${esc(s.person_id || '–')}</td>
      <td title="${escAttr(s.description || '')}">${esc(s.description || '–')}</td>
      <td class="mono" style="font-size:11px;color:var(--text2)">${startFmt}</td>
      <td class="mono">${dur}</td>
      <td class="mono">${Number(s.watch_samples || 0).toLocaleString()}</td>
      <td class="mono">${Number(s.pen_samples || 0).toLocaleString()}</td>
      <td class="mono">${watch.estimated_hz ? fmtHz(watch.estimated_hz) : '–'}</td>
      <td class="mono" title="${esc(signalText)}">${esc(signalText)}</td>
      <td title="${escAttr(scoreTooltip(ml))}">${scoreBadge(ml)}</td>
      <td title="${escAttr(scoreTooltip(recording))}">${scoreBadge(recording)}</td>
      <td title="${escAttr(diag.message)}"><span class="status-badge ${diag.cls}">${esc(diag.label)}</span></td>
      <td><span class="status-badge ${statusCls}">${esc(s.status || 'completed')}</span></td>
    </tr>`;
  }).join('');
}

function renderQualitySummary() {
  const summary = S.qualitySummary || { total: 0, ok: 0, warn: 0, bad: 0 };
  const ml = summary.ml_readiness || summary;
  document.getElementById('qualityTotal').textContent = summary.total ?? 0;
  document.getElementById('qualityOk').textContent = ml.ok ?? 0;
  document.getElementById('qualityWarn').textContent = ml.warn ?? 0;
  document.getElementById('qualityBad').textContent = ml.bad ?? 0;
}

export function selectSession(sessionId) {
  S.selectedSessionId = sessionId;
  renderSessions(S.allSessions);
  renderSessionValidation(sessionId);
}

function renderSessionValidation(sessionId) {
  const panel = document.getElementById('sessionValidationPanel');
  const v = S.validationBySession[sessionId];
  const q = S.qualityBySession[sessionId] || {};
  panel.classList.add('active');

  if (!v) {
    document.getElementById('validationTitle').textContent = `Session ${sessionId}`;
    document.getElementById('validationOverall').textContent = 'Loading…';
    document.getElementById('validationTimeline').innerHTML = '';
    document.getElementById('validationSummary').textContent = 'Validation is loading or unavailable.';
    return;
  }

  const duration = v.timeline_for_chart?.duration_s ?? v.watch?.duration_seconds ?? 0;
  const ml = q.ml_readiness || { status: v.status || q.quality || 'unknown', blockers: [], warnings: [], info: [] };
  const recording = q.recording_health || { status: 'unknown', blockers: [], warnings: [], info: [] };
  const diag = syncDiagnostic(q, v);
  document.getElementById('validationTitle').textContent = `Session ${sessionId} — ${fmtDuration(Math.round(duration || 0))} duration`;
  document.getElementById('validationOverall').textContent =
    `ML: ${ml.status || 'unknown'} · Recording: ${recording.status || 'unknown'}`;
  document.getElementById('validationMlReady').textContent = ml.status || 'unknown';
  document.getElementById('validationRecording').textContent = recording.status || 'unknown';
  document.getElementById('validationPenPct').textContent = v.overlap?.pen_dots_in_watch_range_pct != null
    ? `${Math.round(v.overlap.pen_dots_in_watch_range_pct * 1000) / 10}%`
    : '–';
  document.getElementById('validationSyncDiagnostic').textContent = diag.label;
  document.getElementById('driftWatch').textContent = fmtMs(v.source_clocks?.watch_source_to_local_drift_ms);
  document.getElementById('driftPen').textContent = fmtMs(v.source_clocks?.pen_source_to_local_drift_ms);
  document.getElementById('driftRelative').textContent = fmtMs(v.source_clocks?.relative_pen_vs_watch_clock_drift_ms);
  document.getElementById('driftSyncOffset').textContent = v.source_clocks?.source_clock_offset_gap_ms != null
    ? fmtMs(v.source_clocks.source_clock_offset_gap_ms)
    : (v.sync_estimate?.usable ? fmtMs(v.sync_estimate.median_offset_ms) : 'not estimated');

  document.getElementById('validationTimeline').innerHTML = renderTimeline(v);
  const intervals = v.timeline_for_chart?.pen_events?.length || 0;
  document.getElementById('validationSummary').textContent =
    `Watch: ${Number(v.watch?.total_samples || 0).toLocaleString()} samples over ${fmtSec(v.watch?.duration_seconds)} | ` +
    `Pen: ${intervals} writing intervals, ${Number(v.pen?.total_dots || 0).toLocaleString()} dots over ${fmtSec(v.pen?.duration_seconds)}. ` +
    `Sync diagnostics are optional calibration hints and do not reduce session quality.`;
  const actionableIssues = [
    ...(ml.blockers || []), ...(ml.warnings || []),
    ...(recording.blockers || []), ...(recording.warnings || []),
  ];
  document.getElementById('validationIssues').innerHTML = actionableIssues.length
    ? actionableIssues.map(i => `<span class="issue-chip" title="${escAttr(i.message || '')}">${esc(i.code)}</span>`).join('')
    : '<span class="issue-chip">no blocking issues</span>';
}

function renderTimeline(v) {
  const tl = v.timeline_for_chart || {};
  const duration = Math.max(1, Number(tl.duration_s || 1));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => {
    const sec = Math.round(duration * t);
    return `<span class="axis-tick" style="left:${t * 100}%">${sec}s</span>`;
  }).join('');
  const watchStart = pct(tl.watch_start_s || 0, duration);
  const watchWidth = pct((tl.watch_end_s || 0) - (tl.watch_start_s || 0), duration);
  const penStart = pct(tl.pen_start_s || 0, duration);
  const penWidth = pct((tl.pen_end_s || 0) - (tl.pen_start_s || 0), duration);
  const penBlocks = (tl.pen_events || []).map(ev => {
    const left = pct(ev.start_s, duration);
    const width = Math.max(0.2, pct(ev.end_s - ev.start_s, duration));
    return `<span class="timeline-bar bar-pen" title="${fmtSec(ev.duration_s)} · ${ev.dot_count || 0} dots" style="left:${left}%;width:${width}%"></span>`;
  }).join('');
  return `
    <div class="timeline-axis">${ticks}</div>
    <div class="timeline-row">
      <div class="timeline-label">Watch</div>
      <div class="timeline-track">
        <span class="timeline-bar bar-watch" style="left:${watchStart}%;width:${Math.max(0.2, watchWidth)}%"></span>
      </div>
    </div>
    <div class="timeline-row">
      <div class="timeline-label">Pen</div>
      <div class="timeline-track">
        <span class="timeline-bar bar-gap" style="left:${penStart}%;width:${Math.max(0.2, penWidth)}%"></span>
        ${penBlocks}
      </div>
    </div>`;
}

function pct(value, total) {
  const n = Number(value || 0);
  const d = Math.max(1, Number(total || 1));
  return Math.max(0, Math.min(100, n / d * 100));
}
