# Writing-Activity Detection from Apple Watch IMU

[![tests](https://github.com/CH-GE-Focus-Watch/ML4SCS/actions/workflows/test.yml/badge.svg)](https://github.com/CH-GE-Focus-Watch/ML4SCS/actions/workflows/test.yml)

**Semester project · Machine Learning for Smart and Connected Systems (ML4SCS)**
Noah Samel · Tajuddin Snasni

> **Can handwriting be detected from an Apple Watch's wrist IMU alone — independent of who is wearing the watch and what they write?**

A Moleskine smart pen supplies ground-truth stroke labels **during data collection only**: its `dot_type` events tell us exactly when the wearer is writing, which labels the watch samples at the matching timestamp. Once the model is trained the pen is gone — inference runs on the watch alone, which is the whole point.

**Headline — 20-subject cross-subject LOSO** (RandomForest + per-session z-score + label closing): accuracy **0.869 ± 0.032**, ROC-AUC **0.946 ± 0.021** at 1-second resolution; **0.856 / 0.932** at a 5-second decision window. A causal HMM post-filter runs live in the dashboard.



---

## Data & Collection

| Device | Role | Signal |
|--------|------|--------|
| **Apple Watch (Series 7)** | model input | accelerometer + gyroscope (+ gravity), **currently 100 Hz**; the LOSO cohort was recorded at 50 Hz without gravity (the "legacy" pool) |
| **Moleskine Smart Pen NWP-F130** | ground truth (collection only) | x / y / pressure / `dot_type` via BLE |

**Counterbalanced study protocol.** Recordings run under a Williams-Latin-square protocol (Study Mode v2) that deliberately weaves in **hard negatives** — phone typing, keyboard typing, scrolling, pen-fidgeting, gesturing — alongside writing variants (normal, soft-pressure, think-pause). Task order is counterbalanced per subject, and every state transition is written to a per-session markers CSV, so downstream analysis can attribute each error to the exact task that produced it. The proband side is a fullscreen takeover with per-task instructions, a pre-task countdown, and audio cues; the experimenter drives Pause / Next / Abort from a hidden second-screen monitor.

**Cohort.** 22 subjects collected. The computed headline is on the 20-subject legacy pool; the two newest subjects' refresh is pending. Sessions enter training only if they pass an alignment-confidence and quality gate (`verdict ∈ {trainable, usable}`).

**Pen ↔ IMU time alignment.** The pen and watch clocks don't share an epoch — the pen's hardware clock is typically ~922 days off — so a naïve wall-clock join would smear every label. We recover the per-session offset **δ** automatically by **stroke-variance minimisation** (ported from an ETH Zürich method): while the pen is on paper the wrist stays comparatively still, so the correct δ shifts the stroke mask onto the calmest stretches of the IMU signal. A coarse (±20 s) then fine (±5 s @ 10 ms) search finds it; confidence is the z-score of the minimum against the search grid. No tap-sync ritual at recording time. → [`src/alignment/pen_match.py`](src/alignment/pen_match.py)

---

## Method

```
Watch IMU ─► iPhone bridge ─► POST /watch ─► server ─► data/raw/watch/{s}_watch.csv
Pen (BLE) ─► pen_logger.py ─────────────────────────► data/raw/pen/{s}_pen.csv
      │
      ├─ pen_match.py    recover δ (stroke-variance)
      ├─ merge.py        watch-base join, label ±40 ms → {s}_merged.csv
      ├─ features/       1 s windows / 0.5 s stride → 88 features → {s}_windows.csv
      └─ train_loso.py   per-session z-score → LOSO-by-person   (headline)
                              │
                   live @1 Hz (inference.py) → dashboard pill + causal HMM filter
```

- **Label closing (`max_gap_ms = 2500`).** The pen only reports contact, but a writer in mid-thought lifts the pen for < 2.5 s while still *writing*. Morphological closing redefines the label from "pen on paper" to "person in writing mode (incl. micro-pauses)" — the user-facing truth for a writing-time tracker. The `300 → 2500` sweep was the single largest data-side gain of the project.
- **88 features per 1-s window** in six semantic groups (time-stats, spectral/FFT, jerk, zero-crossing rate, magnitude, cross-axis correlation). Modern (gravity) sessions add 4 tilt features → 92.
- **Per-session z-score** (on by default) standardises each feature per session before fitting, removing the absolute-scale drift between wrists (size, handedness, strap). It was the **largest single ML-side win** of the project.
- **LOSO-by-person** — each fold holds out one subject entirely, so the held-out data is never seen in training. This is the metric that maps to the deployment scenario, and it is what we report.
- **Causal burst aggregation** at 1 / 5 / 10 / 30 s decision windows (trailing rolling mean, no look-ahead) — because an app cares about "has the person written in the last 30 s?", not one 1-s window.
- **Causal HMM live filter** — a 2-state (idle/writing) post-processor on the 1-s probabilities. It lifts the 1-s decision **0.881 → 0.905 without retraining** and is deployed in the server.

---

## Results & the honest ceiling

| Decision window | Accuracy | ROC-AUC |
|-----------------|----------|---------|
| **1 s** (per window) | **0.869 ± 0.032** | **0.946 ± 0.021** |
| 5 s (causal burst) | 0.856 ± 0.039 | 0.932 ± 0.026 |
| 10 s (causal burst) | 0.825 ± 0.046 | 0.907 ± 0.032 |
| 30 s (causal burst) | 0.771 ± 0.046 | 0.855 ± 0.041 |

*20-subject cross-subject LOSO (22 collected, refresh pending). Burst numbers are strictly causal — the earlier centered-smoothing gain was future leakage.*

**The ceiling is signal ambiguity, not the model.** The residual error clusters on one confusion: aggressive keyboard / phone typing looks like writing at the wrist. Pooled false-positive rate is 0.36 on keyboard-typing vs. 0.04 on genuine pauses, and the hardest subject mistakes ~2/3 of his typing windows for writing. Crucially, **four unrelated model families — RandomForest, MiniRocket, a wearable foundation model (harnet), and deep TCNs — converge on the same cross-subject wall**, and the feature axis was falsified three separate ways (rhythm features, sharpened hard-negative features, data augmentation — all null). The first *transferable* gain came from distilled `tsfresh` features (+0.5 pp, p = 0.007). This is a data problem (more typing-style subjects), not a modelling one.


*Four model families cluster at the same cross-subject ceiling (N=15). Two routes rise above the 1-s decision level: native 5-second deep windows (TCN, 0.911) and a causal HMM on the 1-s RandomForest (0.905). The HMM route is the one deployed live.*

**Deep models (research arm).** Under the identical LOSO protocol, a TCN-trunk + GRU hybrid is the front-runner (grouped-5-fold, 3-seed mean 0.922), and native long-window training beats the RF by +2–4 pp — but this margin lives entirely in what burst aggregation already removes, so the deployed model stays the 1-s RandomForest + HMM. Full model-comparison panel: [`reports/model_progression.md`](reports/model_progression.md).

**Live deployment.** Inference runs every second in the server. The dashboard surfaces it as a topbar pill and a Recording-page card (60-s sparkline + persistent writing-time counter that survives restarts), with a model picker between a personal model and a generic pooled-μ/σ model for raw-stream serving.

---

## Reproduce

```bash
pip install -r requirements.txt

# per-session preprocessing (omit the ID to use the most recent session)
python -m src.merge S029                       # watch-base merge  → {s}_merged.csv
python -m src.features S029 --max-gap-ms 2500  # sliding windows   → 88 features

# headline cross-subject evaluation
python -m src.training.train_loso --by person  # true LOSO-by-person

pytest tests/                                  # 682 smoke tests, ~10 s
```

Run the full live stack: `uvicorn server:app --host 0.0.0.0 --port 8000`, then open the dashboard at `http://localhost:8000` and connect the iPhone app.

---

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — the full operational reference: architecture, module map, data schemas, and the pipeline gotchas that still bite.
- **[documentation/](documentation/)** — consolidated [experiment log](documentation/experiment_log.md) (negative results, deep-model / fusion numbers) and the [headline lineage](documentation/headline_history.md) (N=3 → 22).
- **[reports/](reports/)** — per-experiment deep-dives. Highlights: [marker-driven ceiling diagnosis](reports/marker_fpr.md) · [causal HMM post-processing](reports/hmm_postprocess.md) · [distilled tsfresh feature gain](reports/tsfresh_transfer.md) · [TCN↔RF fusion](reports/tcn_rf_fusion.md) · [the sort-stability bug forensics](reports/sort_stability_bug.md).
- **Weekly reports:** [W3](reports/week03.md) · [W4](reports/week_04_report.md) · [W5](reports/week_05_report.md) · [W6](reports/week_06_report.md) · [W7](reports/week_07_report.md) · [W8](reports/week_08_report.md) · [W9](reports/week_09_report.md) · [W10](reports/week_10_report.md) · [W11](reports/week_11_report.md) · [W12](reports/week_12_report.md) · [W13](reports/week_13_report.md)
