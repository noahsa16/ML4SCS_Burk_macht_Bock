// static/js/pages/system.js — System page module
// The inline onclick handlers (setTheme, setLogRows) remain in dashboard.js
// as shared globals (window.*) until Task 14 replaces onclick attributes.

import { fmtHz } from '/static/js/core/format.js';
import { renderState } from '/static/js/core/states.js';

let _mounted = false;
let _container = null;

const CHECK_IDS = ['checkAccel', 'checkGyro', 'checkPenTime', 'checkRate'];

export function mount(container) {
  if (_mounted) return;
  _container = container;
  _mounted = true;

  CHECK_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) renderState(el, 'empty', { title: 'waiting for status', inline: true });
  });
}

export function onStatus(s) {
  const validation = s.validation || {};
  const watchRate = Number(s.watch_rate_hz || 0);
  const penRate = Number(s.pen_rate_hz || 0);
  const gyroOk = validation.watch_has_gyroscope === true;
  const penClockOk = validation.pen_has_server_time === true;
  const accelEl = document.getElementById('checkAccel');
  const gyroEl = document.getElementById('checkGyro');
  const penTimeEl = document.getElementById('checkPenTime');
  const rateEl = document.getElementById('checkRate');
  if (accelEl) accelEl.textContent = validation.watch_has_accelerometer ? 'ok' : 'missing';
  if (gyroEl) gyroEl.textContent = gyroOk ? 'ok' : 'missing';
  if (penTimeEl) penTimeEl.textContent = penClockOk ? 'ok' : 'new recordings only';
  if (rateEl) rateEl.textContent = `${fmtHz(watchRate)} watch · ${fmtHz(penRate)} pen`;
}

export function onShow() {
  // No rAF loops or deferred fetches on this page.
}

export function onHide() {
  // No rAF loops or timers to clean up.
}
