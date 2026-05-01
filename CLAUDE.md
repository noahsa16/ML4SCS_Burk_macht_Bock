# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Semester-long group project for *Machine Learning for Quantified Self*. The research question: can writing activity and concentration levels of elementary school children be detected using IMU data from a smartwatch combined with ground-truth data from a Moleskine Smart Pen (NWP-F130)?

**Team:** Noah Samel, Ben Kriegsmann, Tajuddin Snasni

## Setup

```bash
pip install -r requirements.txt
```

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

### Data Pipeline

Raw data is collected from two sources and must eventually be fused:

1. **Moleskine Smart Pen (NWP-F130)** — captured by `pen_logger.py` via BLE. Uses the NeoSmartpen V2 protocol (reverse-engineered from the TypeScript WEB-SDK2.0). Output CSV columns: `timestamp, x, y, pressure, dot_type, tilt_x, tilt_y, section, owner, note, page`. Dot types: `PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER`.

2. **Smartwatch (Apple Watch Series 7 / Samsung)** — accelerometer + gyroscope data (IMU). Integration is TBD.

Collected CSV files live in `data/experiments/`. Processed data goes to `data/processed/` (gitignored).

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
