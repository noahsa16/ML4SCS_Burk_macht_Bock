# Writing Activity Detection via Apple Watch IMU

[![tests](https://github.com/noahsa16/ML4SCS_Burk_macht_Bock/actions/workflows/test.yml/badge.svg)](https://github.com/noahsa16/ML4SCS_Burk_macht_Bock/actions/workflows/test.yml)

**Semester project · Machine Learning for Smart and Connected Systems**  
Team: Noah Samel · Ben Kriegsmann · Tajuddin Snasni

(Picture to be added after next seminar)

---

## Research Question

> Can writing activity be detected from IMU data (accelerometer + gyroscope) of an Apple Watch?

The Moleskine Smart Pen is used as ground truth during data collection — its stroke events tell us when the wearer is actually writing, which lets us label the watch samples. Once the model is trained the pen is no longer needed; inference runs on the watch alone, which is the whole point of the project.

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
                                                   88 features + label smoothing:
                                                   time-stats + spectral (FFT) +
                                                   jerk + ZCR + correlations)
                                                                     │
                                  data/processed/{session}_windows.csv
                                                                     │
                                  src/training/within_session/    (RF baseline,
                                    train_rf.py                    temporal 80/20 —
                                                                   debug only)
                                  src/training/train_loso.py      (per-session z-score
                                                                   → LOSO cross-val —
                                                                   headline metric)
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
server.py / pen_logger.py    FastAPI entry point + standalone BLE pen logger
src/server/                  Modular server (config, state, csv_io, quality,
                             routes/, study.py — Study Mode runner)
src/alignment/               Pen↔IMU clock-offset recovery (stroke-variance)
src/merge/                   Watch-base merge (1 row per IMU sample + label)
src/features/                Sliding windows → 88 features per window
src/training/                train_loso.py (headline) + within_session/ (debug)
forecast/                    Learning-curve projection to N=99 probands
scripts/                     Plot helpers, multi-model comparison, dev tools
tests/                       138 smoke tests (~1.5 s)
static/, dashboard.html      Web dashboard (page-modular ES modules)
watch_streamer/              iOS + watchOS Xcode targets
data/raw/, data/processed/   Per-session CSVs (raw committed, processed gitignored)
study_protocols/             Study Mode protocol definitions (v1.json)
```

See [CLAUDE.md](CLAUDE.md) for the per-module breakdown.

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

**3. Start a session** from the dashboard — both pen logger and watch start automatically. Two modes are available:

- **Free mode** (default): START, write freely, STOP. Same flow as before.
- **Study mode**: toggle the Recording page to **Study Mode** → pick `v1` from the protocol dropdown → **START STUDY**. The proband side enters a fullscreen takeover with per-task instructions, a pre-task countdown, an urgent last-5-second pulse, and audio cues (880 Hz tick + E5/B5 chime at transitions). The VL controls Pause / Next / Abort and can monitor live status from a second screen via the hidden `#admin` page — **triple-click the brand logo** to reach it on iPad. Task order is counterbalanced via a Latin Square keyed on `subject_index`.

**4. Record data** — write something, pause, write again (or follow the protocol).

**5. Stop the session** — CSVs are finalized. Study Mode also writes `data/raw/markers/{session}_markers.csv` with one row per task transition.

**6. Check quality** — dashboard Sessions page shows `ml_readiness` and `recording_health` per session. The **⤓ md** link in each row downloads a self-explaining Markdown report listing every issue with its check, threshold, observed value, and rationale (`GET /sessions/{id}/report?format=md`).

Server logs go to the terminal *and* `logs/server.log` (rotating). The same log lines also show up in the dashboard's event log panel — useful when debugging connection drops or rate spikes.

---

## ML Pipeline

Once a session is recorded, the per-session preprocessing is two commands:

```bash
python -m src.merge S029                      # watch-base merge → data/processed/S029_merged.csv
python -m src.features S029 --max-gap-ms 300  # sliding windows  → data/processed/S029_windows.csv
```

Without a session ID, `merge` and `features` operate on the most recent session.

There are two training entry points, and we use them for different things.

### Cross-subject evaluation (this is what we report)

```bash
python -m src.training.train_loso --by person      # true LOSO-by-person — what we report
python -m src.training.train_loso --by session     # leave-one-session-out fallback
```

This is the evaluation that actually matches the project goal: a general writing detector that should work regardless of who is wearing the watch. Each fold holds out one subject completely, so the held-out data is never seen during training. The script prints per-fold accuracy and ROC-AUC plus a mean ± std summary. By default it only includes sessions marked `verdict ∈ {trainable, usable}` in `data/sessions.csv` (use `--include-all` to override).

Current 5-subject LOSO result (Noah, P01, P02, P03, Taji) with RandomForest + per-session z-score + label closing `max_gap_ms=2000`: **accuracy 0.872 ± 0.020, ROC-AUC 0.940 ± 0.018, F1(writing) 0.887.** Per-1-s window — see the burst-aggregated numbers below for the user-facing view.

**Per-session z-score normalization** (on by default, `--no-zscore` to disable). Before fitting, each feature column is standardised per `session_id` — subtract that session's mean, divide by its std. The motivation is that the hardest cross-subject problem is *not* "which feature distinguishes writing"; it's that the same gesture produces different absolute feature values on different wrists (size, handedness, watch position, tightness of the strap). Per-session standardisation removes that absolute-scale component while preserving the relative structure within a session. Empirically the single biggest ML-side win of the early project: on the 3-person dataset it jumped accuracy from 0.812 → 0.838 and tightened fold-σ ~4× (0.042 → 0.009). Caveat for deployment: production needs a calibration phase (or rolling stats) to estimate μ, σ from the live stream before the model can be applied — a model trained with z-score cannot be served raw IMU features without that step.

**Label-closing decision (`max_gap_ms`).** Default was historically 300 ms — close any pen-up gap shorter than that into a continuous "writing" label. After N=5 we ran a full LOSO ablation across `300 / 600 / 1000 / 1500 / 2000 / 2500` ms (`scripts/ablate_gap_loso.py`); `2000` came out as the sweet spot: largest single-step gain of the project (acc +4.2 pp / AUC +3.5 pp / F1 +8.9 pp vs. 300), all 5 folds improving monotonically, σ tightening from 0.026 → 0.020. 2500 squeezed +0.3 pp more on the average but caused P02 to regress for the first time — 2000 is the last "no fold regresses" step. Semantically this redefines the label from "pen currently on paper" to "person in writing mode incl. micro-pauses ≤ 2 s", which is closer to what a writing-time tracker actually wants to detect.

**Model comparison at the new label.** With `gap=2000`, the model family stops mattering — top-3 (SVM-RBF / HistGradBoost / RF) are within 0.6 pp accuracy of each other (0.872–0.878), all at AUC 0.940 ± 0.018. RF stays the headline default for stability and reproducibility; ExtraTrees is the speed champion (~0.9 s fit per fold, AUC 0.940). Full table in `reports/model_progression.md` under "Modellvergleich auf Run-08-Basis".

#### Burst-aggregated metrics (decision window)

The 1-s window is right for *features* (FFT bands, label transitions) but rarely the right *decision* window for an app — a writing-time tracker cares about "has the person written in the last 30 s?", not per-second accuracy. So `train_loso.py` reports the same fold at 1/5/10/30 s by smoothing the 1-s probabilities per session and re-thresholding at 0.5. With `--save-cv-csv` these land as extra columns in `models/loso_cv.csv`.

### Within-session baseline (for iterating)

```bash
python -m src.training.within_session.train_rf S029
```

Temporal 80/20 split on a single session, 4-window gap to avoid leakage. **Not a generalisation claim** — used only for feature-iteration and label-smoothing tuning. Real numbers come from `train_loso.py`.

```bash
pytest tests/     # 138 cases, ~1.5 s
```

---

## Data Formats

The two files that actually feed the model:

- **`data/processed/{session}_merged.csv`** — watch-base: one row per IMU sample + `label_writing ∈ {0, 1}` from the nearest pen `dot_type` within ±40 ms of the δ-corrected pen clock. Watch samples in pen-gaps → label 0.
- **`data/processed/{session}_windows.csv`** — one row per 1 s sliding window (0.5 s stride) with 88 features (time-stats + spectral + jerk + ZCR + correlations), plus `label` and `t_center_ms`. Labels are morphologically closed (default 300 ms) at sample level before windowing.

Raw CSV schemas (watch, pen, AirPods, sessions index, Study-Mode markers) are documented in [CLAUDE.md](CLAUDE.md).

---

## Pen ↔ IMU Time Alignment

The pen and the watch don't share a clock. The Moleskine pen's hardware clock is typically off by about 922 days plus some time-of-day offset, so a naïve wall-clock join would smear the labels by hundreds of milliseconds or worse — which would make the whole project pointless.

We recover the per-session offset **δ** automatically with a stroke-window variance-minimisation approach, ported from the TH Zürich method described in [`data/02_Pen_IMU_Timestamp_Alignment.pdf`](data/02_Pen_IMU_Timestamp_Alignment.pdf). The implementation is in [`src/alignment/pen_match.py`](src/alignment/pen_match.py).

The idea: while the pen is touching paper, the wrist holding the watch stays comparatively still — strokes are short and the motion is constrained. So the correct δ shifts the stroke mask onto the calmest parts of the IMU signal, and we can find it by minimising the mean accelerometer variance under the shifted mask.

```
                δ wrong                                δ correct
       ┌────────────────────┐                  ┌────────────────────┐
 acc   │   ╱╲   ╱╲    ╱╲    │            acc   │       ___      __  │
 var   │  ╱  ╲ ╱  ╲  ╱  ╲   │            var   │ ___ ╱   ╲ ___ ╱  ╲ │
       │ ╱    V    ╲╱    ╲  │                  │╱   ╲    │   ╲    │ │
       └─▲─────▲────▲─────▲─┘                  └─▲────▲────▲────▲──┘
         strokes overlap motion                  strokes sit on quiet IMU
```

The search runs in two passes: a coarse one (±20 s in 0.5 s steps) handles BLE buffering and clock drift, then a fine one (±5 s in 10 ms steps) refines around the coarse minimum. We report the confidence as `sigma_minimal_variance` — a z-score of the minimum against the rest of the search grid. More negative means a clearer alignment.

`merge_watch_pen()` calls `match_pen_data()`, shifts `pen.local_ts_ms` by δ, then runs a watch-based `merge_asof` within ±40 ms. Every watch sample is preserved and gets `label_writing = 1` if the nearest pen `dot_type` is `PEN_DOWN` or `PEN_MOVE` within tolerance, else `0`. If the signal is too weak (`sigma > -2`) we skip the δ shift and the quality engine flags the session as `low_sync_confidence` (warn) or `sync_failed` (bad). For actual training we apply a stricter filter of `σ ≤ -3` — we noticed that values around -2 sometimes lock onto spurious local minima.

This replaced an earlier idea to require a tap-sync protocol at the start of each recording (3× tap with the watch hand). We're glad we didn't go that route — alignment is now fully post-hoc and probands don't have to do anything special.

---

## Quality Checks

Each session is scored against a fixed set of checks defined in `quality.py`. Every issue carries `code`, `check`, `threshold`, `observed`, and a short `rationale` — so when a warning fires it's clear *why* and what assumption the threshold reflects. That came in handy: the first version of these checks had three thresholds set wrong, and we only noticed when we could actually read why each one was warning.

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

The full pipeline is operational: capture → alignment → merge → features → training, plus Study Mode for counterbalanced recording. **Headline metric: 5-subject cross-subject LOSO (Noah, P01, P02, P03, Taji) with RandomForest + per-session z-score + label closing `max_gap_ms=2000` — accuracy 0.872 ± 0.020, ROC-AUC 0.940 ± 0.018, F1(writing) 0.887.** The label-closing switch (300 → 2000 ms) was the largest single-step gain of the project (+4.2 pp acc, all 5 folds improved monotonically). Detailed progression — Run 01 (single-subject baseline) → Run 08 (current) — and the multi-model comparison panel live in [`reports/model_progression.md`](reports/model_progression.md). Next milestone is N ≥ 8 probands; the learning-curve forecast (`forecast/`) becomes statistically meaningful around that point, and is roughly the threshold where 1D-CNN baselines start to be worth implementing.

---

## Weekly Reports

- [Week 3](reports/week03.md)
- [Week 4](reports/week_04_report.md)
- [Week 5](reports/week_05_report.md)
- [Week 6](reports/week_06_report.md)
