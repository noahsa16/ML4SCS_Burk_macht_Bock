// Single source of live data. Pages must NOT mutate S directly — use the
// exported mutators below.

export const S = {
  sessionActive: false,
  sessionId: null,
  personId: null,
  startTime: null,
  watchSamples: 0,
  penSamples: 0,
  penConnected: false,
  watchConnected: false,
  uptime: 0,
  timerInterval: null,
  allSessions: [],
  chartBuffer: [],   // {t, mag, pen_writing}
  chartMax: 0,
  eventLog: [],
  sampleLog: [],
  logRows: Number(localStorage.getItem('logRows') || 24),
  theme: localStorage.getItem('theme') || 'light',
  qualityBySession: {},
  qualitySummary: null,
  validationBySession: {},
  alignmentBySession: {},
  alignmentCharts: { variance: null, timeline: null },
  selectedSessionId: null,
  penDotBuffer: [],   // {x, y, t, ts} — last ~500 pen dots for canvas
  penBounds: null,    // {minX, maxX, minY, maxY} — auto-scale bounds
  watchStatusText: 'Offline',
  watchBadgeClass: 'badge-err',
  lastStatus: null,
};

export function updateFromStatus(payload) {
  // Placeholder that mirrors the existing in-place mutation pattern used by
  // handleStatus(). Gains real responsibility in Task 8.
}

export function getActiveSession() { return S.selectedSessionId || null; }
export function getTheme() { return S.theme; }
export function getLogRows() { return S.logRows; }
