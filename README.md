# Writing Activity Detection via Apple Watch IMU

[![tests](https://github.com/noahsa16/ML4SCS_Burk_macht_Bock/actions/workflows/test.yml/badge.svg)](https://github.com/noahsa16/ML4SCS_Burk_macht_Bock/actions/workflows/test.yml)

**Semester project · Machine Learning for Smart and Connected Systems**  
Team: Noah Samel · Ben Kriegsmann · Tajuddin Snasni

(Picture to be added after next seminar)

---

## Research Question

> Can writing activity be detected and predicted from IMU data (accelerometer + gyroscope) of an Apple Watch?

The Moleskine Smart Pen acts as ground truth during data collection: its stroke events label each watch sample in time. Once the model is trained, the pen is no longer needed — inference runs on watch data alone.

---

## How it works

```
Apple Watch (IMU)
  └─ WatchConnectivity ──► iPhone Bridge ──► POST /watch    ──► server.py
                                                                     │
AirPods (head-IMU)                                                   │
  └─ CMHeadphoneMotionManager ─► iPhone ──► POST /airpods ──► server.py
                                                                     │
Moleskine Smart Pen (BLE)                                            │
  └─ pen_logger.py ──────────────────────────────────────────────────┘
                                                                     │
                                            data/raw/watch/{session}_watch.csv
                                            data/raw/pen/{session}_pen.csv
                                            data/raw/airpods/{session}_airpods.csv
                                                                     │
                                  src/alignment/pen_match.py   (recover δ)
                                  src/merge/                   (watch-base, ±40 ms)
                                                                     │
                                  data/processed/{session}_merged.csv
                                                                     │
                                  src/features/   (1 s windows, 0.5 s stride,
                                                   42 stats + label smoothing)
                                                                     │
                                  data/processed/{session}_windows.csv
                                                                     │
                                  src/training/train_rf.py     (RF baseline,
                                                                temporal 80/20 split)
                                                                     │
                                  models/rf_{session}.joblib
```

---

## Screenshots

### Dashboard (Web)

The session dashboard runs at `http://localhost:8000` and gives a real-time view of both sensors, session management, and data quality.

**Session overview & live sensor status**

![Dashboard – Session Control](docs/screenshots/dashboard.png)

---

### iPhone App

The iPhone app bridges Watch ↔ Server: it receives IMU batches via WatchConnectivity and forwards them as HTTP POSTs. It also relays start/stop commands from the server to the Watch.

![iPhone App](docs/screenshots/iphone_app.png)

---

### Apple Watch App

The Watch app captures `CMDeviceMotion` at 50 Hz and streams batches of 10 samples to the iPhone bridge via WatchConnectivity. The UI shows session state, sample rate, and connection status.

![Watch App](docs/screenshots/watch_app.png)



## Hardware

| Device | Role | Data |
|--------|------|------|
| Apple Watch (Series 6+) | Model input | Accelerometer + Gyroscope @ 50 Hz |
| AirPods (Pro / 3rd Gen) | Auxiliary input | Head IMU (accel + gyro + attitude) via `CMHeadphoneMotionManager` |
| Moleskine Smart Pen NWP-F130 | Ground truth | x/y/pressure/dot_type via BLE |

---

## Project Structure

```
server.py                        FastAPI entry point (thin, ~50 lines)
pen_logger.py                    BLE logger for the Moleskine Smart Pen
dashboard.html                   ~88-line shell (head, slots, modulepreload)
static/dashboard.js              Bootstrap: lazy-mounts page partials,
                                 owns hash routing + active-page WS dispatch
static/js/core/                  Cross-cutting modules
  state.js                         S object + named getters/mutators
  ws.js                            WebSocket connection + reconnect
  status_cluster.js                Topbar status + handleStatus dispatcher
  router.js                        Hash routing, tab indicator, page strip
  api.js, dom.js, format.js        Pure helpers (fetch, esc, formatters)
  theme.js, anim.js, toast.js      Leaf services
static/js/pages/                 Per-page modules (mount/onStatus/onShow/onHide)
  recording.js, sessions.js,
  session_detail.js, connections.js,
  system.js, settings.js           WS ticks dispatched only to active page
static/views/*.html              View partials fetched once + cached
                                 (recording / sessions / session-detail /
                                  settings / …)
static/css/                      Per-page + base + topbar stylesheets

src/pen_schema.py                Shared pen-CSV schema (no deps;
                                 imported by pen_logger.py and server)

src/server/                      Modular server package
  config.py                        Paths, field names, logs/ dir
  state.py                         In-memory session state
  utils.py                         Pure helper functions
  logging_setup.py                 File + stream + event-log handlers
  csv_io.py                        CSV read/write (pen + watch + airpods),
                                   live-preview tail
  status.py                        Connection checks + status payload
  issues.py                        ISSUE_SPECS table + sample-rate targets
                                   (single source of truth)
  sync.py                          Sync-confidence helpers
  timelines.py                     Per-session timeline reconstruction
  quality.py                       Session quality, validation, report
  models.py                        Pydantic request/response models
  broadcast.py                     WebSocket broadcast + 1-s status loop
  pen_proc.py                      Pen logger subprocess management
  routes/                          One APIRouter per concern
    watch.py, airpods.py, pen.py,
    sessions.py, dashboard.py, ws.py,
    _helpers.py                    aggregated in __init__.py

src/alignment/
  pen_match.py                     Stroke-variance pen↔IMU clock-offset
                                   recovery (TH Zürich algorithm)
src/merge/
  prep.py                          Per-stream cleaning helpers
  merge.py                         merge_watch_pen() — watch-base ±40 ms
                                   asof join, δ-shifted when σ ≤ -2
  __main__.py                      CLI: python -m src.merge [SESSION_ID]
src/features/
  windows.py                       Sample-level label closing
                                   (max_gap_ms) + 1 s sliding windows
                                   @ 0.5 s stride → 42 stat features
  __main__.py                      CLI: python -m src.features [SESSION_ID]
src/training/
  train_rf.py                      RandomForest baseline; temporal 80/20
                                   split with 4-window gap at the cut
src/evaluation/evaluate.py         Label distribution (real metrics live in
                                   train_rf.py for now)

scripts/
  start.sh                         Server + Cloudflare tunnel TTY UI
  tunnel.sh                        Standalone Cloudflare quick tunnel
  test_server.sh                   POST a synthetic batch to /watch
  plot_alignment.py                Render the 4-panel alignment figure
  plot_merged.py                   Visualize ‖acc‖, ‖gyro‖ + label_writing
                                   over a session (preview label smoothing)
  backfill_session_quality.py      Rewrite sessions.csv quality columns
                                   from current ISSUE_SPECS

tests/                             Tier-1 smoke tests (~30 cases, <1 s)
  test_quality.py                    Quality engine + ISSUE_SPECS regressions
  test_merge.py                      Watch-base merge behaviour
  test_pen_match.py                  Stroke-variance alignment
  test_session_id.py                 _next_session_id stale-file safety
  test_pen_parser_framing.py         STX/ETX/DLE state machine
  test_endpoints.py                  FastAPI TestClient happy paths
  test_chart_aggregation.py          5 Hz chart aggregator
  test_dashboard_static.py           Every static asset reachable (404 trap)

watch_streamer/
  WatchStreamer Watch App/
    MotionManager.swift            IMU capture + WatchConnectivity send
    WatchView_v2.swift             Watch UI
  WatchStreamer/
    PhoneBridge.swift              WatchConnectivity → HTTP bridge
    iPhoneView_v4.swift            iPhone UI
    ServerCommandListener.swift    Listens for start/stop over WebSocket

data/
  raw/pen/{session}_pen.csv        Raw pen dots per session
  raw/watch/{session}_watch.csv    Raw IMU samples per session
  raw/airpods/{session}_airpods.csv  Raw head-IMU per session
  sessions.csv                     Session index
  processed/                       Merged + windowed datasets (gitignored)

models/                            Trained RF baselines (rf_{session}.joblib)
notebooks/                         Exploration notebooks
reports/                           Weekly progress reports
results/plots/                     Generated figures (alignment, etc.)
docs/
  screenshots/                     Dashboard + app screenshots
  superpowers/                     Internal design specs, plans, audits
```

---

## Setup

```bash
pip install -r requirements.txt
```

---

## Running the Stack

**1. Start the server:**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000` — the dashboard loads automatically.

**2. Open the iPhone app** — enter the server IP, tap *Connect*.

**3. Start a session** from the dashboard — both pen logger and watch start automatically.

**4. Record data** — write something, pause, write again.

**5. Stop the session** — CSVs are finalized.

**6. Check quality** — dashboard Sessions page shows `ml_readiness` and `recording_health` per session. The **⤓ md** link in each row downloads a self-explaining Markdown report listing every issue with its check, threshold, observed value, and rationale (`GET /sessions/{id}/report?format=md`).

Server logs go to the terminal *and* `logs/server.log` (rotating). The same log lines also show up in the dashboard's event log panel — useful when debugging connection drops or rate spikes.

---

## ML Pipeline

Once a session is recorded, the full training pipeline is three commands:

```bash
python -m src.merge S029                      # watch-base merge → data/processed/S029_merged.csv
python -m src.features S029 --max-gap-ms 300  # sliding windows  → data/processed/S029_windows.csv
python -m src.training.train_rf S029          # RF baseline      → models/rf_S029.joblib
```

Without a session ID, `merge` and `features` operate on the most recent session. `train_rf` prints classification report, confusion matrix, ROC-AUC and the top-10 feature importances on the temporal hold-out.

To preview the effect of label smoothing visually before training:
```bash
python scripts/plot_merged.py S029 --max-gap-ms 300
```

Run smoke tests:
```bash
pytest tests/     # ~30 cases, <1 s
```

---

## Data Formats

**Watch CSV** — one row per IMU sample:
```
local_ts, local_ts_ms, session_id, sequence, sample_rate_hz,
watch_sent_at, phone_received_at, server_received_ms, source,
ts, ax, ay, az, rx, ry, rz
```
`ts` is the canonical device timestamp (Watch's own clock, milliseconds). `ax/ay/az` = accelerometer, `rx/ry/rz` = gyroscope.

**Pen CSV** — one row per dot event:
```
local_ts, local_ts_ms, timestamp, x, y, pressure, dot_type,
tilt_x, tilt_y, section, owner, note, page
```
`dot_type` values: `PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER`.  
Label derivation: `label_writing = 1` if `dot_type ∈ {PEN_DOWN, PEN_MOVE}`, else `0`.

**AirPods CSV** — one row per head-IMU sample:
```
local_ts, local_ts_ms, session_id, sequence, sample_rate_hz,
airpods_sent_at, phone_received_at, server_received_ms, source,
ts, ax, ay, az, rx, ry, rz, qw, qx, qy, qz, gx, gy, gz
```
Accel + gyro + attitude quaternion (`qw/qx/qy/qz`) + gravity vector (`gx/gy/gz`).

**Merged CSV** (`data/processed/{session}_merged.csv`) — **watch-base**: one row per watch sample, with `label_writing ∈ {0, 1}` derived from the nearest pen `dot_type` within ±40 ms of the δ-corrected pen wall-clock. Watch samples in pen-gaps → label `0` (the negative class for binary classification). Schema = all watch CSV columns + `label_writing`.

**Windows CSV** (`data/processed/{session}_windows.csv`) — one row per 1 s sliding window (0.5 s stride) with 42 statistical features (mean/std/min/max/rms/range per axis + accel/gyro magnitude mean/std/energy), plus `label`, `t_center_ms`. Labels are smoothed at sample level (morphological closing, default 300 ms gap-fill) before windowing.

---

## Pen ↔ IMU Time Alignment

Pen and watch device clocks do not share an epoch. The Moleskine pen's hardware clock typically lands ~922 days off plus an arbitrary time-of-day shift, so a naïve wall-clock join would smear the labels by hundreds of milliseconds (or worse).

We recover the per-session offset **δ** automatically using a **stroke-window variance-minimization** approach — a port of the TH Zürich method described in [`data/02_Pen_IMU_Timestamp_Alignment.pdf`](data/02_Pen_IMU_Timestamp_Alignment.pdf), implemented in [`src/alignment/pen_match.py`](src/alignment/pen_match.py).

**Idea.** While the pen is on paper, the wrist holding the watch is comparatively still — strokes are short and constrained. The correct δ shifts the stroke mask onto the calmest portions of the IMU signal, so the right δ shows up as a clear minimum of the mean accelerometer variance under the shifted mask.

```
                δ wrong                                δ correct
       ┌────────────────────┐                  ┌────────────────────┐
 acc   │   ╱╲   ╱╲    ╱╲    │            acc   │       ___      __  │
 var   │  ╱  ╲ ╱  ╲  ╱  ╲   │            var   │ ___ ╱   ╲ ___ ╱  ╲ │
       │ ╱    V    ╲╱    ╲  │                  │╱   ╲    │   ╲    │ │
       └─▲─────▲────▲─────▲─┘                  └─▲────▲────▲────▲──┘
         strokes overlap motion                  strokes sit on quiet IMU
```

**Search.** Coarse pass (±20 s @ 0.5 s) handles BLE buffering and clock drift; fine pass (±5 s @ 10 ms) refines around the coarse minimum. Confidence is reported as `sigma_minimal_variance` — a z-score of the minimum vs the search-grid distribution. More negative = stronger alignment.

**Wiring.** `merge_watch_pen()` calls `match_pen_data()`, applies δ to `pen.local_ts_ms`, then runs a **watch-base** `merge_asof` within ±40 ms — every watch sample is preserved and gets `label_writing = 1` iff the nearest pen `dot_type` is `PEN_DOWN`/`PEN_MOVE` within tolerance, else `0`. When the signal is weak (`sigma > -2`) the δ shift is skipped and the quality engine surfaces a `low_sync_confidence` (warn) or `sync_failed` (bad) issue. For ML training the practical filter is stricter: **σ ≤ -3** (borderline σ values around -2 sometimes find spurious local minima).

This replaced an earlier plan to require a tap-sync recording protocol (3× tap with the watch hand at session start). Subjects no longer have to do anything special — alignment is fully post-hoc.

---

## Quality Checks

Each session is scored against a fixed set of checks defined in `quality.py`. Every issue carries `code`, `check`, `threshold`, `observed`, and a short `rationale` so it's clear *why* a warning fired and what the assumption behind it was — useful when deciding whether the threshold itself needs adjusting.

| Check | Target |
|-------|--------|
| Watch has accelerometer (`ax/ay/az`) | Required |
| Watch has gyroscope (`rx/ry/rz`) | Required |
| Watch sample rate | 40–60 Hz (target: 50 Hz) |
| Pen CSV has `local_ts_ms` | Required for wall-clock anchor |
| No sequence gaps in watch batches | Recommended |
| Pen dots fall within watch time range | ≥ 80 % |
| `PEN_DOWN` / `PEN_UP` paired | Diagnostic |

Two scores are exposed separately: `ml_readiness` (does this session contain usable training material?) and `recording_health` (did the hardware behave during capture?). Sync confidence is reported as a diagnostic only and never downgrades a session score on its own.

The full per-session report is available as JSON at `GET /sessions/{id}/report` or as Markdown at `GET /sessions/{id}/report?format=md`.

Sync confidence (`sigma_minimal_variance`) is reported as a diagnostic alongside the scores. The pen↔IMU clock offset itself is recovered automatically per session — see [Pen ↔ IMU Time Alignment](#pen--imu-time-alignment) above.

---

## Current Status

| Phase | Status |
|-------|--------|
| Data collection | Operational |
| Preprocessing & merging | Implemented (watch-base, ±40 ms) |
| Pen↔IMU clock alignment | Implemented (stroke-variance, TH Zürich) |
| Feature engineering | Implemented (1 s windows, 42 stats, label closing) |
| Model training | Implemented (Random Forest baseline) |
| Evaluation & metrics | Within-session: S029 acc 0.83 / ROC-AUC 0.85 |
| Multi-session / cross-subject evaluation | TODO |

---

## Weekly Reports

- [Week 3](reports/week03.md)
- [Week 4](reports/week_04_report.md)
- [Week 5](reports/week_05_report.md)
