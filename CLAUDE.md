# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Semester ML project (team: Noah Samel, Ben Kriegsmann, Tajuddin Snasni). The goal is a model that predicts writing activity solely from **Apple Watch IMU data**. The Moleskine Smart Pen is used only during data collection as ground truth: pen stroke events (`dot_type`) label the watch samples at the same timestamp. Once the model is trained, the pen is no longer needed — inference runs on watch data alone.

Two sensors used during training data collection:
- **Moleskine Smart Pen (NWP-F130)** — ground truth labels; provides pen coordinates, pressure, tilt at ~80–90 Hz via BLE
- **Apple Watch IMU** — model input; accelerometer + gyroscope via native watchOS app → FastAPI server

Current status: data collection is operational; preprocessing/merging is implemented; feature engineering, model training, and evaluation are stubs (TODO).

## Setup

ML4SCS (Machine Learning for Smart and Connected Systems) — a semester project detecting writing activity and concentration levels in elementary school children using multivariate time-series data from:
- **Moleskine Smart Pen (NWP-F130)**: x/y coordinates, pressure, tilt, timestamps via BLE
- **Apple Watch (Series 7)**: accelerometer + gyroscope at 50 Hz via CoreMotion

The research question: can writing activity and concentration be detected/predicted from IMU + pen sensor data?

## Running the Stack

**Install Python dependencies:**
Semester-long group project for *Machine Learning for Quantified Self*. The research question: can writing activity and concentration levels of elementary school children be detected using IMU data from a smartwatch combined with ground-truth data from a Moleskine Smart Pen (NWP-F130)?

**Team:** Noah Samel, Ben Kriegsmann, Tajuddin Snasni

## Setup

```bash
pip install -r requirements.txt
```

## Running the Pipeline

**Collect pen data:**
```bash
python pen_logger.py [--password XXXX]
# Move output pen_log_YYYYMMDD_HHMMSS.csv → data/raw/pen/
```

**Collect watch data:**
```bash
python server.py                  # FastAPI on 0.0.0.0:8000, writes watch_data.csv
./test_server.sh [IP]             # Smoke-test the endpoint
# Move collected CSV → data/raw/watch/
```

**Preprocess and merge:**
```bash
python -m src.training.train      # Loads latest pen+watch CSVs, merges, saves to data/processed/merged_dataset.csv
```

**Evaluate:**
```bash
python -m src.evaluation.evaluate # Loads merged_dataset.csv, prints label distribution (metrics TODO)
**Start the FastAPI server (required for data capture):**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000` to access the session dashboard.

**Run the pen BLE logger standalone:**
```bash
python pen_logger.py [--password XXXX] [--session S001]
```
Without `--session`, output goes to `pen_log_YYYYMMDD_HHMMSS.csv` in the working directory. With `--session`, output goes to `data/raw/pen/{session}_pen.csv`.

**Test the watch HTTP endpoint:**
```bash
./test_server.sh [IP]   # defaults to 127.0.0.1
```

**Run preprocessing / training / evaluation modules:**
```bash
python -m src.preprocessing.preprocessing
python -m src.training.train
python -m src.evaluation.evaluate
Dependencies: `pandas`, `numpy`, `matplotlib`, `scikit-learn`, `jupyter`, `notebook`, `bleak`

## Running Key Scripts

**Record pen data via BLE:**
```bash
python pen_logger.py [--password XXXX]
```
Outputs `pen_log_YYYYMMDD_HHMMSS.csv` in the current directory.

**Preprocessing:**
```bash
python src/preprocessing.py
```

**Training / Evaluation:**
```bash
python src/train.py
python src/evaluate.py
```

**Jupyter notebooks:**
```bash
jupyter notebook
```

## Architecture

```
pen_logger.py (BLE)          server.py (FastAPI)
     ↓                              ↓
data/raw/pen/              data/raw/watch/
              ↘            ↙
       src/preprocessing/preprocessing.py
       (load, clean, time-align at ±20 ms)
                     ↓
         data/processed/merged_dataset.csv
                     ↓
       src/training/train.py   →   src/evaluation/evaluate.py
```

**Key modules:**
- `pen_logger.py` — reverse-engineered BLE protocol for the Moleskine Smart Pen (based on the TypeScript NeoSmartpen SDK)
- `server.py` — thin FastAPI entry point (~44 lines); wires up lifespan, mounts the router from `src/server/routes.py`
- `src/server/` — modular server package (see below)
- `static/js/` — browser dashboard modules; no bundler/build step
- `src/preprocessing/preprocessing.py` — `prepare_pen_data()`, `prepare_watch_data()`, `merge_pen_watch()` (nearest-neighbor join, 20 ms tolerance)
- `src/training/train.py` — orchestrates load → merge → save; feature engineering and model fitting go here
- `src/evaluation/evaluate.py` — evaluation harness; currently prints counts only
- `watch_streamer/` — SwiftUI iOS/watchOS app; `MotionManager.swift` captures and streams IMU data to the server

Root-level `src/preprocessing.py`, `src/train.py`, `src/evaluate.py` are thin re-export shims for convenience.

### Server package (`src/server/`)

Dependency order (von unten nach oben, keine Rückwärts-Imports):

```
config.py     Pfade, Feldnamen, SESSIONS_CSV-Initialisierung
utils.py      reine Hilfsfunktionen (_now_ms, _as_float, _mad, …)
state.py      SessionState-Klasse + globales state-Objekt;
              append_event() / append_sample() als Methoden
csv_io.py     CSV lesen/schreiben (Watch, Pen, Sessions)
status.py     Verbindungsstatus (_pen_connected, _watch_connected …)
              + _status_payload() für WS-Broadcasts
quality.py    Session-Qualität (_session_quality) und detaillierte
              Validierung (_session_validation) — kein state-Import,
              reine read-only Analyse der CSV-Dateien
broadcast.py  _broadcast() + _status_loop() (1-s-Tick)
pen_proc.py   Pen-Logger Subprozess starten/stoppen
routes.py     alle FastAPI-Endpunkte als APIRouter
```

## Data Formats

**Pen CSV:** `local_ts, local_ts_ms, timestamp, x, y, pressure, dot_type, tilt_x, tilt_y, section, owner, note, page`
- `dot_type`: `PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER` — used to derive `label_writing` (1 for DOWN/MOVE, 0 otherwise)

**Watch CSV:** `local_ts, local_ts_ms, session_id, sequence, sample_rate_hz, watch_sent_at, phone_received_at, server_received_ms, source, ts, ax, ay, az, rx, ry, rz`

**Merged CSV:** pen rows as base, watch IMU joined on device-relative milliseconds within ±20 ms tolerance; pen-derived features `dt`, `dx`, `dy`, `distance`, `speed` added during preprocessing. Server/local timestamps are capture metadata, not the canonical ML timeline.

**Session quality:** `/sessions/quality` exposes separate `ml_readiness` and `recording_health` scores. Sync confidence is only a calibration diagnostic and must not downgrade a session by itself.

## Path Convention

All source files resolve data paths relative to the project root via:
```python
Path(__file__).parents[N] / "data"
```
Do not use hard-coded absolute paths.
### Data Capture Pipeline

```
Apple Watch (MotionManager.swift)
  → batches of 10 samples at 50 Hz via WatchConnectivity
  → iPhone (PhoneBridge.swift)
  → HTTP POST /watch
  → server.py → data/raw/watch/{session}_watch.csv

Moleskine Smart Pen (BLE)
  → pen_logger.py (subprocess spawned by server.py)
  → data/raw/pen/{session}_pen.csv
```

The server manages pen logger as a child process (`asyncio.create_subprocess_exec`), piping its stdout into the event log. `POST /pen/connect` and `/pen/disconnect` control it independently; session start/stop also start/stop it automatically.

### server.py — Central Hub

A single `SessionState` dataclass instance (`state`) holds all runtime state: active session metadata, sample counts, per-second chart buffer, WebSocket clients, and the pen subprocess handle.

**Key endpoints:**
- `GET /` — serves `dashboard.html`
- `POST /session/start` and `/session/stop` — manage sessions, write to `data/sessions.csv`
- `POST /watch` — receives IMU batches from the iPhone bridge; supports both flat list and `{samples: [...]}` envelope formats
- `GET /sessions/quality` — runs quality checks on every session's CSVs
- `WebSocket /ws` — used by dashboard (status updates every 1 s) and iPhone bridge (`hello`/`watch_ack`/`phone_status` messages)

The `_status_loop` coroutine broadcasts `_status_payload()` over WebSocket every second, updates rolling Hz estimates, and maintains a 60-point chart buffer (one point per second: acc magnitude, gyro magnitude, pen writing state).

### iOS/watchOS App (`watch_streamer/`)

Two targets in the Xcode project:
- **WatchStreamer Watch App** (`MotionManager.swift`): captures `CMDeviceMotion` at 50 Hz, accumulates in a buffer, sends batches of 10 via `WCSession.sendMessage` (or `transferUserInfo` as background fallback). Drops oldest samples when buffer exceeds 500.
- **WatchStreamer (iPhone)** (`PhoneBridge.swift`): receives WatchConnectivity messages, normalizes payload (handles both raw and `Data`-encoded envelopes), queues HTTP POSTs to `http://{serverIP}:8000/watch`. Retries on failure with a 2-second delay. Server IP is stored in `UserDefaults` (key: `"serverIP"`, default `192.168.178.147`).

Watch and iPhone communicate start/stop commands via WatchConnectivity messages. The server broadcasts `{type: "start"/"stop", session_id: ...}` JSON over WebSocket; the iPhone bridge listens and forwards commands to the watch.

### ML Pipeline (`src/`)

The top-level `src/preprocessing.py`, `src/evaluate.py`, and `src/train.py` are deprecated redirect stubs that raise `ImportError`. Use the subpackage paths:

- `src/preprocessing/preprocessing.py` — `prepare_pen_data()`, `prepare_watch_data()`, `merge_pen_watch()`
- `src/training/train.py` — `train()` (currently merges and saves; ML model is a TODO)
- `src/evaluation/evaluate.py` — `evaluate()` (currently prints label distribution; metrics are a TODO)

**Time alignment:** `merge_pen_watch()` uses `pd.merge_asof` with nearest-neighbour matching within ±20 ms on device-relative milliseconds. Watch `ts` and pen `timestamp` are canonical; local/server timestamps are capture metadata.

## Data Schemas

**Watch CSV** (`data/raw/watch/{session}_watch.csv`):
```
local_ts, session_id, sequence, sample_rate_hz, watch_sent_at, phone_received_at,
server_received_ms, source, ts, ax, ay, az, rx, ry, rz
```

**Pen CSV** (`data/raw/pen/{session}_pen.csv`):
```
local_ts, local_ts_ms, timestamp, x, y, pressure, dot_type,
tilt_x, tilt_y, section, owner, note, page
```
`dot_type` values: `PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER`. Dots where `x == -1` and `y == -1` are pen-down/up events with no position — filter them out before spatial analysis.

**Sessions index** (`data/sessions.csv`, local/gitignored):
```
session_id, person_id, description, start_time, end_time, pen_samples, watch_samples, status
```
Session IDs auto-increment as `S001`, `S002`, …

Versioned demo sessions live in `data/samples/` (currently S009 and S013). Real recordings in `data/raw/` and `data/sessions.csv` stay local and must not be committed.

## Quality Checks

Before using a session for modelling, verify via `GET /sessions/quality` or the dashboard Sessions page:
- Watch samples must include both `ax/ay/az` (accelerometer) and `rx/ry/rz` (gyroscope).
- Estimated watch sample rate should be 40–60 Hz (target: 50 Hz).
- Pen and Watch CSVs must have usable device timestamps.
- No sequence gaps in watch batches.

Processed data (`data/processed/`) is gitignored and regenerated by the training pipeline.
### Data Pipeline

Raw data is collected from two sources and must eventually be fused:

1. **Moleskine Smart Pen (NWP-F130)** — captured by `pen_logger.py` via BLE. Uses the NeoSmartpen V2 protocol (reverse-engineered from the TypeScript WEB-SDK2.0). Output CSV columns: `timestamp, x, y, pressure, dot_type, tilt_x, tilt_y, section, owner, note, page`. Dot types: `PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER`.

2. **Smartwatch (Apple Watch Series 7 / Samsung)** — accelerometer + gyroscope data (IMU). Integration is TBD.

Collected CSV files live locally in `data/raw/` and `data/sessions.csv` (gitignored). Small versioned demo data lives in `data/samples/`. Processed data goes to `data/processed/` (gitignored).

### `pen_logger.py` internals

- `Parser` — stateful byte-stream parser. Handles packet framing (STX/ETX/DLE escaping), dispatches commands, and tracks per-session paper state (`section`, `owner`, `note`, `page`) and running timestamp accumulated from per-dot time deltas.
- `find_pen()` — BLE scanner that matches by service UUID (`SVC_128` / `SVC_16`) or device name hints.
- `run()` — async main loop: scans, connects, performs the handshake sequence (VERSION → SETTING → [PASSWORD] → ONLINE), then drains the async queue and writes dots to CSV.

### `src/` modules

Placeholder structure — fill these out as the project progresses:
- `preprocessing.py` — `load_csv()` and `summarize_dataframe()` utilities; extend with the full feature-engineering pipeline here.
- `train.py` — model training entry point.
- `evaluate.py` — model evaluation entry point.

### Notebooks

`notebooks/01_project_setup.ipynb` — initial EDA: load dataset, inspect columns, check shape and missing values.

## Data Notes

- Pen coordinates are raw Ncode values (sub-pixel resolution: integer part + 0.01 × fractional byte).
- `timestamp` is an absolute millisecond epoch from the pen; dot timestamps within a stroke are reconstructed by accumulating per-dot time deltas from the pen-down timestamp.
- `section`/`owner`/`note`/`page` identify which Moleskine notebook page was used.
- Ground-truth concentration labels come from separate CSV files (`taji_konzentriert.csv`, `taji_unkonzentriert.csv`).
