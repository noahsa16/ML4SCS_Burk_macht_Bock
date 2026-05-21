# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

ML4SCS (Machine Learning for Smart and Connected Systems) — semester
project by Noah Samel, Ben Kriegsmann, and Tajuddin Snasni. Goal: a
general writing-activity detector from **Apple Watch IMU data alone** —
binary classification (writing vs. not writing) on the wrist-worn IMU
stream, independent of who is wearing the watch or what is being written.

The Moleskine Smart Pen is used **only during data collection** as
ground truth: pen stroke events (`dot_type`) label the watch samples at
the matching timestamp. Once trained, the pen is no longer needed —
inference runs on the watch.

Sensors during training-data collection:
- **Moleskine Smart Pen (NWP-F130)** — ground truth; x/y, pressure,
  tilt at ~80–90 Hz over BLE.
- **Apple Watch (Series 7)** — primary model input; accelerometer +
  gyroscope at 50 Hz via CoreMotion → iPhone bridge → FastAPI server.
- **AirPods (Pro / 3rd Gen)** — additional head-IMU stream via
  `CMHeadphoneMotionManager`, captured alongside the watch through the
  same iPhone bridge. Currently logged but not yet used by the model.

Status: data collection + preprocessing + watch-base merge + quality
checks + sliding-window features + Random Forest baseline + LOSO
cross-validation + Study Mode (counterbalanced protocol runner with
fullscreen proband UI and VL admin monitor) are operational. **Current
headline (10-person cross-subject LOSO, RF + per-session z-score +
`max_gap_ms=2500` label closing): accuracy 0.856 ± 0.032, ROC-AUC
0.928 ± 0.033, F1(writing) 0.864. Burst-aggregated @5s: acc 0.887,
AUC 0.960; @10s: acc 0.870, AUC 0.944; @30s: acc 0.831, AUC 0.909.**
Vorgänger-Headlines: 8-Probanden gap=2500 acc 0.861 ± 0.035 /
AUC 0.932 ± 0.035; 7-Probanden gap=2500 acc 0.868 ± 0.024 /
AUC 0.943 ± 0.014; 7-Probanden gap=2000 acc 0.864 ± 0.026 /
AUC 0.940; 5-Probanden gap=2000 acc 0.872 ± 0.020 / AUC 0.940;
3-Probanden gap=300 acc 0.842 ± 0.007 / AUC 0.909 (ExtraTrees).

## Setup

```bash
pip install -r requirements.txt
```

Dependencies: `pandas`, `numpy`, `scikit-learn`, `matplotlib`, `bleak`,
`fastapi`, `uvicorn`, `websockets`, `pytest`, `jupyter`, `notebook`.

## Running

**Server (required for data capture):**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```
Dashboard at `http://localhost:8000`.

**Pen logger standalone (no server):**
```bash
python pen_logger.py [--password XXXX] [--session S001]
```
With `--session`, output goes to `data/raw/pen/{session}_pen.csv`;
otherwise to `pen_log_YYYYMMDD_HHMMSS.csv` in the working directory.

**Test the watch HTTP endpoint:**
```bash
./scripts/ops/test_server.sh [IP]    # defaults to 127.0.0.1
```

**Convenience scripts:**
- `scripts/ops/start.sh` — boots the server and (optionally) a Cloudflare
  tunnel in one TTY UI; Ctrl+C cleans up both.
- `scripts/ops/tunnel.sh` — standalone Cloudflare quick tunnel
  (`https://*.trycloudflare.com → localhost:8000`).
- `scripts/plots/plot_alignment.py` — runs the pen↔IMU alignment for a
  session and renders the explanatory 4-panel figure (top: variance
  with stroke overlay raw vs δ-shifted; bottom: J(δ) coarse + fine).

**Merge / features / train / evaluate (full ML pipeline):**
```bash
python -m src.merge S029                          # watch-base merge → data/processed/S029_merged.csv
python -m src.features S029 --max-gap-ms 300      # sliding-window features → data/processed/S029_windows.csv
python -m src.training.train_loso                 # LOSO cross-validation (headline metric)
python -m src.training.within_session.train_rf S029   # within-session 80/20 RF (debug/feature-iteration)
python -m src.evaluation.evaluate S029            # placeholder, prints label distribution
python scripts/plots/plot_merged.py S029 --max-gap-ms 300   # visualize IMU + label overlay
```
Without args, `src.merge` / `src.features` operate on the most recent session.

**Run smoke tests:**
```bash
pytest tests/         # 138 tests, ~1.5 s
```

**Study Mode (counterbalanced data collection):**
From the dashboard's Recording page, toggle to Study Mode → pick
`v1` from the protocol dropdown → START STUDY. The proband side
enters a fullscreen takeover (Watch-style UI: pre-task countdown,
audio cues, instructions, last-5s urgent pulse); the VL controls
Pause / Next / Abort. Once running, the `#admin` page (hidden from
the tab strip — reached by **triple-clicking the brand logo**) gives
a second-screen monitor view for the experimenter without leaving
the proband's screen. See *Study Mode* below.

## Architecture

```
Apple Watch (MotionManager.swift)
  → batches of 10 samples at 50 Hz via WatchConnectivity
  → iPhone (PhoneBridge.swift)
  → HTTP POST /watch
  → server.py → data/raw/watch/{session}_watch.csv

AirPods (CMHeadphoneMotionManager on iPhone)
  → HTTP POST /airpods
  → server.py → data/raw/airpods/{session}_airpods.csv

Moleskine Smart Pen (BLE)
  → pen_logger.py (subprocess spawned by server.py)
  → data/raw/pen/{session}_pen.csv
                    ↓
       src/alignment/pen_match.py    (recover per-session δ via
                                      stroke-variance minimization;
                                      σ ≤ -3 → use for ML)
                    ↓
       src/merge/merge.py            (watch-base: 1 row per watch
                                      sample with label_writing from
                                      pen activity in ±40 ms)
                    ↓
         data/processed/{session}_merged.csv  (50 Hz watch + raw label)
                    ↓
       src/features/windows.py       (sample-level label closing,
                                      max_gap_ms=2500 → "writing mode"
                                      semantics; then 1 s / 0.5 s
                                      sliding windows → 88 features
                                      in 6 groups: time-stats, spectral
                                      (FFT), jerk, ZCR, magnitude,
                                      cross-axis correlations)
                    ↓
         data/processed/{session}_windows.csv  (1 row per window)
                    ↓
       src/training/train_loso.py    (HEADLINE: LOSO by person, N=10,
                                      RF 200 trees + per-session z-score,
                                      class_weight=balanced, then per-
                                      session rolling-mean burst-agg
                                      @1s/5s/10s/30s decision-windows)
       src/training/within_session/  (debug only — temporal 80/20 split
         train_rf.py                  for feature/smoothing iteration)
                    ↓
         models/rf_all.joblib  (deployment, --save-final-model)
         models/loso_cv.csv    (per-fold metrics, --save-cv-csv)
                    ↓
         acc 0.856 ± 0.032  |  AUC 0.928 ± 0.033  |  F1(w) 0.864
         burst @30s: acc 0.831 / AUC 0.909  (Schreibzeit-tracking)
```

### Server (`server.py` + `src/server/`)

`server.py` is a thin entry point (~50 lines). All logic lives in
`src/server/`. Dependency order (no backwards imports):

```
config.py          paths, field names, sessions.csv init
                   (re-exports PEN_FIELDNAMES from src/pen_schema.py)
utils.py           pure helpers (_now_ms, _as_float, _mad …)
state.py           SessionState class + global `state` object
logging_setup.py   RotatingFileHandler + EventLog handler wiring
csv_io.py          read/write watch + pen + airpods + sessions CSVs;
                   _next_session_id() (scans raw/{pen,watch,airpods}
                   to avoid ID reuse); _pen_recent_dots() for the live
                   whiteboard preview
status.py          connection status + _status_payload() for WS broadcasts
issues.py          ISSUE_SPECS table + _TARGET_WATCH_HZ / _TARGET_AIRPODS_HZ;
                   single source of truth for issue codes/severities
sync.py            sync-confidence helpers around the alignment output
timelines.py       per-session timeline reconstruction for validation views
quality.py         _session_facts() = single source of truth for facts;
                   _session_quality / _session_validation / _session_report
                   (re-exports ISSUE_SPECS for external consumers)
broadcast.py       _broadcast() + _status_loop() (1-s tick)
pen_proc.py        starts/stops pen_logger.py as a subprocess
models.py          Pydantic schemas (WatchEnvelope, SessionStartBody …)
study.py           Study Mode internals: protocol loader (Pydantic
                   schema), LATIN_SQUARE_3 (6 permutations of 3 writing
                   tasks), scheduler that interleaves writing tasks with
                   pauses, and the runtime state machine (idle / running
                   / paused / done). Pure Python — no FastAPI imports,
                   fully unit-testable.
routes/            FastAPI endpoint package — one APIRouter per concern
                   (watch.py, airpods.py, pen.py, sessions.py,
                    study.py, dashboard.py, ws.py, _helpers.py);
                    __init__.py aggregates them into a single `router`
```

`src/pen_schema.py` is a top-level shared module (no deps) so
`pen_logger.py` can stay a standalone script while still sharing the
canonical `PEN_FIELDNAMES` with the server.

The pen logger runs as an `asyncio.create_subprocess_exec` child;
`POST /pen/connect` and `/pen/disconnect` control it independently, and
session start/stop start/stop it automatically.

### Key endpoints

- `GET /` — `dashboard.html`
- `POST /session/start` / `POST /session/stop` — write `data/sessions.csv`
- `POST /watch` — receives IMU batches; supports both flat list and
  `{samples: [...]}` envelope formats
- `POST /airpods` — same envelope shape, head-IMU stream
- `GET /sessions/quality` — quality snapshot for every session
- `GET /sessions/{id}/validation` — deep validation (timeline, drift, sync)
- `GET /sessions/{id}/report?format=json|md` — full per-session report;
  Markdown form is the "⤓ md" link in the dashboard
- `POST /sessions/{id}/mark-test` — retroactive flip of a session to
  `study_mode='test'`, prepends `[TEST] ` to description; the
  resulting session is excluded from Latin-Square counting and from
  default LOSO inclusion
- `GET /study/protocols` — lists available protocols in
  `study_protocols/` (currently `v1.json`)
- `POST /study/start` — boots a Study-Mode session: loads protocol,
  computes Latin-Square ordering from `subject_index`, starts the
  session, writes the first marker to `data/raw/markers/{id}_markers.csv`
- `POST /study/next` / `POST /study/pause` / `POST /study/abort` —
  drive the state machine; emits markers on every transition
- `WebSocket /ws` — dashboard status (1 s tick) + iPhone bridge
  messages + per-tick `study` payload (current task, time-remaining,
  next-task preview)

`_status_loop` broadcasts `_status_payload()` once a second, updates
rolling Hz estimates, and maintains a 60-point rolling chart buffer
(acc magnitude, gyro magnitude, pen writing state).

### Dashboard frontend (`dashboard.html` + `static/`)

`dashboard.html` is a thin ~88-line shell: head with stylesheet + module
preload tags, topbar markup, five empty `<div data-view="..."></div>` page
slots, and `<script type="module" src="/static/dashboard.js">`.

`static/dashboard.js` is the bootstrap (~165 lines). On `hashchange` it
calls `showPage(pageId)`, which lazy-fetches the matching partial from
`static/views/<page>.html` (cached after first fetch), injects it via
`DOMParser` + `replaceChildren`, calls the page module's `mount(slot)`
exactly once, then `onShow()`. Switching away calls the previous page's
`onHide()`. WS ticks go through `setActivePageDispatcher`, which routes
`onStatus(payload)` to the active page only — hidden pages do no
per-tick work. Session Detail's `onHide` calls `_destroyAlignCharts()`
to tear down the alignment-plot canvases when leaving (the main perf
mechanism, since that page is the heaviest).

Page modules live in `static/js/pages/{recording,recording-study,
sessions,session_detail,settings,admin}.js` and all export the same
four-function contract: `mount(container)`, `onStatus(payload)`,
`onShow()`, `onHide()`.

`recording-study.js` is the **fullscreen takeover** for the proband
side once Study Mode is running. It is a sibling of `recording.js`:
the recording view switches between the two depending on whether
study runtime state is active. When active, it adds the
`body.study-active` class which takes over the whole viewport (topbar
hidden), performs a FLIP-style animation between tasks, and plays
two audio cues — an 880 Hz tick during the last-5-second urgent pulse
and an E5/B5 two-note chime at task transitions. Markup is built via
the DOM API (no template string innerHTML) to avoid re-mounting the
same nodes between ticks. Styles live in `static/css/study-mode.css`.

The `#admin` page is **hidden from the tab strip** (intentionally —
the proband must not see it). It is reached by triple-clicking the
brand logo in the topbar (the easter-egg lives in `dashboard.js`).
It mirrors the live status / chart / connections summary so the VL
can monitor the recording from a second device (iPad) without
intruding on the proband's screen. Files: `static/js/pages/admin.js`,
`static/views/admin.html`, `static/css/admin.css`.

Cross-cutting concerns in `static/js/core/`:
- `state.js` — `S` object + `updateFromStatus(payload)` + named getters
- `ws.js` — WebSocket connection, reconnect with backoff. On each
  message: `updateFromStatus(msg)` → `handleStatus(msg, prevSessionId)`.
  Note the second arg: it carries the pre-update `S.lastStatus.session_id`
  so cross-session canvas clearing still works after state mutation moved
  into `state.js`.
- `status_cluster.js` — `handleStatus` updates the topbar pills/badges
  and ends with `_activePageDispatch(s)`.
- `router.js` — hash routing, tab indicator, `closeSessionDetail`.
  `closeSessionDetail` sets `location.hash = 'sessions'` (not
  `history.replaceState`) so `hashchange` fires and the bootstrap's
  `activePage` stays in sync.
- `api.js`, `dom.js`, `format.js`, `theme.js`, `anim.js`, `toast.js` —
  pure helpers + leaf services.

Per-page styles live in `static/css/<page>.css`; cross-cutting tokens and
layout are in `static/css/base.css` + `static/css/topbar.css`.

**Inline `onclick=` handlers in view partials** reference functions as
`window.foo()`. Since the bootstrap is a module (functions are not global
by default), `dashboard.js` ends with an explicit
`Object.assign(window, { ... })` block exposing every handler name. If
you move or rename a function called from inline HTML, update that block.

**Static-asset HTTP smoke test** at `tests/test_dashboard_static.py`
parametrises every JS module / view partial / stylesheet path. Catches
the silent-404 failure mode (browsers serve `text/html` for missing
`.js` and ES modules fail to parse opaquely). When you add a new file
under `static/js/`, `static/views/`, or `static/css/`, add the path to
the parametrise list.

### iOS / watchOS app (`watch_streamer/`)

Two Xcode targets:

- **WatchStreamer Watch App** (`MotionManager.swift`): captures
  `CMDeviceMotion` at 50 Hz, batches of 10 over `WCSession.sendMessage`
  (or `transferUserInfo` background fallback). Drops oldest samples
  when buffer exceeds 500.
- **WatchStreamer (iPhone)** (`PhoneBridge.swift`): receives
  WatchConnectivity messages, normalises payload, queues HTTP POSTs
  to `http://{serverIP}:8000/watch`. Server IP in `UserDefaults`
  (`"serverIP"`).

Watch ↔ iPhone start/stop commands flow over WatchConnectivity. The
server broadcasts `{type: "start"/"stop", session_id: …}` over the WS;
the iPhone bridge forwards to the watch.

**WS connection epoch (`ServerCommandListener.swift`):** each
`connect()` bumps `connectionEpoch`. Receive/send callbacks capture
the epoch at registration; if it has moved on by callback time the
callback returns silently. This prevents a cancelled task's `.failure`
from scheduling a reconnect that kills the live connection — was the
root cause of an earlier 3 s reconnect storm.

**Haptic feedback** is gated on actual transitions (false→true /
true→false) rather than every `@Published` re-emit, so the iPhone
no longer vibrates continuously when the server is down.

### ML pipeline (`src/`)

- `src/alignment/pen_match.py` — `pen_match()`, `match_pen_data()`,
  `strokes_from_dot_types()`, `reconstruct_watch_wall_clock()`. Recovers
  the per-session pen↔watch clock offset δ via stroke-window variance
  minimization (TH Zürich algorithm, see *Sample-level merge alignment*
  below). Replaces the planned tap-sync recording protocol.
- `src/merge/prep.py` — per-stream cleaning helpers (`prepare_pen_data()`,
  `prepare_watch_data()`, `load_csv()`). Still exported for external use;
  the canonical ML merge no longer needs the pen-side per-sample features.
- `src/merge/merge.py` — `merge_watch_pen()`: **watch-base merge**.
  Calls `match_pen_data`, applies δ to `pen.local_ts_ms` when σ ≤ -2,
  then `merge_asof` with **watch as base** within ±`label_tol_ms`
  (default 40 ms). Result: 1 row per watch sample, with `label_writing`
  = 1 iff nearest pen `dot_type` ∈ {PEN_DOWN, PEN_MOVE} within tolerance,
  else 0. Watch samples in pen-gaps → label 0 (the negative class —
  critical for binary classification).
- `src/merge/__main__.py` — CLI: `python -m src.merge [SESSION_ID]`,
  writes per-session to `data/processed/{session}_merged.csv` (no
  overwriting).
- `src/features/windows.py` — `smooth_labels()` + `build_windows()`.
  Sample-level **morphological closing** on the binary label sequence
  (idle gaps ≤ `max_gap_ms` between writing runs → flipped to writing;
  default 300 ms) before windowing. Then 1 s sliding windows with
  0.5 s stride → **88 features per window**, in 6 semantic groups:
  *time_stats* (36: mean/std/min/max/rms/range per axis), *spectral*
  (24: dominant frequency, spectral centroid, spectral entropy, 3–8 Hz
  band ratio per axis via rFFT — DC-bin removed before centroid/
  entropy), *zcr* (6 per-axis zero-crossing rates), *jerk* (8: std +
  mean-abs of d/dt on accel axes + magnitudes; `× fs_hz` for scale
  invariance), *magnitude* (6 accel/gyro mag mean/std/energy), and
  *correlation* (6 cross-axis Pearson pairs, accel-pairs + gyro-pairs,
  zero-std-safe). Window label = 1 iff ≥ 60% of samples in the window
  have `label_writing == 1`. Optional opening (`--max-spike-ms`) is
  implemented but defaults off — empirically didn't help on S029.
- `src/features/__main__.py` — CLI: `python -m src.features [SESSION_ID]
  [--max-gap-ms 300] [--max-spike-ms 0]`, writes
  `data/processed/{session}_windows.csv`.
- `src/training/within_session/train_rf.py` — **debug/feature-iteration
  baseline, not the headline metric.** `RandomForestClassifier` (200
  trees, `class_weight="balanced"`) with a temporal 80/20 split by
  `t_center_ms` plus a 4-window gap at the cut to prevent overlap
  leakage (adjacent windows share 50% of samples). Use this for fast
  iteration on features or label-smoothing parameters, *not* to claim
  generalisation — within-session metrics only measure "can the model
  finish this session given the start of it". Loads cached
  `{session}_windows.csv` if present, else builds on the fly. Dumps
  to `models/rf_{session}.joblib`.
- `src/training/train_loso.py` — **headline metric for the project
  goal.** Leave-One-Out cross-validation. Default `--by person` (true
  LOSO — the right metric for the "general writing detector" promise);
  fallback `--by session` for leave-one-session-out, useful while only
  one subject has been recorded. Filters sessions via
  `verdict ∈ {trainable, usable}` from `sessions.csv` (override with
  `--include-all`). No `temporal_split` needed — the
  subject/session-hold-out is a strictly stronger leakage guarantee
  than zeitliche Trennung (held-out windows were never seen). Reports
  per-fold accuracy/ROC-AUC plus mean ± std summary, **plus
  burst-aggregated metrics at multiple decision-window scales**
  (1 s / 5 s / 10 s / 30 s — controlled by `BURST_SCALES_SEC`).
  Probabilities are smoothed via per-session rolling mean (stride
  derived from median Δ`t_center_ms`, robust to non-default window
  configs), then re-thresholded at ≥ 0.5. Critical: smoothing groups
  by `session_id` so predictions from temporally-distant sessions in
  the same fold are never mixed. The burst scales surface the share
  of model error that is high-frequency noise versus systematic, and
  give the user-facing metric for aggregated use-cases (e.g.
  Schreibzeit-tracking) without retraining. Per-session z-score
  normalization of features is on by default (`--no-zscore` to
  disable). It standardises each feature column per `session_id`
  before fitting so subject-dependent baselines (wrist size,
  handedness, watch position) don't shift the model's decision
  threshold. Empirically: jumped acc from 0.812 → 0.838 on the
  3-person dataset and tightened fold-σ 4× (0.042 → 0.009) — the
  biggest single ML-side improvement of the project.
- `scripts/ml/compare_models.py` — runs LOSO on the same splits with
  RF / ExtraTrees / HistGradBoost / LogReg / MLP / SVM-RBF to verify
  RF is still competitive. Same `--no-zscore` flag. Liest
  vor-generierte `{session}_windows.csv` aus `data/processed/`.
- `scripts/ml/compare_models_at_gap.py` — gleiches Modell-Panel, aber
  baut die Features on-the-fly bei beliebigem `--gap` neu, ohne die
  Cache-Dateien anzufassen. Nützlich, um Modell-Rangfolge bei
  alternativen Label-Closing-Werten zu prüfen ohne Re-Generation.
- `scripts/ml/ablate_gap_loso.py` — Label-Closing-Ablation: fährt den
  vollen LOSO-Lauf bei mehreren `max_gap_ms`-Werten und reportiert
  per-Fold + Mean/Std. Quelle der Headline-Entscheidung
  `max_gap_ms=2000` (siehe *Label smoothing* unten).
- `src/evaluation/evaluate.py` — placeholder that loads
  `{session}_merged.csv` and prints label distribution. Real metrics
  live in `train_loso.py` (cross-subject) and
  `within_session/train_rf.py` (within-session sanity check).
- `scripts/plots/plot_merged.py` — visualizes ‖acc‖, ‖gyro‖, and
  `label_writing` over the session; supports `--max-gap-ms` /
  `--max-spike-ms` to preview label smoothing effects.

The merge skips the δ shift when the alignment confidence is weak
(`sigma_minimal_variance > -2`); the quality engine surfaces this as
`low_sync_confidence` (warn) and `sync_failed` (bad). Older pen logs
without `local_ts_ms` cannot be aligned and are flagged as
`legacy_pen_time`.

## Data Schemas

**Watch CSV** (`data/raw/watch/{session}_watch.csv`):
```
local_ts, local_ts_ms, session_id, sequence, sample_rate_hz,
watch_sent_at, phone_received_at, server_received_ms, source,
ts, ax, ay, az, rx, ry, rz
```

**Pen CSV** (`data/raw/pen/{session}_pen.csv`):
```
local_ts, local_ts_ms, timestamp, x, y, pressure, dot_type,
tilt_x, tilt_y, section, owner, note, page
```
`dot_type` ∈ {`PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER`}. Rows with
`x == -1` and `y == -1` are framing events (no position) — filter
them out before spatial analysis. `label_writing` is derived as 1 for
`PEN_DOWN`/`PEN_MOVE`, else 0. Schema is defined in
`src/pen_schema.py` (shared with `pen_logger.py`).

**AirPods CSV** (`data/raw/airpods/{session}_airpods.csv`):
```
local_ts, local_ts_ms, session_id, sequence, sample_rate_hz,
airpods_sent_at, phone_received_at, server_received_ms, source,
ts, ax, ay, az, rx, ry, rz, qw, qx, qy, qz, gx, gy, gz
```
Head-IMU stream from `CMHeadphoneMotionManager`: accel + gyro +
attitude quaternion + gravity vector. Currently logged only.

**Sessions index** (`data/sessions.csv` — **gitignored**, owned by
the running server, derivable from `data/raw/`):
```
session_id, person_id, description, start_time, end_time,
pen_samples, watch_samples, airpods_samples, status,
study_mode, protocol_id, subject_index
```
- `study_mode` ∈ {`free`, `study`, `test`}. `free` = legacy manual
  recording; `study` = run under a study protocol; `test` = study
  protocol run flagged not-for-analysis (pilot/dry-run).
- `protocol_id` — id of the protocol JSON in `study_protocols/` (e.g.
  `v1`); empty for `free` sessions.
- `subject_index` — 0-indexed counterbalancing index used to pick the
  Latin-Square row for this proband. Auto-assigned via
  `_subject_index_for_person_id(person_id)`, which **counts only prior
  sessions with `study_mode='study'`** for that person — `test` and
  `free` are skipped so pilot runs do not consume a counterbalance
  slot. The 6-row `LATIN_SQUARE_3` table in `src/server/study.py`
  defines all 6 permutations of the 3 writing tasks (full
  counterbalance — each task appears in each position twice across
  6 subjects).

Session IDs auto-increment (`S001`, `S002`, …). `_next_session_id()`
scans **sessions.csv** and `data/raw/{pen,watch,airpods}/` so an ID
can never be reused while a stale per-session CSV is still on disk.

`sessions.csv` was previously checked in but is **now gitignored**
after a data-loss incident where switching git branches reset it. The
server fully owns the file; any environment can reconstruct it by
scanning `data/raw/`.

**Markers CSV** (`data/raw/markers/{session_id}_markers.csv`): one
row per Study-Mode state transition or VL action. Schema:
```
local_ts, local_ts_ms, session_id, event, task_id, task_index,
task_label, category, duration_seconds, instance, note
```
Events include `study_start`, `task_start`, `task_end`, `pause_start`,
`pause_end`, `next`, `abort`, `study_end`. The marker stream is the
ground-truth timeline for downstream per-task analyses and lets the
training pipeline filter windows by task category if needed.

**Merged CSV** (`data/processed/{session}_merged.csv`): **watch-base**
— every watch sample is preserved, with `label_writing` ∈ {0, 1}
assigned from the nearest pen `dot_type` within ±40 ms of the
δ-corrected pen wall-clock. Watch samples in pen-gaps → label 0 (the
"not writing" negative class). Schema = all watch CSV columns +
`label_writing`. Server/local timestamps are capture metadata, not the
canonical ML timeline.

**Windows CSV** (`data/processed/{session}_windows.csv`): 1 row per
1 s sliding window (0.5 s stride), 42 statistical features + `label`
+ `t_center_ms`. Labels are smoothed at sample level before windowing
(see *Label smoothing* below).

## Study Mode

End-to-end protocol runner so recordings happen under a consistent,
counterbalanced script rather than free-form. Lives in
`src/server/study.py` (pure logic) + `src/server/routes/study.py`
(HTTP) + `static/js/pages/recording-study.js` (UI).

**Protocol definition.** `study_protocols/v1.json` defines tasks
(id, label, category ∈ {`writing`, `idle`}, duration, instances,
instruction, content_type ∈ {`text`, `list`, `image`}, content),
plus `pre_task_seconds`, `randomize`, and `interleave` mode.
`load_protocol(path)` validates against the Pydantic schema.

**Scheduler.** Three `interleave` modes are supported; v1 uses
`latin_square`: pick the Latin-Square row by `subject_index % 6` to
order the 3 writing tasks, then **interleave with pauses** between
them. v1's writing tasks are `abschreiben` (text copy),
`math` (math problems), `free_writing` — each 240 s — separated by
pause blocks. Net schedule: W-P-W-P-W (~15 min including pre-task
countdowns and audio cues).

**State machine.** `new_runtime(protocol, subject_index)` constructs
the ordered task list; `state.study` tracks `phase`,
`current_task_idx`, `task_started_ms`. `/study/next` advances,
`/study/pause` flips to/from `paused`, `/study/abort` terminates
and writes a `study_end` marker. Markers are written via
`write_marker()` (`csv_io.py`) on every transition.

**Test mode.** `POST /study/start` with `test_mode=true`:
- prefixes the description with `[TEST] `,
- writes `study_mode='test'` to sessions.csv,
- **skips Latin Square** (random shuffle fallback instead).
Existing sessions can be flipped retroactively via
`POST /sessions/{id}/mark-test` (the dashboard exposes this).

## Quality Checks

`/sessions/quality` returns separate `ml_readiness` and
`recording_health` scores. Issues come from `ISSUE_SPECS` in
`src/server/issues.py` (re-exported by `quality.py` for back-compat) —
each issue has `code`, `check`, `threshold`, `observed`, `rationale`,
plus `ml_severity` and `recording_severity`. Sync confidence is a
calibration diagnostic only — it must not downgrade a session by itself.

Notable issues:
- `data_outside_session_window` — fires when watch- or pen-CSV
  timestamps fall more than 60 s before `start_time` or after `end_time`.
  Catches stale CSVs being appended to a recycled session ID.
- `streams_do_not_overlap` — pen and watch wall-clock ranges don't
  overlap.
- `legacy_pen_time` / `legacy_watch_time` — old CSVs missing
  `local_ts_ms` / `server_received_ms`.
- `low_watch_coverage` — fewer rows than `~50 Hz × duration` (target
  defined by `_TARGET_WATCH_HZ`).
- `pen_clock_mismatch` — info-only; pen device clock is typically
  ~922 days behind wall clock.

**Sample-rate target:** the watch streams at 50 Hz
(`MotionManager.Config.requestedHz`). Quality check accepts 40–60 Hz.
If reconfigured, `_TARGET_WATCH_HZ` in `src/server/issues.py` is the
single place to update (likewise `_TARGET_AIRPODS_HZ` for the head
stream).

**Sample-level merge alignment:** pen and watch device clocks do not
share an epoch (typical Moleskine pen offset: ~922 days plus an
arbitrary time-of-day shift). Session-level overlap uses wall-clock
`local_ts_ms`. For sample-level merging the per-session offset δ is
recovered automatically by the **stroke-variance alignment** in
`src/alignment/pen_match.py` — a port of the TH Zürich algorithm
(see `data/02_Pen_IMU_Timestamp_Alignment.pdf`). Physical assumption:
while the pen is on paper, the wrist holding the watch is comparatively
still, so the correct δ minimizes the mean watch-acceleration variance
under the shifted stroke mask. The search runs coarse (±20 s @ 0.5 s)
then fine (±5 s @ 10 ms); confidence is reported as
`sigma_minimal_variance` (z-score of the minimum vs the search-grid
distribution — more negative = stronger). `merge_watch_pen()` applies
δ to `pen.local_ts_ms` before the `merge_asof` join and skips the
shift when `sigma > -2`. This replaced the planned tap-sync recording
protocol — no special user action at session start is required.

## ML pipeline gotchas

**Label smoothing (morphological closing).** The pen reports DOWN/MOVE
only while in contact / near the paper. Between letters, across word
boundaries and during short denkpausen there are 50 ms–2 s gaps where
the pen is briefly lifted — the writer is still in *writing mode* but
the raw pen label flips to 0, and the watch IMU during those gaps
looks identical to the surrounding strokes. Without smoothing the
model sees the same wrist motion with contradictory labels and learns
ambivalence. **Chosen closing (headline pipeline):** `max_gap_ms=2500` —
idle runs ≤ 2.5 s between writing runs are flipped to writing. (Code-
Default in `build_windows()` ist historisch noch `300`; Headline-
Runs werden mit explizitem `--max-gap-ms 2500` gefahren bis der
Default geflippt wird.) Semantik: damit detektiert das Modell "Person
ist im Schreibmodus" (inkl. Mikropausen ≤ 2.5 s) und nicht "Pen
aktuell auf Papier". Für einen Schreibzeit-Tracker ist das die
User-facing-Wahrheit.

LOSO-Ablation auf N=7 (2026-05-18): Headline gap=2000 → 2500 hob
acc 0.864 → 0.868 (+0.4 pp), AUC 0.940 → 0.943 (+0.3 pp), F1(w)
0.875 → 0.885 (+1.0 pp). 6 von 7 Folds verbesserten sich, P02/P03
marginal regrediert (≤0.7 pp). Wichtig: P05 (neue, schwächste Fold)
profitierte (acc 0.816 → 0.825, FP 307 → 295) — was die Hypothese
aus der Marker-Analyse stützt, dass P05's lange Denkpausen in der
math-Task länger als 2 s sind. Gap=3000 testete noch +0.2 pp F1,
aber P05 regredierte (acc 0.802, FP 340) weil Fidgeting in geplanten
Pausen ≥ 2.5 s fälschlich als writing geschluckt wird — und σ-acc
sprang von 0.026 auf 0.035. `2500` ist die letzte Stelle mit
near-universellem Per-Fold-Gewinn und σ-Tightening. Vorgänger-Switch
auf N=5 von gap=300 → 2000 hatte +4.2 pp acc gebracht; bei N=7 ist
das Plateau erreicht — weitere Smoothing-Gains brauchen entweder
Features (z. B. „still sitting" Detektor) oder Threshold-Tuning.

N=8 (2026-05-18, +P07/S019): Headline-Acc fällt 0.868 → 0.861, AUC
0.943 → 0.932, σ wächst 0.024 → 0.035 — komplett von P07-Fold
getrieben (acc 0.808, AUC 0.848). Per-Block-Diagnose: P07 versagt
*ausschließlich* im Math-Block (acc 0.578, 96 FPs, 61 FNs), während
abschreiben/free_writing/pause sauber sind (acc 0.83–0.96). Sample-
Level am `S019_merged.csv`: P07 hat in 225 s Math-Block nur **22 s
echte Pen-Zeit (10 %)**; 6 Idle-Stretches > 10 s (längste 22 s),
die `max_gap_ms=2500` strukturell nicht schließen kann. **30 s-Burst-
AUC für P07 erholt sich auf 0.932** — Modell trifft Phasen, nur nicht
einzelne Sekunden. Nebenbefund: 3 FP-Bursts in Pause 2 (+8 s, +49 s,
+74 s) korrespondieren mit Noah's in-room Beobachtung dass P07 in der
Pause aufs Handy getippt hat — Phone-Typing als echter Wrist-Confound,
für Protokoll v2 dokumentiert.

N=10 (2026-05-19, +P08/S020, +P09/S022): Headline-Acc 0.861 → 0.856,
AUC 0.932 → 0.928, F1(w) 0.879 → 0.864 — **alle Bewegungen innerhalb
σ-fold, σ tightens sogar 0.035 → 0.032 trotz +2 Folds**, Modell
stabilisiert sich mit N. **P08-Math widerlegt die N=8-These "Math
ist strukturell schwer":** P08 hat in Math 26 % Pen-Zeit (ähnlich
niedrig wie P07's 10 %), erreicht aber acc 0.843 / AUC 0.942 im
Math-Block. Math-Schwierigkeit war **P07-individuell** (lange
Denkpausen + fidgety hands), nicht task-inhärent — die N=8-Diagnose
"strukturelle Limitation" ist insofern zu stark formuliert. **P09 ist
neue Fehlerklasse** (acc 0.812, AUC 0.896): Pausen exzellent
(acc 0.92–0.96), aber beide Writing-Tasks symmetrisch schwach
(Free 0.791 / AUC 0.843, Abschreiben 0.782 / AUC 0.844).
Abschreiben-Pen-Zeit nur **58 % (Norm 75–80 %)** — Soft-Writer-Stil
mit langen Mikropausen *innerhalb* der Schreibphasen. Anders als P07:
**Burst-Aggregation @30 s verschlechtert P09** (acc 0.812 → 0.782,
AUC 0.896 → 0.851) statt zu helfen — die einzige Fold im Datensatz
mit @30 s < @1 s AUC. Erklärung: P09's Fehler sind zeitlich
geclustert, nicht verrauscht — längere Decision-Windows mitteln
korrekte Predictions weg statt Noise zu glätten. → **Zwei distinkte
Failure-Modi** im Datensatz mit unterschiedlichen Lösungswegen:
P07-Klasse (high-frequency Noise) braucht task-aware Labeling oder
profitiert from Burst-Aggregation; P09-Klasse (systematische Soft-
Writer-Confusion) braucht Per-Subject-Threshold oder weichere
Pen-Truth-Definition.

Opening (`max_spike_ms`) ist implementiert aber bleibt off; flipping
short writing spikes hurt S029 — real quick strokes (i-dots,
punctuation) sind kurz und informativ.

**Smoothing lives in the feature step, not the merge.** The merged
CSV is intentionally the "raw pen truth" — smoothing is a feature-
engineering hypothesis and must remain reversible. Anyone wanting the
unsmoothed labels can call `build_windows(..., max_gap_ms=0)` or read
`label_writing` directly from `{session}_merged.csv`.

**Marker-driven per-task error analysis.** Seit Study Mode v1 schreibt
jeder Run einen `data/raw/markers/{session}_markers.csv` mit allen
Task-Übergängen (Schreib-Tasks vs. geplante Pausen). Beim Diagnose
von LOSO-Fehlern ist das die wichtigste Cross-Reference: man kann
jedes Test-Window über `t_center_ms` auf die laufende Task mappen
und FP/FN-Cluster getrennt nach `writing`- vs. `idle`-Kategorie
analysieren. Beispiel-Insight aus dem 2026-05-17-Taji-Fold: die
meisten FPs lagen *nicht* in den geplanten Pausen (Pause-FPR=0.01,
nahezu perfekt), sondern an Pen-Lift-Mikropausen innerhalb der
Schreib-Tasks — was die Hypothese „Pen-Truth ist zu hart" stützte
und letztlich zum `max_gap_ms`-Switch geführt hat. Wenn neue
LOSO-Folds verschlechtert wirken: erst Markers über die Predictions
legen, bevor Modell- oder Feature-Änderungen angefasst werden.

**Session length minimum.** Within-session 80/20 temporal splits need
enough windows that both train and test see both classes. Empirically:
sessions < 5 min (< 100 windows) produce unreliable / nonsense metrics
because bursty writing-periods fall entirely on one side of the split
(seen on S027: train `[51 idle, 3 writing]`, test `[4 idle, 11 writing]`
→ accuracy 0.27, ROC-AUC 0.47). **Aim for ≥ 5 min** with a natural mix
of writing and idle for any session that should contribute to ML
metrics.

**Alignment confidence as ML gate.** The current merge applies δ when
`σ ≤ -2`, but that threshold is too loose for ML — borderline σ values
(-2.0 to -2.5) sometimes find spurious local minima at large δ
(seen on S011/S027: δ = 16–18 s, ROC-AUC 0.36/0.47). For training data
the practical filter is **σ ≤ -3** (S028: -3.30, S029: -5.27). Lower
confidence sessions are still valid for data collection (the pen logs
remain useful raw material), they just shouldn't be fed into the
trainer without manual review of the alignment plot.

**Temporal split, not random** (within-session only). Sliding windows
overlap by 50% (stride 0.5 s, window 1 s). Random splits leak adjacent
windows across train/test → inflated metrics that collapse in
deployment. `within_session.train_rf.temporal_split()` enforces a
4-window gap at the cut. **LOSO via `train_loso.py` is the stronger
guarantee** — the held-out subject/session was never in training, so
window overlap across the cut is impossible by construction. Use
within-session as a fast sanity check during development; LOSO is the
metric that maps to the deployment scenario.

**Feature-Window vs. Decision-Window.** The 1 s sliding window is the
*feature* window (right size for FFT bandwidth + crisp temporal
resolution), but is **not** the right size to report user-facing
accuracy on. `train_loso.py` therefore reports the same fold on four
*decision* scales (1 s / 5 s / 10 s / 30 s) by smoothing the model's
1-s probabilities per-session before re-thresholding. The
per-1-s number stays in the output as the model-quality metric, but
the 10–30 s burst numbers are what matches a typical use-case
(Schreibzeit-tracker, phase detection). Do not silently switch to the
larger scale — always report all four with the decision-window
explicitly named.

**Two training entry points, two purposes.**
- `python -m src.training.within_session.train_rf S029` — fast
  iteration on features/label-smoothing parameters on a single
  session. **Not a generalisation claim.** Use during development.
- `python -m src.training.train_loso [--by person|session]` —
  Leave-One-Out cross-validation. **Headline metric.** Use to validate
  the model and to report results. With `--save-final-model` it
  additionally re-trains on all data and dumps the deployment model
  to `models/rf_all.joblib`; `--save-cv-csv` writes per-fold metrics
  to `models/loso_cv.csv` for tracking across data-collection rounds.

**Per-session z-score, briefly.** The hardest cross-subject problem
isn't "what feature distinguishes writing" — it's that the same
gesture produces different absolute feature values on different
wrists. Per-session standardization removes the absolute-scale
component while preserving the relative structure within a session.
Lives in `_zscore_per_session()` in `train_loso.py` (and a copy in
`compare_models.py`). Caveat for deployment:
production needs a calibration phase (or rolling stats) to estimate
μ, σ from the live stream before the model can be applied.

**Negative result: catch22 + DWT-Energy features.** Tried adding the
22-feature catch22 bank (`pycatch22`) and DWT-Energy coefficients
(`pywt`, db4 wavelet) per axis on top of the 88 engineered features.
At N=3 probands, no systematic gain (Δacc ≈ ±0.003) and fold-σ
roughly doubled — classic overfitting signature when feature count
grows but data doesn't. Recorded in `reports/model_progression.md`.
Worth re-trying at N≥5.

## Testing

`tests/` holds Tier-1 smoke tests (138 cases, ~1.5 s) — anything that
could silently poison the training data or the proband-facing flow:

- `test_quality.py` — synthetic CSVs feeding into `_session_facts`;
  asserts which issue codes fire. Includes a regression for the
  stale-CSV-window bug.
- `test_session_id.py` — `_next_session_id` skips IDs with stale
  pen/watch/airpods files.
- `test_merge.py` — `merge_watch_pen` watch-base behaviour (every
  watch sample preserved; label 1 only when pen DOWN/MOVE within
  tolerance; pre/post idle stretches labelled 0), plus
  `prepare_pen_data` `label_writing` mapping and x=-1 filtering.
- `test_pen_match.py` — stroke-variance alignment in
  `src/alignment/pen_match.py`: stroke-mask construction, coarse/fine
  search behaviour, sigma confidence.
- `test_pen_parser_framing.py` — STX/ETX/DLE-escape state machine
  in `pen_logger.py`.
- `test_endpoints.py` — FastAPI TestClient smokes for `POST /watch`
  (both payload formats), `POST /session/start` → `/stop` happy path,
  and the `streams_do_not_overlap` validation issue.
- `test_protocol_loader.py` — `load_protocol` schema validation
  (extra fields rejected, durations positive, content_type matches
  content, etc.).
- `test_study_scheduler.py` — Latin-Square ordering, writing/pause
  interleave, `pre_task_seconds`, randomize fallback.
- `test_study_state_machine.py` — runtime transitions
  (idle → running → paused → running → done), pause/abort semantics.
- `test_study_endpoints.py` — HTTP layer for `/study/*`.
- `test_study_e2e.py` — full start → next → next → abort smoke,
  asserts markers CSV contents and sessions.csv columns.
- `test_subject_index.py` — `_subject_index_for_person_id` counts
  only `study_mode='study'` sessions, ignores `test` and `free`.
- `test_markers_csv.py` — `write_marker` schema + append behaviour.
- `test_sessions_schema.py` — sessions.csv carries the new
  `study_mode` / `protocol_id` / `subject_index` columns; the schema
  is migrated forward on read.
- `test_sync.py` / `test_timelines.py` — previously-untested server
  helpers (sync-confidence, per-session timeline reconstruction).
- `test_chart_aggregation.py` — 5 Hz chart aggregator.
- `test_dashboard_static.py` — every JS module / view partial /
  stylesheet path returns 200 (404 trap; ES modules fail opaquely
  when served as `text/html`).

Hardware loops (real BLE pen, watchOS app, iPhone bridge) remain
**manual** smoke tests — there is no XCTest target in the Xcode
project and BLE scan/connect cannot be exercised without a device.

## Path Convention

All Python modules resolve data paths relative to the project root:
```python
ROOT = Path(__file__).parents[N]
ROOT / "data"
```
Do not hard-code absolute paths.

## Working with this repo

- Prefer editing existing files; don't add new docs unless asked.
- Default to no comments in code — only add `# Why:` lines for
  non-obvious constraints, hidden invariants, or workarounds.
- When changing the quality engine, add a corresponding test fixture
  in `tests/test_quality.py` with the synthetic CSV that triggers it.
- When changing pen/watch CSV schemas, update `PEN_FIELDNAMES` /
  `WATCH_FIELDNAMES` in `src/server/config.py` (the canonical source)
  and re-run `pytest tests/`.
- Processed data (`data/processed/`) is gitignored and regenerated by
  the training pipeline.
