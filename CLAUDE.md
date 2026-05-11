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
checks + sliding-window features + Random Forest baseline are
operational. Multi-session / cross-subject evaluation is TODO.

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
./scripts/test_server.sh [IP]    # defaults to 127.0.0.1
```

**Convenience scripts:**
- `scripts/start.sh` — boots the server and (optionally) a Cloudflare
  tunnel in one TTY UI; Ctrl+C cleans up both.
- `scripts/tunnel.sh` — standalone Cloudflare quick tunnel
  (`https://*.trycloudflare.com → localhost:8000`).
- `scripts/plot_alignment.py` — runs the pen↔IMU alignment for a
  session and renders the explanatory 4-panel figure (top: variance
  with stroke overlay raw vs δ-shifted; bottom: J(δ) coarse + fine).

**Merge / features / train / evaluate (full ML pipeline):**
```bash
python -m src.merge S029                          # watch-base merge → data/processed/S029_merged.csv
python -m src.features S029 --max-gap-ms 300      # sliding-window features → data/processed/S029_windows.csv
python -m src.training.train_rf S029              # RF baseline → models/rf_S029.joblib + metrics
python -m src.evaluation.evaluate S029            # placeholder, prints label distribution
python scripts/plot_merged.py S029 --max-gap-ms 300   # visualize IMU + label overlay
```
Without args, `src.merge` / `src.features` operate on the most recent session.

**Run smoke tests:**
```bash
pytest tests/         # ~30 tests, <1 s
```

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
                                      stroke-variance minimization)
       src/merge/                    (watch-base: 1 row per watch
                                      sample with label_writing from
                                      pen activity in ±40 ms)
                    ↓
         data/processed/{session}_merged.csv  (50 Hz watch + label)
                    ↓
       src/features/                 (sample-level label smoothing
                                      via morphological closing, then
                                      1 s / 0.5 s sliding windows →
                                      42 stat features per window)
                    ↓
         data/processed/{session}_windows.csv  (1 row per window)
                    ↓
       src/training/train_rf.py      (temporal 80/20 split, RF)
                    ↓
         models/rf_{session}.joblib  +  metrics on stdout
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
routes/            FastAPI endpoint package — one APIRouter per concern
                   (watch.py, airpods.py, pen.py, sessions.py,
                    dashboard.py, ws.py, _helpers.py); __init__.py
                    aggregates them into a single `router`
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
- `WebSocket /ws` — dashboard status (1 s tick) + iPhone bridge messages

`_status_loop` broadcasts `_status_payload()` once a second, updates
rolling Hz estimates, and maintains a 60-point rolling chart buffer
(acc magnitude, gyro magnitude, pen writing state).

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
  0.5 s stride → 42 stat features per window (mean/std/min/max/rms/range
  per axis + accel/gyro magnitude mean/std/energy). Window label = 1
  iff ≥ 60% of samples in the window have `label_writing == 1`.
  Optional opening (`--max-spike-ms`) is implemented but defaults off —
  empirically didn't help on S029.
- `src/features/__main__.py` — CLI: `python -m src.features [SESSION_ID]
  [--max-gap-ms 300] [--max-spike-ms 0]`, writes
  `data/processed/{session}_windows.csv`.
- `src/training/train_rf.py` — `RandomForestClassifier` (200 trees,
  `class_weight="balanced"`). **Temporal** train/test split (80/20 by
  `t_center_ms`, with a 4-window gap at the cut to prevent overlap
  leakage — adjacent windows share 50% of samples). Loads cached
  `{session}_windows.csv` if present, else builds on the fly. Prints
  classification report, confusion matrix, ROC-AUC, top-10 feature
  importances; dumps to `models/rf_{session}.joblib`.
- `src/evaluation/evaluate.py` — placeholder that loads
  `{session}_merged.csv` and prints label distribution. Real metrics
  live in `train_rf.py` for now.
- `scripts/plot_merged.py` — visualizes ‖acc‖, ‖gyro‖, and
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

**Sessions index** (`data/sessions.csv`):
```
session_id, person_id, description, start_time, end_time,
pen_samples, watch_samples, airpods_samples, status
```
Session IDs auto-increment (`S001`, `S002`, …). `_next_session_id()`
scans **sessions.csv** and `data/raw/{pen,watch,airpods}/` so an ID
can never be reused while a stale per-session CSV is still on disk.

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
only while in contact / near the paper. Between letters and across word
boundaries there are 50–300 ms gaps where the pen is briefly lifted —
the writer is still in *writing mode* but the raw pen label flips to 0,
and the watch IMU during those gaps looks identical to the surrounding
strokes. Without smoothing the model sees the same wrist motion with
contradictory labels and learns ambivalence. **Default closing:**
`max_gap_ms=300` in `build_windows()` — idle runs ≤ 300 ms between
writing runs are flipped to writing. Empirically lifted within-session
test accuracy on S029 from 0.66 → 0.83 and ROC-AUC from 0.75 → 0.85.
Opening (`max_spike_ms`) is implemented but defaults off; flipping
short writing spikes hurt S029 because real quick strokes (i-dots,
punctuation) are short and informative.

**Smoothing lives in the feature step, not the merge.** The merged
CSV is intentionally the "raw pen truth" — smoothing is a feature-
engineering hypothesis and must remain reversible. Anyone wanting the
unsmoothed labels can call `build_windows(..., max_gap_ms=0)` or read
`label_writing` directly from `{session}_merged.csv`.

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

**Temporal split, not random.** Sliding windows overlap by 50%
(stride 0.5 s, window 1 s). Random splits leak adjacent windows
across train/test → inflated metrics that collapse in deployment.
`train_rf.temporal_split()` enforces a 4-window gap at the cut.

## Testing

`tests/` holds Tier-1 smoke tests — anything that could silently
poison the training data:

- `test_quality.py` — synthetic CSVs feeding into `_session_facts`;
  asserts which issue codes fire. Includes a regression for the
  stale-CSV-window bug.
- `test_session_id.py` — `_next_session_id` skips IDs with stale
  pen/watch/airpods files.
- `test_merge.py` — `merge_watch_pen` watch-base behaviour (every
  watch sample preserved; label 1 only when pen DOWN/MOVE within
  tolerance; pre/post idle stretches labelled 0), plus `prepare_pen_data`
  `label_writing` mapping and x=-1 filtering.
- `test_pen_match.py` — stroke-variance alignment in
  `src/alignment/pen_match.py`: stroke-mask construction, coarse/fine
  search behaviour, sigma confidence.
- `test_pen_parser_framing.py` — STX/ETX/DLE-escape state machine
  in `pen_logger.py` (does not cover packet semantics — that needs
  real BLE captures).
- `test_endpoints.py` — FastAPI TestClient smokes for `POST /watch`
  (both payload formats), `POST /session/start` → `/stop` happy path,
  and the `streams_do_not_overlap` validation issue.

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
