// ════════════════════════════════════════════════════════════
//  STATE
// ════════════════════════════════════════════════════════════
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
  selectedSessionId: null,
  watchStatusText: 'Offline',
  watchBadgeClass: 'badge-err',
