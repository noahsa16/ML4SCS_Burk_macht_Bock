# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ML4SCS (Machine Learning for Smart and Connected Systems) — a semester project detecting writing activity and concentration levels in elementary school children using multivariate time-series data from:
- **Moleskine Smart Pen (NWP-F130)**: x/y coordinates, pressure, tilt, timestamps via BLE
- **Apple Watch (Series 7)**: accelerometer + gyroscope at 50 Hz via CoreMotion

The research question: can writing activity and concentration be detected/predicted from IMU + pen sensor data?

## Running the Stack

**Install Python dependencies:**
```bash
pip install -r requirements.txt
```

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
```

## Architecture

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

**Time alignment:** `merge_pen_watch()` uses `pd.merge_asof` with nearest-neighbour matching within ±20 ms. This relies on the pen CSV having `local_ts_ms` (wall-clock ms at time of receipt). Older pen logs without this column cannot be confidently aligned — the quality endpoint flags this as `legacy_pen_time`.

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

**Sessions index** (`data/sessions.csv`):
```
session_id, person_id, start_time, end_time, pen_samples, watch_samples, status
```
Session IDs auto-increment as `S001`, `S002`, …

## Quality Checks

Before using a session for modelling, verify via `GET /sessions/quality` or the dashboard Sessions page:
- Watch samples must include both `ax/ay/az` (accelerometer) and `rx/ry/rz` (gyroscope).
- Estimated watch sample rate should be 40–60 Hz (target: 50 Hz).
- Pen CSV must have `local_ts_ms` for reliable wall-clock alignment.
- No sequence gaps in watch batches.

Processed data (`data/processed/`) is gitignored and regenerated by the training pipeline.
