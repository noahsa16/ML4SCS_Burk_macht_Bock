# Week 12 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Close the legs left open after the N=15 capture-clock headline: (1) break the "decision-window ceiling" with sequence models trained on real long-window context, (2) test whether a light post-processor can lift the live 1-s model without retraining, and (3) give the pipeline a shippable face — an on-device writing-focus tracker.

## Work Done This Week

### Deep long-window models break the 5-s ceiling

The "≥5 s ties the RF" ceiling only held for *burst-smoothing a 1-s model*. Training CNN/TCN directly on **native 5-s windows** beats the RF on the same 15 folds:

| Model (native 5-s decision) | Accuracy | ROC-AUC |
|---|---:|---:|
| RF (5-s feature window) | 0.885 | 0.953 |
| CNN-5s | 0.905 | 0.970 |
| TCN-5s | **0.911** | **0.976** |
| tcn6 (6-layer) | **0.922** | 0.978 |

Paired Wilcoxon, same folds: TCN-5s vs RF **+2.1 pp acc (p = 0.001), +2.6 pp AUC (p = 0.0001)**; CNN-5s comparable. The gain comes from longer **raw input** (more context to pool), not a wider receptive field — tcn6 ≈ TCN-5s — and plateaus at ~5 s. Same weak folds as the RF (P17/P07), train/test gap 0.012 → data-limited, not overfit.

### Causal HMM post-processing — +2.4 pp on the live model, no retraining

A 2-state (idle/writing) **causal** HMM over the RF's per-window probabilities (scaled-likelihood emission, leak-free per-person transition matrix) lifts the 1-s RF **0.881 → 0.905** and beats causal burst smoothing on every scale (+4.4 pp @5 s … +13 pp @30 s, 15/15 folds, p = 0.0001), at ~16 s *adaptive* latency. A shuffled-emission negative control collapses to 0.50, ruling out a block-detection artefact. Causal + O(1)/tick → live-deployable.

A 2×2 cross-model ladder (RF/TCN × 1 s/5 s) shows the gain hangs on **time-context, not model family**: the HMM helps the memoryless 1-s models (RF +2.4, TCN +1.0) and *hurts* the 5-s ones (over-smoothing). RF-1s+HMM 0.905 ≈ TCN-1s+HMM 0.905 ≈ native TCN-5s 0.911 — one ceiling, several roads. Calibration check: the raw 1-s proba is already honest (ECE 0.020); burst aggregation worsens it (Brier 0.09 → 0.16); the HMM has the best Brier (0.080).

### Scrybe — the live-deployment leg

Rebuilt the iPhone app into **Scrybe**, a writing-focus tracker for the wearer, backed by the existing live-inference pipeline:

- Horizontal pager **Today / Trends / History** — ink-ring daily goal, goal-met streak, a "writing now" live chip from the `live_inference` WebSocket, week strip + streak calendar.
- The operator UI moved behind a hidden, **PIN-gated Admin panel** (long-press the wordmark): recording health, data-flow backlog, connections, session STOP, spill repair, event log, settings.
- One new endpoint `GET /focus/history?days=N`; the project's first **Swift Testing** target (pure logic: streak, goal, time-format, data-flow, DTO decode); legacy iPhone view + all AirPods code removed.

Executed as a 40-task plan; verified green — server `pytest` 494/494, Swift build + unit tests + on-device boot smoke.

## Key Insights

- **The ceiling was the framing, not the signal.** "≥5 s aggregation ties the RF" was only true for smoothing a 1-s model; real long-window representation — native 5-s TCN, or a 1-s model + HMM — clears it by ~2 pp.
- **Time-structure is a single bucket.** Long windows, a post-hoc HMM, and a deep net all reach ≈0.905–0.911. You collect the context gain once, then deploy the cheapest road (1-s RF + HMM), not all three.
- **The project now has a face.** The same per-window probabilities that drive the LOSO table now drive a calm on-device tracker — classification → live deployment is end-to-end.

## Plan for Next Week

- Retrain `rf_all_live.joblib` (still N=14, pre-fix) on the N=15 pooled-μ/σ pool.
- Wire the HMM post-processor into live inference (stateful — needs gap/session reset) and pick RF-1s+HMM vs native TCN-5s for deployment.
- Final presentation + report: classification → regression → engagement → live deployment (Scrybe), with the long-window/HMM result and the capture-clock fix as the two headline corrections.

## Contributions

### Noah

- Native long-window deep LOSO (CNN/TCN/tcn6 @5–10 s) + paired significance vs RF; showed the gain is raw-context and plateaus at ~5 s.
- Causal HMM post-processor + cross-model context ladder + Phase-2 decision-scale calibration (ECE/Brier).
- Scrybe iPhone redesign: 40-task rebuild into a writing-focus tracker + PIN-gated Admin, `/focus/history` endpoint, first Swift Testing target, legacy/AirPods removal.

### Ben

- _to be filled in_

### Taji

- _to be filled in_
