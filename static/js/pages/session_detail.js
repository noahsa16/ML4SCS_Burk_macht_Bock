// static/js/pages/session_detail.js — Session Detail page module
//
// Heaviest page: alignment canvases with rAF/Chart.js state.
// onHide calls _destroyAlignCharts() — the headline perf-win for this module.

import { api } from '/static/js/core/api.js';
import { esc, escAttr, _roundRect } from '/static/js/core/dom.js';
import { renderState } from '/static/js/core/states.js';
import {
  fmtDuration, fmtHz, fmtNum, fmtMs, fmtSec, fmtClock, fmtClockGap,
} from '/static/js/core/format.js';
import { S } from '/static/js/core/state.js';
import { toast } from '/static/js/core/toast.js';
import { computeVerdict } from '/static/js/pages/sessions.js';
import {
  updatePageStrip, updateTabIndicator,
} from '/static/js/core/router.js';

// PAGE LIFECYCLE

export function mount(/* slot */) {
  // No persistent listeners needed at mount time.
  // toggle listeners are wired lazily in openSessionDetail on first call.
}

// Session Detail is entered explicitly via openSessionDetail(id), not via tab click.
export function onShow() {}

// Called by the tab-click handler and closeSessionDetail before hiding this page.
// Destroys Chart.js instances + cancels any pending rAF to free GPU/CPU.
export function onHide() {
  _destroyAlignCharts();
}

// No live-status updates needed while viewing a historical session.
export function onStatus(/* s */) {}

// PUBLIC ENTRY POINT

export async function openSessionDetail(sessionId) {
  const loadingSlot = document.getElementById('pageDetailLoading');
  if (loadingSlot) loadingSlot.style.display = '';

  try {
    S.selectedSessionId = sessionId;
    document.getElementById('detailTitle').textContent = `Session ${sessionId}`;
    document.getElementById('detailSubtitle').textContent = 'Loading…';
    document.getElementById('detailReportLink').href = `/sessions/${encodeURIComponent(sessionId)}/report?format=md`;

    // Restore section open-state from localStorage. Wire toggle listeners
    // once per page lifetime so they don't accumulate across detail opens.
    document.querySelectorAll('#page-session-detail details.detail-section').forEach(d => {
      const key = `sessionDetail.section.${d.dataset.section}.open`;
      d.open = localStorage.getItem(key) === '1';
    });
    if (!S._detailTogglesWired) {
      document.querySelectorAll('#page-session-detail details.detail-section').forEach(d => {
        const key = `sessionDetail.section.${d.dataset.section}.open`;
        d.addEventListener('toggle', () => {
          try { localStorage.setItem(key, d.open ? '1' : '0'); } catch {}
        });
      });
      S._detailTogglesWired = true;
    }

    // Load validation + alignment in parallel.
    const [validation, alignment] = await Promise.all([
      S.validationBySession[sessionId]
        ? Promise.resolve(S.validationBySession[sessionId])
        : api(`/sessions/${encodeURIComponent(sessionId)}/validation`, 'GET'),
      S.alignmentBySession[sessionId]
        ? Promise.resolve(S.alignmentBySession[sessionId])
        : api(`/sessions/${encodeURIComponent(sessionId)}/alignment`, 'GET'),
    ]);
    if (validation) S.validationBySession[sessionId] = validation;
    if (alignment) S.alignmentBySession[sessionId] = alignment;

    // The session_id may not be in S.allSessions if filters are tight — re-fetch list if missing.
    if (!S.allSessions?.find(s => s.session_id === sessionId)) {
      const data = await api('/sessions', 'GET');
      if (data) S.allSessions = data;
    }
    const session = S.allSessions.find(s => s.session_id === sessionId) || {};
    const quality = S.qualityBySession[sessionId] || {};

    _renderDetailHeader(session, quality, alignment);
    _renderDetailStreams(session, quality);
    renderSessionValidation(sessionId);
    renderAlignment(sessionId);
    _renderDetailIssues(quality);
  } finally {
    if (loadingSlot) loadingSlot.style.display = 'none';
  }
}

// RENDER HELPERS

function _renderDetailHeader(session, quality, alignment) {
  const durationSec = session.start_time && session.end_time
    ? (new Date(session.end_time) - new Date(session.start_time)) / 1000
    : 0;
  const verdict = computeVerdict(quality, alignment, durationSec);

  const person = (session.person_id || '').trim();
  document.getElementById('detailTitle').textContent =
    `${session.session_id || '–'}${person ? ' · ' + person : ''}`;
  const startFmt = session.start_time
    ? new Date(session.start_time).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' })
    : '–';
  document.getElementById('detailSubtitle').textContent =
    `${session.description ? '"' + session.description + '" · ' : ''}${startFmt} · ${fmtDuration(Math.floor(durationSec))}`;

  const v = document.getElementById('detailVerdict');
  v.className = `verdict-badge ${verdict.level}`;
  v.textContent = verdict.label;

  const mlStatus = quality?.ml_readiness?.status || 'unknown';
  const recStatus = quality?.recording_health?.status || 'unknown';
  const sigma = alignment?.sigma;

  const pillCls = (st) => st === 'ok' ? 'ok' : st === 'warn' ? 'warn' : st === 'bad' ? 'err' : '';
  const mlPill = document.getElementById('detailPillMl');
  mlPill.className = 'pill ' + pillCls(mlStatus);
  mlPill.textContent = `ML ${mlStatus}`;

  const recPill = document.getElementById('detailPillRec');
  recPill.className = 'pill ' + pillCls(recStatus);
  recPill.textContent = `Rec ${recStatus}`;

  const alignPill = document.getElementById('detailPillAlign');
  if (Number.isFinite(sigma)) {
    alignPill.className = 'pill ' + (sigma <= -3 ? 'ok' : sigma <= -2 ? 'warn' : 'err');
    alignPill.textContent = `Align σ=${sigma.toFixed(2)}`;
  } else {
    alignPill.className = 'pill';
    alignPill.textContent = 'Align —';
  }
}

function _renderDetailStreams(session, quality) {
  const watch = quality?.watch || {};
  const pen = quality?.pen || {};
  const airpods = quality?.airpods || {};
  const cov = (q) => q?.coverage_pct != null ? `${(q.coverage_pct * 100).toFixed(0)}%` : '–';
  // Why: All data is server-derived numbers/strings from trusted API — not user input.
  // esc() guards any string that could contain HTML-special chars.
  const html = [
    '<div class="drift-grid" style="grid-template-columns: repeat(3, 1fr)">',
    '  <div class="drift-box">',
    '    <div class="k">Watch</div>',
    `    <div class="v">${Number(session.watch_samples || 0).toLocaleString()}</div>`,
    `    <div class="k" style="margin-top:6px">${watch.estimated_hz ? esc(fmtHz(watch.estimated_hz)) : '– Hz'} · coverage ${cov(watch)}</div>`,
    '  </div>',
    '  <div class="drift-box">',
    '    <div class="k">Pen</div>',
    `    <div class="v">${Number(session.pen_samples || 0).toLocaleString()}</div>`,
    `    <div class="k" style="margin-top:6px">${pen.has_server_time ? 'wall-clock' : 'legacy'}</div>`,
    '  </div>',
    '  <div class="drift-box">',
    '    <div class="k">AirPods</div>',
    `    <div class="v">${Number(session.airpods_samples || 0).toLocaleString()}</div>`,
    `    <div class="k" style="margin-top:6px">${airpods.estimated_hz ? esc(fmtHz(airpods.estimated_hz)) : '–'}</div>`,
    '  </div>',
    '</div>',
  ].join('\n');
  document.getElementById('detailStreams').innerHTML = html;
}

function _renderDetailIssues(quality) {
  const ml = quality?.ml_readiness || { blockers: [], warnings: [], info: [] };
  const rec = quality?.recording_health || { blockers: [], warnings: [], info: [] };
  const all = [
    ...(ml.blockers || []).map(i => ({ ...i, sev: 'err' })),
    ...(ml.warnings || []).map(i => ({ ...i, sev: 'warn' })),
    ...(rec.blockers || []).map(i => ({ ...i, sev: 'err' })),
    ...(rec.warnings || []).map(i => ({ ...i, sev: 'warn' })),
  ];
  document.getElementById('detailIssuesCount').textContent = all.length;
  // Why: esc() and escAttr() sanitize all issue codes/messages before insertion.
  const chips = all.length
    ? all.map(i => `<span class="issue-chip" title="${escAttr(i.message || i.rationale || '')}">${esc(i.code)}</span>`).join('')
    : '<span class="issue-chip">no blocking issues</span>';
  document.getElementById('detailIssues').innerHTML = chips;
  document.getElementById('detailIssuesSummary').textContent = all.length
    ? 'Hover an issue chip to see rationale. Severity is mixed: blockers are red, warnings yellow.'
    : 'Nothing flagged on this session.';
}

// ALIGNMENT

function _alignFmtDelta(d) {
  if (d == null || !isFinite(d)) return '–';
  const ms = d * 1000;
  if (Math.abs(ms) < 1) return '0 ms';
  if (Math.abs(d) < 1) return `${ms.toFixed(0)} ms`;
  return `${d.toFixed(2)} s`;
}

export function renderAlignment(sessionId) {
  const section = document.getElementById('alignmentSection');
  const empty = document.getElementById('alignmentEmpty');
  const status = document.getElementById('alignmentStatus');
  const explainer = document.getElementById('alignmentExplainer');
  if (!section) return;
  section.style.display = 'block';

  if (empty) {
    empty.style.display = '';
    renderState(empty, 'loading', { title: 'Computing alignment…' });
  }

  const a = S.alignmentBySession[sessionId];

  if (!a) {
    status.textContent = 'Loading…';
    status.className = 'alignment-status';
    return;
  }
  if (a.available === false || a.error) {
    status.textContent = 'unavailable';
    status.className = 'alignment-status err';
    empty.style.display = '';
    renderState(empty, 'empty', {
      title: 'No alignment data',
      hint: 'Pen and watch streams don\'t overlap, or the session was too short to align.',
    });
    document.getElementById('alignDelta').textContent = '–';
    document.getElementById('alignSigma').textContent = '–';
    document.getElementById('alignStrokes').textContent = '–';
    document.getElementById('alignFactor').textContent = '–';
    _destroyAlignCharts();
    return;
  }
  empty.style.display = 'none';
  renderState(empty, 'clear');

  if (a.applied) {
    status.textContent = 'angewandt';
    status.className = 'alignment-status ok';
  } else {
    status.textContent = 'verworfen (σ > −2)';
    status.className = 'alignment-status skip';
  }

  document.getElementById('alignDelta').textContent = _alignFmtDelta(a.delta_sec);
  document.getElementById('alignSigma').textContent =
    a.sigma == null ? '–' : a.sigma.toFixed(2);
  document.getElementById('alignStrokes').textContent =
    a.n_strokes != null ? a.n_strokes.toLocaleString() : '–';
  document.getElementById('alignFactor').textContent =
    a.improvement_factor != null ? `${a.improvement_factor.toFixed(1)}×` : '–';

  const factorTxt = a.improvement_factor != null
    ? `Während der Pen-Striche ist die Hand <strong>${a.improvement_factor.toFixed(1)}× ruhiger</strong> als im Mittel über alle möglichen δ.`
    : '';
  let verdict = '';
  if (a.applied) {
    verdict = ` Confidence σ = <strong>${a.sigma.toFixed(2)}</strong> (Schwelle ≤ −2 für "anwenden") → der Shift von <strong>${_alignFmtDelta(a.delta_sec)}</strong> wird auf die Pen-Zeitstempel angewandt, bevor gemerged wird.`;
  } else if (a.sigma != null) {
    verdict = ` Confidence σ = <strong>${a.sigma.toFixed(2)}</strong> ist über der Schwelle (≤ −2) — die Suchkurve ist zu flach, also wird kein Shift angewandt und der Merge läuft auf den Roh-Zeitstempeln.`;
  }
  // Why: factorTxt and verdict use <strong> for numeric emphasis only; all
  // numeric values are formatted by _alignFmtDelta / toFixed — not user input.
  explainer.innerHTML =
    `Beim Schreiben hält die schreibende Hand die Uhr ruhig — Pausen und Gesten erzeugen mehr Bewegung. ` +
    `Der Algorithmus probiert verschiedene Zeitverschiebungen δ aus und wählt die, bei der die Pen-Striche auf die ruhigsten Phasen fallen. ` +
    factorTxt + verdict;

  _drawAlignVarianceCurve(a);
  _drawAlignTimeline(a);
}

function _destroyAlignCharts() {
  if (S.alignmentCharts.variance) { S.alignmentCharts.variance.destroy(); S.alignmentCharts.variance = null; }
  if (S.alignmentCharts.timeline) { S.alignmentCharts.timeline.destroy(); S.alignmentCharts.timeline = null; }
}

function _drawAlignVarianceCurve(a) {
  const ctx = document.getElementById('alignVarCanvas');
  if (!ctx || !window.Chart) return;
  if (S.alignmentCharts.variance) { S.alignmentCharts.variance.destroy(); S.alignmentCharts.variance = null; }
  const points = (a.variance_curve || []).filter(p => p.v != null).map(p => ({ x: p.d, y: p.v }));
  if (!points.length) return;
  const minPt = points.reduce((best, p) => (best == null || p.y < best.y) ? p : best, null);
  const ys = points.map(p => p.y);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const yPad = (yMax - yMin) * 0.12 || 0.01;

  const mean = a.mean_variance;
  const min  = a.min_variance;
  let acceptVar = null;
  if (a.sigma != null && a.sigma !== 0 && mean != null && min != null) {
    const std = (min - mean) / a.sigma;
    if (isFinite(std) && std > 0) acceptVar = mean + a.sigma_threshold * std;
  }

  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#c79a3a';
  const text2  = css.getPropertyValue('--text2').trim() || '#555';
  const text3  = css.getPropertyValue('--text3').trim() || '#888';
  const border = css.getPropertyValue('--border').trim() || '#ddd';
  const okGreen = '#2c8a47';
  const skipAmber = '#c98c1a';
  const minColor = a.applied ? okGreen : skipAmber;

  const overlayPlugin = {
    id: 'alignVarOverlay',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: ca, scales: { x, y } } = chart;
      ctx.save();
      if (mean != null && mean >= y.min && mean <= y.max) {
        const yp = y.getPixelForValue(mean);
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = text3;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(ca.left, yp); ctx.lineTo(ca.right, yp); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = text3;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
        ctx.fillText('Ø Varianz', ca.right - 4, yp - 2);
      }
      if (acceptVar != null && acceptVar >= y.min && acceptVar <= y.max) {
        const yp = y.getPixelForValue(acceptVar);
        ctx.setLineDash([2, 4]);
        ctx.strokeStyle = '#c54a4a';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(ca.left, yp); ctx.lineTo(ca.right, yp); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#c54a4a';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillText('Akzeptanz σ ≤ −2', ca.left + 4, yp + 2);
      }
      if (minPt) {
        const xp = x.getPixelForValue(minPt.x);
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = minColor;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(xp, ca.top); ctx.lineTo(xp, ca.bottom); ctx.stroke();
        ctx.setLineDash([]);
        const yp = y.getPixelForValue(minPt.y);
        ctx.fillStyle = minColor;
        ctx.beginPath(); ctx.arc(xp, yp, 5, 0, Math.PI * 2); ctx.fill();
        ctx.font = '11px system-ui, sans-serif';
        const label = `δ = ${_alignFmtDelta(minPt.x)}` + (a.sigma != null ? `   σ = ${a.sigma.toFixed(2)}` : '');
        const tw = ctx.measureText(label).width + 10;
        const lx = Math.min(xp + 8, ca.right - tw - 4);
        const ly = Math.max(yp - 22, ca.top + 4);
        ctx.fillStyle = minColor;
        ctx.globalAlpha = 0.92;
        _roundRect(ctx, lx, ly, tw, 18, 4); ctx.fill();
        ctx.globalAlpha = 1;
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(label, lx + 5, ly + 9);
      }
      ctx.restore();
    },
  };

  S.alignmentCharts.variance = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Mittlere Varianz unter Stroke-Maske',
          data: points,
          borderColor: accent,
          backgroundColor: accent + '26',
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.25,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      scales: {
        x: { type: 'linear', title: { display: true, text: 'Zeitverschiebung δ (Sekunden)', color: text2, font: { size: 11 } },
             ticks: { color: text3, font: { size: 10 }, maxTicksLimit: 9 },
             grid: { color: border + '40' } },
        y: { title: { display: true, text: 'Bewegung während Strichen', color: text2, font: { size: 11 } },
             ticks: { color: text3, font: { size: 10 }, maxTicksLimit: 5 },
             grid: { color: border + '40' },
             min: yMin - yPad, suggestedMax: yMax + yPad },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: ([it]) => `δ = ${it.parsed.x.toFixed(3)} s`,
            label: (it) => `Varianz: ${it.parsed.y.toFixed(4)}`,
          },
        },
      },
    },
    plugins: [overlayPlugin],
  });
}

function _drawAlignTimeline(a) {
  const ctx = document.getElementById('alignTimelineCanvas');
  if (!ctx || !window.Chart) return;
  if (S.alignmentCharts.timeline) { S.alignmentCharts.timeline.destroy(); S.alignmentCharts.timeline = null; }
  const tl = a.timeline || {};
  const xs = tl.watch_var_t || [];
  const ys = tl.watch_var_y || [];
  const rawPoints = xs.map((x, i) => ({ x, y: ys[i] })).filter(p => p.y != null);
  if (!rawPoints.length) return;
  const delta = tl.delta_sec_applied || 0;
  const strokes = tl.strokes_raw || [];

  const yVals = rawPoints.map(p => p.y);
  const yLo = Math.min(...yVals);
  const yHi = Math.max(...yVals);
  const yRange = yHi - yLo || 1;
  const points = rawPoints.map(p => ({ x: p.x, y: (p.y - yLo) / yRange }));

  const css = getComputedStyle(document.documentElement);
  const text2  = css.getPropertyValue('--text2').trim() || '#555';
  const text3  = css.getPropertyValue('--text3').trim() || '#888';
  const border = css.getPropertyValue('--border').trim() || '#ddd';
  const accent = css.getPropertyValue('--accent').trim() || '#c79a3a';

  const beforeColor = '#c54a4a';
  const afterColor  = '#2c8a47';

  const RAIL_TOP_Y0 = 1.05, RAIL_TOP_Y1 = 1.20;
  const RAIL_BOT_Y0 = -0.20, RAIL_BOT_Y1 = -0.05;

  const railsPlugin = {
    id: 'alignRails',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: ca, scales: { x, y } } = chart;
      ctx.save();

      const drawRail = (start, end, color, yTop, yBottom, alpha) => {
        const x0 = x.getPixelForValue(start);
        const x1 = x.getPixelForValue(end);
        if (x1 < ca.left || x0 > ca.right) return;
        const yA = y.getPixelForValue(yTop);
        const yB = y.getPixelForValue(yBottom);
        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.fillRect(
          Math.max(x0, ca.left), Math.min(yA, yB),
          Math.max(1.5, Math.min(x1, ca.right) - Math.max(x0, ca.left)),
          Math.abs(yB - yA),
        );
      };

      ctx.fillStyle = beforeColor;
      ctx.globalAlpha = 0.06;
      const yT0 = y.getPixelForValue(RAIL_TOP_Y0), yT1 = y.getPixelForValue(RAIL_TOP_Y1);
      ctx.fillRect(ca.left, Math.min(yT0, yT1), ca.right - ca.left, Math.abs(yT1 - yT0));
      if (delta) {
        ctx.fillStyle = afterColor;
        const yB0 = y.getPixelForValue(RAIL_BOT_Y0), yB1 = y.getPixelForValue(RAIL_BOT_Y1);
        ctx.fillRect(ca.left, Math.min(yB0, yB1), ca.right - ca.left, Math.abs(yB1 - yB0));
      }
      ctx.globalAlpha = 1;

      strokes.forEach(s => drawRail(s.start_s, s.end_s, beforeColor, RAIL_TOP_Y0, RAIL_TOP_Y1, 0.85));
      if (delta) {
        strokes.forEach(s => drawRail(s.start_s + delta, s.end_s + delta, afterColor, RAIL_BOT_Y0, RAIL_BOT_Y1, 0.85));
      }

      ctx.fillStyle = beforeColor;
      ctx.font = '10px system-ui, sans-serif';
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      const yTopMid = y.getPixelForValue((RAIL_TOP_Y0 + RAIL_TOP_Y1) / 2);
      ctx.fillText('Pen-Striche · roh', ca.left + 6, yTopMid);
      if (delta) {
        ctx.fillStyle = afterColor;
        const yBotMid = y.getPixelForValue((RAIL_BOT_Y0 + RAIL_BOT_Y1) / 2);
        ctx.fillText(`Pen-Striche · nach δ = ${_alignFmtDelta(delta)}`, ca.left + 6, yBotMid);
      }

      ctx.restore();
    },
  };

  const datasets = [
    {
      label: 'Watch-Bewegung',
      data: points,
      borderColor: accent,
      backgroundColor: accent + '1f',
      borderWidth: 1.6,
      pointRadius: 0,
      tension: 0.3,
      fill: 'origin',
    },
  ];

  S.alignmentCharts.timeline = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', intersect: false },
      scales: {
        x: { type: 'linear',
             title: { display: true, text: 'Zeit seit Watch-Start (s)', color: text2, font: { size: 11 } },
             ticks: { color: text3, font: { size: 10 }, maxTicksLimit: 8 },
             grid: { color: border + '40' } },
        y: { title: { display: true, text: 'Bewegung (normalisiert)', color: text2, font: { size: 11 } },
             ticks: {
               color: text3, font: { size: 10 },
               callback: (v) => (v >= 0 && v <= 1) ? v.toFixed(1) : '',
               stepSize: 0.25,
             },
             grid: { color: border + '40' },
             min: RAIL_BOT_Y0 - 0.02, max: RAIL_TOP_Y1 + 0.02 },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          filter: (it) => it.datasetIndex === 0,
          callbacks: {
            title: ([it]) => `t = ${it.parsed.x.toFixed(2)} s`,
            label: (it) => `Bewegung: ${(it.parsed.y * 100).toFixed(0)}%`,
          },
        },
      },
    },
    plugins: [railsPlugin],
  });
}

// SESSION VALIDATION / TIMELINE

export function renderSessionValidation(sessionId) {
  const v = S.validationBySession[sessionId];
  if (!v) {
    document.getElementById('detailTimeline').textContent = 'Validation data loading…';
    return;
  }

  const hasOverlap = v.overlap?.streams_overlap === true;

  if (!hasOverlap) {
    ['driftWatch', 'driftPen', 'driftRelative', 'driftSyncOffset'].forEach(id => {
      const el = document.getElementById(id);
      if (el) renderState(el, 'empty', { title: 'no overlap', inline: true });
    });
  } else {
    document.getElementById('driftWatch').textContent = fmtMs(v.source_clocks?.watch_source_to_local_drift_ms);
    document.getElementById('driftPen').textContent = fmtMs(v.source_clocks?.pen_source_to_local_drift_ms);
    document.getElementById('driftRelative').textContent = fmtMs(v.source_clocks?.relative_pen_vs_watch_clock_drift_ms);
    document.getElementById('driftSyncOffset').textContent = fmtClockGap(
      v.source_clocks?.source_clock_offset_gap_ms,
      v.sync_estimate
    );
  }

  renderTimeline(v);
}

export function renderTimeline(v) {
  const slot = document.getElementById('detailTimeline');
  if (!slot) return;
  if (!v || !v.overlap?.streams_overlap) {
    renderState(slot, 'empty', {
      title: 'No timeline overlap',
      hint: 'Pen and watch did not record in the same window for this session.',
    });
    return;
  }
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
  // Why: fmtSec returns formatted numeric strings; ev.dot_count is a number.
  // All values are server-side numerics — no user content.
  const penBlocks = (tl.pen_events || []).map(ev => {
    const left = pct(ev.start_s, duration);
    const width = Math.max(0.2, pct(ev.end_s - ev.start_s, duration));
    return `<span class="timeline-bar bar-pen" title="${esc(fmtSec(ev.duration_s))} · ${Number(ev.dot_count || 0)} dots" style="left:${left}%;width:${width}%"></span>`;
  }).join('');
  slot.innerHTML = [
    `<div class="timeline-axis">${ticks}</div>`,
    '<div class="timeline-row">',
    '  <div class="timeline-label">Watch</div>',
    '  <div class="timeline-track">',
    `    <span class="timeline-bar bar-watch" style="left:${watchStart}%;width:${Math.max(0.2, watchWidth)}%"></span>`,
    '  </div>',
    '</div>',
    '<div class="timeline-row">',
    '  <div class="timeline-label">Pen</div>',
    '  <div class="timeline-track">',
    `    <span class="timeline-bar bar-gap" style="left:${penStart}%;width:${Math.max(0.2, penWidth)}%"></span>`,
    `    ${penBlocks}`,
    '  </div>',
    '</div>',
  ].join('\n');
}

function pct(value, total) {
  const n = Number(value || 0);
  const d = Math.max(1, Number(total || 1));
  return Math.max(0, Math.min(100, n / d * 100));
}
