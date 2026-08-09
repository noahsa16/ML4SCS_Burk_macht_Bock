# scripts/

Everything here is a command-line entry point. Library code lives in `src/`.

The split that matters is **pipeline vs. research**: `pipeline/` produces the
artefacts the running system loads, `ml/` records how we got there. A script in
`ml/` may well document a negative result — that is the point of keeping it.

| Directory | Purpose | Safe to change without re-training? |
|---|---|---|
| `pipeline/` | Produces deployed artefacts (`models/*.joblib`, `models/hmm_live.json`) | No — output is loaded at runtime |
| `ml/` | Research: comparisons, ablations, falsifications | Yes |
| `plots/` | Figures for `reports/` and the presentation | Yes |
| `ops/` | Server, tunnel, data bundling | Yes |
| `checks/` | Ad-hoc data-integrity probes | Yes |
| `analysis/` | Per-fold error analyses | Yes |

Paths under `ml/` and `plots/` are referenced by external runners (RunPod pods,
Colab notebooks) that clone this repo and call them directly. Renaming a file
there breaks those silently — the failure only surfaces on the next training
run.

---

## pipeline/ — writes what the server loads

| Script | Produces |
|---|---|
| `train_noah_personal.py` | `models/rf_noah.joblib` — personal model, live default (100 Hz, no z-score) |
| `train_rf_all_live.py` | `models/rf_all_live.joblib` — generic model with pooled μ/σ baked in |
| `train_acc_only_live.py` | Accelerometer-only variant for passive deployment |
| `export_hmm_live.py` | `models/hmm_live.json` — transition matrix + prior for the live HMM filter |
| `validate_invariant_deploy.py` | Guard: asserts the deployed feature set matches what the model expects |

The headline LOSO artefacts (`rf_all.joblib`, `loso_cv.csv`) come from
`src/training/train_loso.py`, not from here. `rf_all.joblib` uses per-session
z-score and is deliberately **not** deployable.

---

## ml/ — the research record

**Model comparison.** `compare_models.py` (RF vs. ExtraTrees / HistGradBoost /
LogReg / MLP / SVM-RBF on identical splits), `compare_models_at_gap.py` (same
panel, features rebuilt at an arbitrary `--gap`), `minirocket_loso.py`,
`rocket_loso.py`, `tsai_loso.py`, `ensemble_committee.py`.

**Features — mostly negative results.** `rhythm_feature_test.py` (autocorrelation
peak + spectral flatness against the typing confound: no effect),
`hard_negative_feature_test.py` (ten sharpened minority-vote features: no
effect), `tsfresh_loso.py` + `tsfresh_winners_test.py` (the project's first
transferable feature gain), `ablate_features_loso.py`, `feature_importance.py`.

**Window and label sweeps.** `sweep_window_size.py` (native long feature windows
beat 1 s + burst smoothing), `ablate_gap_loso.py` (label-closing sensitivity),
`sweep_matrix.py` + `sweep_collect.py` (CI fan-out), `rf_hparam_sweep.py`.

**HMM post-processing.** `hmm_postprocess_loso.py` (the +2.4 pp that shipped),
`hmm_cross_model.py` (the gain tracks window size, not model family),
`hmm_hyperparameter_sweep.py`, `hmm_3s_probe.py`.

**Fusion.** `harnet_rf_fusion.py` (null result at N=14), `tcn_rf_fusion.py`
(significant at N=20), `tcn_transformer_fusion.py`, `deep_deep_fusion.py`.

**Deep hyperparameter search.** `deep_hp_study.py` (Sobol, per-architecture),
`deep_hp_matrix.py`, `run_grid_wandb.py`, `tui_runner.py`,
`pull_wandb_runs.py`, `deep_hard_negative_weight.py`.

**Augmentation.** `augment_ab.py`, `augment_ab_collect.py`, `augment_matrix.py` —
no gain on either pool; `AUGMENT` stays off by default.

**Calibration and explanation.** `calibration_decision_scale.py`,
`shap_explain_fold.py`, `marker_fpr.py` (per-task false-positive rates — located
the keyboard/phone typing gap), `label_kinematics_check.py`, `sync_audit.py`,
`per_subject_threshold.py`, `honest_live_loso.py` (leak-free pooled z-score).

**Accelerometer-only / passive.** `acc_only_loso.py`,
`passive_raw_accel_loso.py`, `passive_raw_poc.py`.

**Single-subject and 100 Hz.** `within_noah_100hz.py`,
`cnn_within_noah_100hz.py`, `predict_s032.py`.

**Live diagnostics.** `replay_live_inference.py` (feeds a known CSV through
`LiveInference` sample by sample) and `diff_live_features.py` (per-feature diff,
training path vs. live path) — together these found the sort-stability bug.
`inspect_model.py` dumps a joblib's metadata.

---

## ops/

`start.sh` (server + optional tunnel in one TTY), `tunnel.sh`, `test_server.sh`,
`check_running.sh`, `ensure_views.py` (builds missing legacy views),
`pack_sweep_data.sh` (bundles proband data for an external runner — the bundle
is gitignored and must never be committed).
