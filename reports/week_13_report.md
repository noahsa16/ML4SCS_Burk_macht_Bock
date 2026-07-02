# Week 13 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Stress-test the "signal-ambiguity ceiling" narrative from Week 12: is the weakest fold (P17) truly irreducible, or partly a training gap? In parallel, close the fair-comparison gap in the deep-model sweep (same hyperparameters were never guaranteed across architectures) and check whether ensembling or data augmentation buys further headline gains.

## Work Done This Week

### The "ceiling" is partly an addressable training gap, not pure ambiguity

Mapping LOSO false positives to Study-Mode task markers shows they cluster on two specific tasks, not evenly across all idle blocks: pooled FPR is 0.36 on `keyboard_typing` and 0.25 on `phone_typing`, vs. 0.036 on `pause` (4.7×). P17 confuses both typing tasks with writing ~2/3 of the time, while other subjects (P26/P27) reject them almost perfectly — this is subject-specific, not a universal signal limit. A raw-data comparison shows P17 types aggressively (Hunt-and-Peck), producing writing-scale wrist bursts; a matched SHAP diff (P17-writing vs. P17-typing, r = 0.633 across the 88 features) finds two features that already discriminate correctly (`rx_band_3_8`, `gyro_mag_jerk_mean_abs`) but get outvoted by the majority. A follow-up rhythm/periodicity feature (autocorrelation peak, spectral flatness) built to directly target this gap came back negative (keyboard-FPR 0.343 → 0.336, n.s.) — handwriting is rhythmic enough at the wrist that it doesn't separate the two. Net: more diverse typing-style training data remains the honest lever, not a quick feature fix.

### TCN6↔RF ensemble lifts both solo models — unlike the earlier harnet fusion

On the native 5-s decision scale (N=20, 20 folds), averaging RF and tcn6 probabilities beats both alone: RF-solo 0.879, tcn6-solo 0.898, **ensemble 0.909** (± 0.036), AUC 0.978. Paired Wilcoxon: significant vs. both solo models on accuracy (p = 0.003–0.036); AUC gain over tcn6 alone is not significant. This reverses the Week-12-adjacent harnet-RF fusion result (no lift, similar residual correlation ~0.57–0.60 in both cases) — the extra 6 folds here likely give enough power to detect a real but small (~1 pp) effect. Research finding only; live inference still runs 1-s RF + HMM.

### Cohort grown to N=20; a clean negative result on augmentation

Added 5 new v2-protocol subjects (P26/P27/P29/P31/P32) to the legacy pool. The 1-s headline is essentially flat (0.869 vs. 0.872 at N=15) — the new folds are a mix of the weakest (P31, P17) and strongest (P26, P13) in the cohort, no systematic drop. Separately, an on-the-fly IMU augmentation A/B (scale/rotate, and a richer jitter/time-warp/magnitude variant) across both pools found no gain on any pool or variant (AUC flat everywhere, no config passes the significance gate) — input-space augmentation can't invent signal that isn't there. A grouped-5-fold check corroborates the LOSO headline (0.867 vs. 0.871, no fold-structure artifact). On the modern (gravity) pool, a 3-seed tcn6 re-run exposed a ±1.7 pp seed-noise floor — several previously reported "wins" (z-score, validation-based early stopping) turned out to be noise at this sample size.

### First transferable feature gain: distilled tsfresh winners

After three targeted feature attempts failed, an automated 4,700-feature tsfresh bank beat the 88 hand-crafted features in a matched-window paired test (+0.85 pp accuracy, p = 0.0015; AUC also significant — a genuine separability gain, unlike the augmentation null where AUC stayed flat). The top-ranked features concentrate in four families the 88 lack: per-axis autocorrelation at fixed short lags (40–100 ms, gyro), quantiles, change-quantiles, and CID complexity. Distilling these into 42 plain-numpy features (no tsfresh dependency) and re-testing on all ~45k windows at the natural class distribution confirms the transfer: window accuracy 0.869 → 0.874 (p = 0.007), AUC p = 0.0002, and the gain compounds through the deployed live stack (1-s + HMM: 0.895 → 0.899, p = 0.003). The gain lives at the 1-second scale — 5-s burst aggregation absorbs it — which is exactly where the live pipeline operates. Not yet adopted into the canonical pipeline; adoption requires retraining the deployed models.

### Fair per-architecture hyperparameter study — infrastructure merged

Built a Sobol-sampled nuisance-parameter sweep (learning rate, dropout, batch size, weight decay) so architecture comparisons aren't confounded by one model getting better defaults than another, with a 3-job GitHub Actions pipeline (prepare → per-config search → collect). Merged to main; a full cloud run is dispatched but not yet analyzed. A second Actions workflow benchmarks four tsai architectures (InceptionTime/XceptionTime/ResNet/TSiTPlus) with per-fold seed ensembling; running.

## Key Insights

- **The ceiling isn't monolithic.** Part of it is genuine signal ambiguity (most features can't separate P17's typing from writing); part of it is an addressable training gap (two features already discriminate, just outvoted). Diagnosing which part you're looking at changes what's worth building next.
- **Fancy methods are hit-or-miss where more data is reliable.** TCN6-RF fusion worked, harnet-RF fusion and augmentation didn't, at similar sample sizes. The project's biggest recent gains keep coming from data/labeling/diagnosis, not new model machinery.
- **Automated feature banks earn their keep as search engines, not deployments.** tsfresh's value wasn't running 4,700 features in production — it was *finding* the four families our hand-crafted set missed, which then distill into 42 cheap portable features. Hand-engineering plus automated search beats either alone.
- **Seed noise is a real floor at N≈7.** A single seed's tcn6 run swung ~2.4 pp from the multi-seed average — architecture comparisons at this scale need multiple seeds or a nuisance-controlled sweep (this week's HP-study infrastructure) to be trusted.

## Plan for Next Week

- Analyze the completed Deep-HP-Study cloud run once it finishes.
- Land the hard-negative feature test (per-axis gyro jerk, accel-rotation correlation, sample weighting) — running as of this report.
- Regenerate the canonical N=20 artifacts (`loso_cv_legacy.csv`, `rf_all.joblib`) — still N=15 pending retraining.

## Contributions

### Noah

- Marker-FPR diagnosis + P17 raw-data/SHAP mechanism analysis + rhythm-feature negative result.
- TCN6↔RF fusion experiment; N=20 pool expansion; augmentation A/B + grouped-5-fold check.
- Deep-HP-Study Sobol infrastructure (subagent-driven build, PR #57).

### Ben

- _to be filled in_

### Taji

- _to be filled in_
