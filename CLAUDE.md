# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Semester ML project (team: Noah Samel, Ben Kriegsmann, Tajuddin Snasni). The goal is a model that predicts writing activity solely from **Apple Watch IMU data**. The Moleskine Smart Pen is used only during data collection as ground truth: pen stroke events (`dot_type`) label the watch samples at the same timestamp. Once the model is trained, the pen is no longer needed — inference runs on watch data alone.

Two sensors used during training data collection:
- **Moleskine Smart Pen (NWP-F130)** — ground truth labels; provides pen coordinates, pressure, tilt at ~80–90 Hz via BLE
- **Apple Watch IMU** — model input; accelerometer + gyroscope via native watchOS app → FastAPI server

Current status: data collection is operational; preprocessing/merging is implemented; feature engineering, model training, and evaluation are stubs (TODO).

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
- `server.py` — minimal FastAPI app; each POST to `/watch` appends a JSON batch of IMU samples to CSV
- `src/preprocessing/preprocessing.py` — `prepare_pen_data()`, `prepare_watch_data()`, `merge_pen_watch()` (nearest-neighbor join, 20 ms tolerance)
- `src/training/train.py` — orchestrates load → merge → save; feature engineering and model fitting go here
- `src/evaluation/evaluate.py` — evaluation harness; currently prints counts only
- `watch_streamer/` — SwiftUI iOS/watchOS app; `MotionManager.swift` captures and streams IMU data to the server

Root-level `src/preprocessing.py`, `src/train.py`, `src/evaluate.py` are thin re-export shims for convenience.

## Data Formats

**Pen CSV:** `timestamp, x, y, pressure, dot_type, tilt_x, tilt_y, section, owner, note, page`
- `dot_type`: `PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER` — used to derive `label_writing` (1 for DOWN/MOVE, 0 otherwise)

**Watch CSV:** `local_ts, session_id, sequence, sample_rate_hz, watch_sent_at, phone_received_at, source, ts, ax, ay, az, rx, ry, rz`

**Merged CSV:** pen rows as base, watch IMU joined at nearest timestamp within ±20 ms tolerance; pen-derived features `dt`, `dx`, `dy`, `distance`, `speed` added during preprocessing.

## Path Convention

All source files resolve data paths relative to the project root via:
```python
Path(__file__).parents[N] / "data"
```
Do not use hard-coded absolute paths.
