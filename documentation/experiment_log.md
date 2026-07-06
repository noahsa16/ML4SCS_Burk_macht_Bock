# ML4SCS Experiment Log

Extracted from CLAUDE.md 2026-07-06 to keep the operational reference lean.
Primary detailed source remains `reports/*.md`; this file is the consolidated
narrative + the numbers CLAUDE.md used to spell out per script.

---

## 1 · Gap-Ablation Cohort Histories (N=7 → N=10)

The headline `max_gap_ms` is an *a-priori label definition* (which micro-pauses
still count as "writing mode"), not a test-tuned hyperparameter. These runs are
the sensitivity/robustness history behind the `2500` choice.

**N=7 (2026-05-18), gap=2000 → 2500:** acc 0.864 → 0.868 (+0.4 pp), AUC 0.940 →
0.943 (+0.3 pp), F1(w) 0.875 → 0.885 (+1.0 pp). 6/7 folds improved, P02/P03
marginally regressed (≤0.7 pp). P05 (new, weakest fold) profited (acc 0.816 →
0.825, FP 307 → 295) — supports the marker-analysis hypothesis that P05's long
math-task think-pauses exceed 2 s. gap=3000 tested +0.2 pp F1 but P05 regressed
(acc 0.802, FP 340, fidgeting in ≥2.5 s planned pauses wrongly swallowed as
writing) and σ-acc jumped 0.026 → 0.035. `2500` = last point with
near-universal per-fold gain + σ-tightening. Predecessor N=5 switch gap=300 →
2000 gave +4.2 pp acc; at N=7 the plateau is reached.

**N=8 (2026-05-18, +P07/S019):** headline acc 0.868 → 0.861, AUC 0.943 → 0.932,
σ 0.024 → 0.035 — entirely driven by the P07 fold (acc 0.808, AUC 0.848).
Per-block: P07 fails *only* in the Math block (acc 0.578, 96 FPs, 61 FNs);
abschreiben/free_writing/pause clean (0.83–0.96). Sample-level: P07's 225 s
math block has only **22 s real pen time (10 %)**; 6 idle stretches > 10 s
(longest 22 s) that `max_gap_ms=2500` structurally cannot close. **30 s-burst
AUC for P07 recovers to 0.932** — model catches phases, not single seconds.
Side finding: 3 FP-bursts in Pause 2 (+8 s, +49 s, +74 s) match an in-room
observation that P07 was phone-typing during the pause — phone-typing as a real
wrist confound, documented for protocol v2.

**N=10 (2026-05-19, +P08/S020, +P09/S022):** headline acc 0.861 → 0.856, AUC
0.932 → 0.928, F1(w) 0.879 → 0.864 — all moves within σ-fold, σ actually
tightens 0.035 → 0.032. **P08-Math refutes the N=8 "Math is structurally hard"
thesis:** P08 has 26 % pen time in Math (as low as P07's 10 %) yet reaches acc
0.843 / AUC 0.942 there. Math difficulty was P07-individual (long think-pauses +
fidgety hands), not task-inherent. **P09 is a new error class** (acc 0.812, AUC
0.896): pauses excellent (0.92–0.96), both writing tasks symmetrically weak
(Free 0.791/0.843, Abschreiben 0.782/0.844). Abschreiben pen time only **58 %**
(norm 75–80 %) — soft-writer style with long micro-pauses *within* writing.
Unlike P07: **burst @30 s worsens P09** (acc 0.812 → 0.782, AUC 0.896 → 0.851) —
the only fold with @30 s < @1 s AUC. P09's errors are temporally clustered, not
noisy → longer decision windows average away correct predictions. → **Two
distinct failure modes:** P07-class (high-frequency noise, helped by burst /
task-aware labeling) vs P09-class (systematic soft-writer confusion, needs a
softer pen-truth definition).

`ablate_gap_loso.py` re-test (2026-07-01, N=14 legacy): gap 2500 vs 3000 — 2500
acc 0.871 ± 0.030 vs 3000 0.867 ± 0.039, marginally better + more stable, Δ n.s.
(p=0.24) → 2500 stays. Same run: grouped-5-fold (`train_loso --folds 5`,
GroupKFold by subject) acc 0.867 ± 0.026 — practically identical to LOSO
headline (0.871), tighter σ → corroborates the LOSO headline (no fold-structure
artifact).

---

## 2 · Negative Results & Falsifications

**Per-Subject-Threshold** (`scripts/ml/per_subject_threshold.py`, 2026-05-22) —
falsified. Leakage-free: threshold picked on first session-third (calibration,
F1(writing)-optimal), evaluated on remaining 2/3, 0.5-baseline on same windows.
F1(writing) 0.858 → 0.846 (**worse**, 7/10 folds regressed) — first third isn't
class-representative. Oracle (threshold tuned on eval labels, leakage upper
bound) lifts F1(writing) only +0.007; P09's oracle threshold is 0.49 ≈ 0.5.
P09's error is in class *separation*, not threshold placement. Report
`reports/per_subject_threshold.md`.

**catch22 + DWT-Energy features** — no systematic gain at N=3 (Δacc ≈ ±0.003),
fold-σ ~doubled (classic overfitting: feature count grows, data doesn't).
Recorded `reports/model_progression.md`. Worth re-trying at N≥5.

**Rhythm features** (`src/features/rhythm.py`, 2026-07-01) — autocorrelation
peak-height + spectral flatness (4 opt-in features) don't separate keyboard/phone
typing from writing: keyboard-FPR 0.343 → 0.336 (marginal), phone 0.243 → 0.247
(slightly worse), LOSO acc n.s. (p=0.54 window, p=0.89 @5s). Handwriting is
itself rhythmic on the wrist IMU. `reports/rhythm_feature.md`.

**Hard-negative features + weighting** (`scripts/ml/hard_negative_feature_test.py`,
2026-07-02) — 10 targeted sharpenings of the minority separating signals
(per-axis gyro-jerk, accel↔rx correlations, rx/ay ratio) **do not lower typing
FPR** (keyboard 0.343 → 0.358 slightly worse, phone unchanged); a 3× sample-weight
on keyboard/phone train windows drives phone-FPR 0.243 → 0.286 and regresses the
correctly-rejecting subjects (P26/P27 ~−1 pp). LOSO flat (p>0.29). Feature axis
for the typing confound is **triple-falsified** (rhythm, sharpened features,
weighting). `reports/hard_negative_feature.md`. Remaining lever: more subjects
with aggressive typing style, or the confound is intrinsic at 50 Hz.

**Data augmentation** (`src/training/deep/augment.py`, 2026-07-01) — on-the-fly
IMU augmentation (basic: scale 0.8–1.2, rotate ±10°; rich: + time-warp/jitter/
magnitude) via GitHub-Actions A/B (tcn6 @5s, 3 seeds). **No gain on any pool
with any set:** modern/basic Δacc +1.55 pp p=0.078, legacy/basic +0.52 pp p=0.27,
modern/rich +1.28 pp p=0.31 (rich helped *less* than basic). AUC flat throughout
(all Δ ≤ +0.5 pp) — augmentation moves accuracy on single folds (P14/P17/P26) but
no separability. `AUGMENT` default OFF. `reports/augment_ab.md`.

**Per-session z-score honesty** (`scripts/ml/honest_live_loso.py`, 2026-06-11) —
per-session z-score is non-causal (held-out normalized with its own future stats)
but deployable-pooled (`_zscore_train_pooled`, μ/σ fit on train folds) is not
worse: pooled acc 0.863 / AUC 0.930 / @5s 0.855 / @30s 0.789 — slightly **above**
per-session (0.855/0.929; Δacc −0.008 Wilcoxon p=0.035 *favoring pooled*). The
non-causal z-score does not inflate the headline; the honest deployable number is
0.863.

**Sync-audit** (`scripts/ml/sync_audit.py`, 2026-05-22) — residual pen↔watch
alignment error does NOT explain the error ceiling: r(σ,acc)=−0.22,
r(drift,acc)=−0.18 (both null/wrong-sign). `reports/sync_audit.md`.

**Label-kinematics check** (`scripts/ml/label_kinematics_check.py`) — refutes the
"variance minimization maps writing onto rest phases, labels inverted" suspicion:
8/8 jerk features higher for writing (median ratio 1.35) → writing is the more
dynamic class. Not a substitute for video ground truth.

---

## 3 · Deep Models (detailed numbers)

**`src/training/deep/` — TCN/CNN/LSTM/GRU LOSO.** CLI
`python -m src.training.deep --model {cnn|lstm|gru|tcn|tcn6} [--pool legacy|modern] [--win 1|5|10|both] [--zscore]`.
Per-session z-score default OFF (CNN A/B, legacy N=14: Δacc −0.002 p≈0.65 —
BatchNorm re-normalizes activation scale). `RF_DECISION_BY_POOL["legacy"]` =
N=15 post-Capture-Clock-Fix causal burst: @1s 0.872/0.947, @5s 0.860/0.933,
@10s 0.825/0.906, @30s 0.771/0.856.

- **TCN @1s (N=15, post-fix, no-zscore, 2026-06-19):** acc 0.895 ± 0.035, AUC
  0.960 — significant over RF@1s (Δacc +0.021 p=0.0006, ΔAUC +0.010 p=0.015). But
  @5/10/30 s statistically indistinguishable from RF (p>0.1) — the 1s lead is
  exactly the high-frequency noise burst-aggregation removes → no headline gain.
  Weakest fold P17 (0.794), same weak folds as RF. Train/test gap 0.012 =
  data-limited.
- **CNN @1s (N=14, pre-Capture-Clock-Fix, no-zscore):** acc 0.873 ± 0.035, AUC
  0.936, @5s 0.897/0.963, @30s 0.843/0.918 — regen-pending on N=15.

**Native long-window finding (2026-06-20, N=15 legacy, post-fix, no-zscore).**
Training directly on native 5-s windows (250 samples, `--win 5`), per-window =
5-s decision: **TCN-5s acc 0.911 / AUC 0.976 (σ 0.030), CNN-5s 0.905 / 0.970
(σ 0.036)** vs RF-nativ-5s 0.885 / 0.953. Paired Wilcoxon same 15 folds: TCN-5s
vs RF-5s Δacc +0.021 p=0.0012, ΔAUC +0.026 p=0.0001; CNN-5s vs RF-5s Δacc +0.021
p=0.0043, ΔAUC +0.019 p=0.0034 — both significant. Real longitudinal context *in
the representation* lifts deep nets over RF at the 5-s decision scale → the
decision-window ceiling holds only for the **burst framing** (smooth 1-s input),
not native long-window training.

- **`tcn6`** (6 levels, dilations to 32, receptive field 253 ≈ 5 s @ 50 Hz): acc
  0.922 / AUC 0.978 (σ 0.033) — highest point estimate, beats RF-nativ-5s (Δacc
  +0.041 p=0.0012). But vs 4-level TCN-5s (0.911) NOT significant (Δacc +0.019
  p=0.083) → the long-window gain comes from longer raw input (more context for
  pooling), not a literally 5-s receptive field.
- **@10-s native (RF-nativ-10s 0.880/0.955):** TCN-10s 0.914 / 0.979 (σ 0.037)
  still beats RF-10s (Δacc +0.035 p=0.015); CNN-10s falls to 0.889 / 0.969
  (σ 0.047). Long-window gain plateaus at ~5 s (TCN-10s vs TCN-5s Δacc +0.007
  p=0.60). **Practical optimum: 5-s window with TCN/tcn6 (0.911 / 0.922).**

**Modern-pool tcn6 (N=7, 2026-06-25, honest 3-seed):** acc 0.889 ± 0.017 / AUC
0.968 ± 0.001. Seed-noise floor ±1.7 pp (per-fold to ±5 pp, P26 12 pp span at
identical data/config) → architecture tweaks unmeasurable at N=7; only data
moves the number. A prior "+4.9 pp z-score" (N=6) + "+2.8 pp val-based early-stop"
were noise artifacts. AUC seed-stable (ranking robust). Deploy = no-zscore.
Side: `drawing` task correctly excluded from all pools (was a bug depressing P17;
P17 0.728 → 0.843 via fix + N=7). See `modern_zscore_threshold_fix` memory.

**Deep-HP-Study** (`scripts/ml/deep_hp_study.py`, PR #57 merged to main
2026-07-01) — fair per-architecture Sobol HP study (lr/dropout/batch/wd). Search
run (Run 28527728688, N=20 legacy @5s, 64/96 trials, 16.5 h, `reports/deep_hp_study.md`).
Winner @1 seed: **tcn6 0.9194/0.9755 — best AND most robust** (min over 9 Sobol
points 0.893); **GRU surprise 0.9185 gleichauf** (lr~0.005, dropout~0.47) but
HP-fragile; LSTM extremely fragile (median 0.64, best 0.908); tcn 0.905, cnn
0.897 (insensitive, capped). Reference N=20 nativ-5s: RF 0.879, tcn6-default
0.898. tcn6-vs-gru (Δ 0.1 pp) far below seed-floor. Transformer 0/16: OOM in
`predict_proba` (fixed 2026-07-02: chunked batch_size=512).

**MiniRocket** (`scripts/ml/minirocket_loso.py`, 2026-06-24, N=15 legacy) —
nativ-5s 0.886/0.956 ≡ RF-nativ-5s 0.885/0.953 (Δacc −0.004 p=0.93). A
mechanistically RF-unrelated family hits the same ceiling *and* same weakest fold
(P17 0.794) → paradigm-independent ceiling confirmation. Honest negative:
MiniRocket on 1-s+burst is @10s/@30s significantly worse than RF (use nativ-5s).
`models/minirocket_win{1,5}_cv.csv`.

**harnet transfer** (`src/training/deep/harnet*.py`, N=14) — Oxford ssl-wearables
foundation model. Input = userAcceleration without gravity, no z-score. CLIs
`python -m src.training.deep.harnet [--model harnet5|harnet10]` +
`.harnet_finetune`. `reports/harnet_transfer.md`.
- harnet5 frozen LogReg: per-window (5s) 0.896/0.958 — gleichauf mit RF@5s
  (0.899/0.962).
- harnet10 frozen LogReg: per-window (10s) 0.909/0.966 — beats RF@10s
  (0.882/0.952); @30s 0.881/0.950 vs RF 0.838/0.917 (+4.3 pp).
- harnet5 fine-tuned: 0.896/0.965 — no clear gain vs frozen (mean best_epoch 0.8,
  train/test gap +0.042 → pretrained features near-optimal, overfits at N=14).
- Same weak folds as RF (P07/P09/P12), per-fold AUC r≈0.92 with RF.

---

## 4 · Fusion Experiments

**harnet↔RF fusion** (`scripts/ml/harnet_rf_fusion.py`, harnet5, N=14) — null on
native 5-s: ensemble ΔAcc −0.011/ΔAUC +0.001, stack ΔAcc +0.005/ΔAUC +0.006 vs
RF-88. Per-window the fusion shines (RF-AUC 0.923 → stack 0.946 / ensemble 0.949)
but that's pure de-noising of 1-s RF jitter → redundant with burst-aggregation,
vanishes on aggregation. Residual correlation r=+0.574 (RF vs harnet errors) —
both wrong on the same windows. `reports/harnet_rf_fusion.md`.

**tcn6↔RF ensemble** (`scripts/ml/tcn_rf_fusion.py`, 2026-07-01/02, N=20 legacy,
nativ-5s, 9093 windows) — unlike the harnet null, the proba-mean ensemble lifts
BOTH solo models significantly: RF-solo 0.879 ± 0.027 / 0.953, TCN6-solo 0.898 ±
0.045 / 0.969, **ensemble 0.909 ± 0.036 / 0.978**. Ensemble > TCN6-solo (Δacc
+0.0076 p=0.036), > RF-solo (Δacc +0.0327 p=0.0032, ΔAUC +0.0229 p<0.0001).
Residual r=0.599. Likely the gain is real ~1 pp separated from noise by N=20's
higher power (vs N=14 harnet). TCN6-solo 0.898 here vs 0.922 headline = seed-noise
floor; multi-seed ensemble replay still open. **Research finding, NOT deployed.**
`reports/tcn_rf_fusion.md`. See `tcn6_rf_fusion_result` memory.

**tsfresh transfer** (`scripts/ml/tsfresh_loso.py` + `src/features/tsfresh_winners.py`,
2026-07-02) — **first transferable feature gain of the project.** (1) Full tsfresh
bank (~4700 features, 1-s, matched windows) beats the 88 paired: +0.85 pp acc
(0.8821 vs 0.8736 p=0.0015), +0.52 pp AUC (p=0.0005), 16/20 folds. (2) 42 lean
numpy "winner" features distilled (per-axis autocorrelation at fixed short lags,
quantiles, change_quantiles, CID) — opt-in `build_windows(tsfresh_winners=True)`.
(3) Transfer on ALL ~45.5k windows: window-acc 0.869 → 0.874 (p=0.0073), AUC
p=0.0002. @5s-burst n.s. (value on 1-s scale). Live stack 1s+HMM 0.8954 → 0.8993
(p=0.0027) — compounds with HMM. keyboard/phone-FPR mild better (0.343→0.336 /
0.243→0.225), P17 untouched. **Adoption candidate, NOT yet adopted** (would need
flag in canonical window-gen + live inference + retraining). `reports/tsfresh_transfer.md`.
See `tsfresh_feature_gain` memory.

**Deep hard-negative reweighting** (`scripts/ml/deep_hard_negative_weight.py`,
2026-07-06, UNCOMMITTED) — deep counterpart to the RF weighting falsification.
Paired per-fold tcn6 baseline vs 3× loss-weight on keyboard/phone train windows,
only variable = `sample_weight` (added optional to `train_one_model`,
bit-identical when None). Dispatched on the pod queue; expected to confirm the RF
null. `reports/deep_hard_negative_weight.md`.

---

## 5 · Feature-Engineering Ceiling, HMM, Calibration

**Ceiling summary** (`feature_engineering_ceiling` memory) — RF/TCN/harnet/
MiniRocket all hit the same ceiling with the same weak folds (P17/P07/P09); the
limit is signal ambiguity, not model capacity or feature set. SHAP on P17
(`scripts/ml/shap_explain_fold.py`): top features are jerk + 3–8 Hz spectral, but
the *small* signed values (~±0.005) ARE the finding — no feature separates P17.
**Revised by the marker-FPR finding:** a substantial part of P17's weakness is an
addressable keyboard/phone typing confusion (FPR 0.63/0.68), not pure irreducible
ambiguity. But the feature axis for that confound is triple-falsified (§2) → the
lever is more aggressive-typing training data. `reports/shap_hard_negative_diff.md`
(P17 write-vs-type SHAP r=0.633).

**Feature-window sweep** (`scripts/ml/sweep_window_size.py`, 2026-06-11, N=14
legacy) — a 5-s *native* feature window beats 1-s features + burst@5s at fixed 5-s
latency by +2.8 pp acc / +2.3 pp AUC (paired Wilcoxon p≈0.011, 12/14 folds).
Best params 5s/2.5s or 3s/1.5s. Model-robust (RF/ExtraTrees/HistGradBoost/SVM-RBF
+2.0–2.8 pp). P09 (soft-writer) +0.057 biggest gainer, P07 (think-pauses)
−0.038 only regression. **Not adopted** (live inference still 1 s). Writes to
`data/processed/windows_sweep/` (canonical cache untouched).

**HMM post-processor** (`src/evaluation/hmm.py` + `scripts/ml/hmm_postprocess_loso.py`)
— causal forward-filter over per-window probabilities. **Lifts RF 1s acc 0.881 →
0.905 (+2.4 pp, no retraining)**, beats causal burst on every scale (+4.4 pp @5s …
+13 pp @30s, 15/15 folds, p=0.0001), ~16 s adaptive latency. Negative control
(shuffled emission → acc 0.50) excludes a block-detection artifact. **LIVE
deployed since 2026-06-24** (`OnlineForwardFilter`, params `models/hmm_live.json`
via `scripts/ml/export_hmm_live.py`). `reports/hmm_postprocess.md`.

**HMM cross-model ladder** (`scripts/ml/hmm_cross_model.py`) — 2×2 factor
(RF/Deep × 1s/5s): the HMM gain hangs on time-context (window size), NOT model
family. RF-1s +2.4 pp / TCN-1s +1.0 pp (helps) vs RF-5s −0.8 / TCN-5s −0.9 /
harnet-5s −1.0 (hurts/null, over-smoothing). RF-1s+HMM 0.905 ≈ TCN-1s+HMM 0.905 ≈
native TCN-5s 0.911 — one ceiling, several roads. Deploy HMM on the 1-s RF, not
5-s. `reports/hmm_context_ladder.md`.

**Calibration** (`scripts/ml/calibration_decision_scale.py`, N=15) — the 1-s RF
proba is already honest (ECE 0.020 < 0.05, isotonic doesn't improve); burst
worsens calibration (Brier 0.09 → 0.16, resolution loss); HMM has best Brier
(0.080) but slightly over-confident (ECE 0.057). `reports/calibration_decision_scale.md`.

**Gravity verdict** (Modern-LOSO N=4, 92-vs-88 A/B) — cross-subject Gravity does
NOT help (Δacc −0.005, ΔAUC −0.003; P14 regresses −3.8 pp via pose idiosyncrasy);
within-subject stays positive. Gravity is a personalization signal, not a
generalization signal. `reports/feature_ablation.md`. Capture continues (not
retro-imputable, revisable at N≥6).

**Marker-FPR hard-negative gap** (`scripts/ml/marker_fpr.py`, 2026-07-01, N=20 1s
OOF) — LOSO FPR clusters task-specifically on typing, not flat: pooled
keyboard_typing FPR 0.360, phone_typing 0.251 vs pause 0.036 (4.7×). P17: keyboard
0.63, phone 0.68 (confuses ~2/3 of typing windows with writing) despite 5 other
v2 subjects with typing examples — subject-specific (P26/P27 reject near-perfectly).
Partially revises the "ceiling = pure ambiguity" story: a substantial part is an
addressable training gap. `reports/marker_fpr.md`. See `marker_fpr_hard_negative_gap`
memory.
