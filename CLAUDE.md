# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

ML4SCS (Machine Learning for Smart and Connected Systems) — semester
project by Noah Samel, Ben Kriegsmann, and Tajuddin Snasni. Goal: a
model that predicts writing activity (and eventually concentration) of
elementary-school children from **Apple Watch IMU data alone**.

The Moleskine Smart Pen is used **only during data collection** as
ground truth: pen stroke events (`dot_type`) label the watch samples at
the matching timestamp. Once trained, the pen is no longer needed —
inference runs on the watch.

Two sensors during training-data collection:
- **Moleskine Smart Pen (NWP-F130)** — ground truth; x/y, pressure,
  tilt at ~80–90 Hz over BLE.
- **Apple Watch (Series 7)** — model input; accelerometer + gyroscope
  at 50 Hz via CoreMotion → iPhone bridge → FastAPI server.

Status: data collection + preprocessing + merging + quality checks are
operational. Feature engineering, model training, and evaluation are
TODO.

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

**Preprocess / train / evaluate:**
```bash
python -m src.preprocessing.preprocessing
python -m src.training.train       # loads latest pen+watch CSVs, merges, saves to data/processed/merged_dataset.csv
python -m src.evaluation.evaluate  # currently prints label distribution
```

**Run smoke tests:**
```bash
pytest tests/         # ~30 tests, <1 s
```

## Architecture

```
Apple Watch (MotionManager.swift)
  → batches of 25 samples at 50 Hz via WatchConnectivity
  → iPhone (PhoneBridge.swift)
  → HTTP POST /watch
  → server.py → data/raw/watch/{session}_watch.csv

Moleskine Smart Pen (BLE)
  → pen_logger.py (subprocess spawned by server.py)
  → data/raw/pen/{session}_pen.csv
                    ↓
       src/preprocessing/preprocessing.py
       (load, clean, time-align at ±20 ms tolerance)
                    ↓
         data/processed/merged_dataset.csv
                    ↓
       src/training/train.py → src/evaluation/evaluate.py
```

### Server (`server.py` + `src/server/`)

`server.py` is a thin entry point (~50 lines). All logic lives in
`src/server/`. Dependency order (no backwards imports):

```
config.py          paths, field names, sessions.csv init
utils.py           pure helpers (_now_ms, _as_float, _mad …)
state.py           SessionState class + global `state` object
logging_setup.py   RotatingFileHandler + EventLog handler wiring
csv_io.py          read/write watch + pen + sessions CSVs;
                   _next_session_id() (also scans raw/* to avoid ID reuse);
                   _pen_recent_dots() for the live whiteboard preview
status.py          connection status + _status_payload() for WS broadcasts
quality.py         ISSUE_SPECS table; _session_facts() = single source of truth;
                   _session_quality / _session_validation / _session_report
broadcast.py       _broadcast() + _status_loop() (1-s tick)
pen_proc.py        starts/stops pen_logger.py as a subprocess
routes.py          all FastAPI endpoints as APIRouter
models.py          Pydantic schemas (WatchEnvelope, SessionStartBody …)
```

The pen logger runs as an `asyncio.create_subprocess_exec` child;
`POST /pen/connect` and `/pen/disconnect` control it independently, and
session start/stop start/stop it automatically.

### Key endpoints

- `GET /` — `dashboard.html`
- `POST /session/start` / `POST /session/stop` — write `data/sessions.csv`
- `POST /watch` — receives IMU batches; supports both flat list and
  `{samples: [...]}` envelope formats
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
  `CMDeviceMotion` at 50 Hz, batches of 25 over `WCSession.sendMessage`
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

- `src/preprocessing/preprocessing.py` — `prepare_pen_data()`,
  `prepare_watch_data()`, `merge_pen_watch()` (pandas `merge_asof`,
  ±20 ms nearest-neighbour, on device-relative ms, with stroke-variance
  δ pre-shift applied to `pen.local_ts_ms`).
- `src/preprocessing/pen_match.py` — `pen_match()`, `match_pen_data()`,
  `strokes_from_dot_types()`, `reconstruct_watch_wall_clock()`. Recovers
  the per-session pen↔watch clock offset δ via stroke-window variance
  minimization (TH Zürich algorithm, see *Sample-level merge alignment*
  below). Replaces the planned tap-sync recording protocol.
- `src/training/train.py` — orchestrates load → merge → save; ML model
  is a TODO.
- `src/evaluation/evaluate.py` — currently prints label distribution.

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
`PEN_DOWN`/`PEN_MOVE`, else 0.

**Sessions index** (`data/sessions.csv`):
```
session_id, person_id, description, start_time, end_time,
pen_samples, watch_samples, status
```
Session IDs auto-increment (`S001`, `S002`, …). `_next_session_id()`
scans **sessions.csv, `data/raw/pen/`, and `data/raw/watch/`** so an
ID can never be reused while a stale per-session CSV is still on disk.

**Merged CSV:** pen rows as base, watch IMU joined on device-relative
ms within ±20 ms tolerance. Pen-derived features `dt`, `dx`, `dy`,
`distance`, `speed` are added during preprocessing. Server/local
timestamps are capture metadata, not the canonical ML timeline.

## Quality Checks

`/sessions/quality` returns separate `ml_readiness` and
`recording_health` scores. Issues come from `ISSUE_SPECS` in
`quality.py` — each issue has `code`, `check`, `threshold`, `observed`,
`rationale`, plus `ml_severity` and `recording_severity`. Sync
confidence is a calibration diagnostic only — it must not downgrade a
session by itself.

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
If reconfigured, `_TARGET_WATCH_HZ` in `quality.py` is the single
place to update.

**Sample-level merge alignment:** pen and watch device clocks do not
share an epoch (typical Moleskine pen offset: ~922 days plus an
arbitrary time-of-day shift). Session-level overlap uses wall-clock
`local_ts_ms`. For sample-level merging the per-session offset δ is
recovered automatically by the **stroke-variance alignment** in
`src/preprocessing/pen_match.py` — a port of the TH Zürich algorithm
(see `data/02_Pen_IMU_Timestamp_Alignment.pdf`). Physical assumption:
while the pen is on paper, the wrist holding the watch is comparatively
still, so the correct δ minimizes the mean watch-acceleration variance
under the shifted stroke mask. The search runs coarse (±20 s @ 0.5 s)
then fine (±5 s @ 10 ms); confidence is reported as
`sigma_minimal_variance` (z-score of the minimum vs the search-grid
distribution — more negative = stronger). `merge_pen_watch()` applies
δ to `pen.local_ts_ms` before the `merge_asof` join and skips the
shift when `sigma > -2`. This replaced the planned tap-sync recording
protocol — no special user action at session start is required.

## Testing

`tests/` holds Tier-1 smoke tests — anything that could silently
poison the training data:

- `test_quality.py` — synthetic CSVs feeding into `_session_facts`;
  asserts which issue codes fire. Includes a regression for the
  stale-CSV-window bug.
- `test_session_id.py` — `_next_session_id` skips IDs with stale
  pen/watch files.
- `test_merge.py` — `merge_pen_watch` nearest-neighbour join,
  `label_writing` mapping, x=-1 filtering.
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
