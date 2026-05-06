# Week 03 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Build a stable, session-based data collection pipeline that streams Apple Watch IMU data and Moleskine Smart Pen data simultaneously into time-aligned CSVs, controlled from a single dashboard.

---

## Work Done This Week

### Project Setup

**Project Question:**
Can writing activity and concentration levels be detected using sensor data from a Moleskine Smart Pen as ground truth, and in combination with an Apple Watch?

**Hardware:**
- Moleskine Smart Pen (NWP-F130), connected via Bluetooth Low Energy
- Apple Watch Series 7 (native watchOS app)
- iPhone (native iOS app as bridge)

**Data Sources / Interfaces:**
- Native watchOS app capturing CoreMotion at 50 Hz
- iPhone bridge forwarding samples via HTTP to a local FastAPI server
- Direct BLE connection to the pen via Python (`bleak`)

**Tools:**
- Python, FastAPI, `bleak`, Pydantic
- Swift / SwiftUI, WatchConnectivity, CoreMotion
- Xcode, PyCharm, GitHub

### Data Work

- Switched from SensorLogger to a self-built native watchOS + iOS app — full control over sampling, batching and timestamps
- Watch streams accelerometer + gyroscope at 50 Hz in batches of 10 samples via WatchConnectivity to the iPhone, which posts them to the server
- Server writes one CSV per session per sensor: `data/raw/watch/{session}_watch.csv` and `data/raw/pen/{session}_pen.csv`
- Sessions are indexed in `data/sessions.csv` with auto-incrementing IDs (`S001`, `S002`, …) and start/stop timestamps, sample counts and status

### Technical Work — Pipeline Foundation

- **Native watch + phone app** (`watch_streamer/`): MotionManager captures `CMDeviceMotion` at 50 Hz, buffers and batches samples, drops oldest when overflowing. PhoneBridge normalizes payloads, queues HTTP POSTs and retries on failure.
- **FastAPI server**: session start/stop endpoints, `/watch` ingestion endpoint, WebSocket for live status, dashboard at `/`. Pen logger is spawned as a child subprocess and tied to the active session.
- **Modularization**: refactored the monolithic `server.py` into a clean `src/server/` package (config, state, csv_io, status, quality, broadcast, pen_proc, routes) with strict dependency direction.
- **Pydantic models**: introduced typed request/response models for more robust session handling and validation.
- **Dashboard**:  HTML/JS frontend showing live connection status, sample rates, per-second chart of acc/gyro magnitude and pen writing state, plus a sessions overview with quality metrics.
- **README overhaul**: rewrote with screenshots, project structure and quality-check documentation. Added `CLAUDE.md` to formalize the project context.

### Technical Work — Stability & Quality Pass (later in the week)

- **Diagnosed and fixed a WebSocket reconnect storm**: the iPhone bridge was opening and closing a fresh connection roughly every 3 s (close code 1001 = Going Away). Root cause: cancelled tasks' `.failure` callbacks kept stacking `scheduleReconnect()` calls, each tearing down the next healthy connection. Fixed via a `connectionEpoch` counter — receive/send callbacks now bail out silently when the epoch has moved on. After the fix the WebSocket stays stable for the entire session.
- **Server logging infrastructure**: new `src/server/logging_setup.py` attaches a rotating file handler (`logs/server.log`, 2 MB × 5 backups), a stream handler, and a custom `EventLogHandler` that pushes every log record into `state.event_log` so it shows up in `/status/debug` and on the dashboard. The `/ws` endpoint now logs `accepted` / `closed` with peer, lived-ms and close reason — exactly the data that nailed the reconnect storm.
- **Quality-check refactor and bug-fixes**: rewrote `src/server/quality.py` around an `ISSUE_SPECS` table (each issue carries `check`, `threshold`, `observed`, `rationale` plus per-score severities). Single source of truth via `_session_facts()`; `_session_quality`, `_session_validation` and the new `_session_report` are thin projections. Fixed three real bugs in the old checks: watch-rate threshold was 80–120 Hz instead of 40–60 Hz around the actual 50 Hz target, `expected_watch_samples` was computed at 100 Hz, and `missing_accelerometer` / `missing_gyroscope` had inconsistent severities even though both come from the same `CMDeviceMotion` frame. Added two new diagnostics: effective writing time (sum of `PEN_DOWN→PEN_UP` interval durations) and common Wall-Clock recording window. Loosened `pen_dots_outside_watch_range` from 95% to 80% and the count-mismatch tolerance from `max(5, 1%)` to `max(20, 2%)` to match real-world noise levels.
- **Per-session Markdown report**: new `GET /sessions/{id}/report?format=md` endpoint that renders a downloadable, self-explaining quality report listing every issue with its check, threshold, observed value, and rationale. Dashboard now has a "⤓ md" link in each session row.
- **Watch app icon**: registered the existing 1024×1024 PNG with the modern `idiom: universal · platform: watchos · size: 1024x1024` schema; before this only the iPhone-companion-settings role was filled, so the watch home screen showed the placeholder icon.

---

## Experiments

**End-to-end pipeline test:** Started a session from the dashboard, connected pen and watch, wrote on the Moleskine and confirmed both CSVs were written under the same `session_id`. Watch samples landed at ~50 Hz, pen samples at ~80 Hz, no sequence gaps over a multi-minute recording.

**Session quality decoupling:** Split session scoring into `ml_readiness` (is this usable for training?) and `recording_health` (did the hardware behave?). Sync confidence is now only a calibration diagnostic and no longer downgrades sessions on its own.

**Reference session (S018):** the post-firmware test recording is the cleanest session so far — 1,660 watch samples at exactly 50.0 Hz, no sequence gaps, accelerometer + gyroscope present, 590 pen dots all with wall-clock stamps, 100% of pen dots fall within the watch capture window, and `PEN_DOWN`/`PEN_UP` are perfectly paired (19/19). The remaining issue is the expected `source_clocks_not_shared` info message: the Moleskine pen's hardware clock is offset by ~922 days plus ~16.5 hours from wall-clock — irrelevant for current session-level checks, but a TODO for the sample-level merge step.

**Clock-offset analysis:** verified empirically that the pen hardware clock has a fixed ~922-day-plus-time-of-day offset relative to wall-clock, while the watch hardware clock matches wall-clock to within HTTP latency (~700 ms). The relative drift between the two device clocks across a 19 s session was −94 ms (≈ 5 ms/s), which is small and linear. Conclusion: a single tap-sync event at session start is enough to calibrate, with optional end-of-session re-sync for longer recordings. The `_estimate_sync_drift` heuristic is already in place and matched 19 events on S018; only the recording protocol is missing.

---

## Key Insights

- A native watch + phone app is significantly more reliable than third-party loggers — full control over batching, sequence numbers and timestamps makes downstream alignment much easier.
- Modularizing the server early (before the codebase grew further) paid off immediately: each module has a single responsibility and the dependency graph stays acyclic.
- Separating ML-readiness from recording-health avoids false negatives: a session with imperfect sync can still be perfectly fine for training if the streams themselves are clean.
- Tying the pen logger lifecycle to the session avoids the "unsessioned dots" problem we had last week.
- Quality checks need a self-explaining report. The first iteration just emitted opaque codes; reading the new Markdown report (issue + check + threshold + observed + rationale) makes it possible to question whether each check is set correctly — and the review immediately surfaced three real bugs in the thresholds that had been silently warning every session.
- Stability bugs need server-side diagnostics. The reconnect storm was invisible until the WebSocket close-codes and lived-ms were logged; once they appeared in `logs/server.log`, the cause was obvious within minutes.
- The Moleskine pen sends `PEN_DOWN` with sentinel `(-1, -1)` coordinates — the real position arrives with the first `PEN_MOVE`. Any UI or analysis code that filters out `-1` coordinates must handle "stroke continues from PEN_MOVE without a visible PEN_DOWN".

---

## Plan for Next Week

- Run first multi-subject recording sessions with all team members
- Add a tap-sync recording protocol (3× tap with the watch hand at session start) and wire `_estimate_sync_drift`'s offset into `merge_pen_watch` for sample-level alignment
- Start feature engineering on the merged dataset (windowing, rolling statistics on IMU, pen-derived speed/pressure features)

---

## Contributions

### Noah

- Built the native watchOS + iOS streaming app (MotionManager, PhoneBridge)
- Built the FastAPI server, session management, dashboard frontend and WebSocket status broadcasting
- Refactored the server into the `src/server/` package
- Added Pydantic-based session handling and the `/sessions/quality` endpoint with split ML-readiness / recording-health scoring
- Diagnosed and fixed the WebSocket reconnect storm via a `connectionEpoch` counter; added server-wide logging infrastructure
- Refactored `quality.py` around `ISSUE_SPECS` + `_session_facts`; fixed three real bugs in the thresholds; added per-session Markdown report export
- Fixed the live handwriting preview (Moleskine `PEN_DOWN` sentinel coordinate handling); registered the Watch app icon
- Wrote `CLAUDE.md` and overhauled the README with screenshots and pipeline documentation

### Ben

- _to be filled in_

### Taji

- _to be filled in_
