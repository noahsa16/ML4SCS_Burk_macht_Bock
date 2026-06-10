"""E1: kalt-test von rf_all.joblib (trainiert auf 50-Hz-Korpus) auf S032 @ 100 Hz.

Beantwortet die Pipeline-Validierungs-Frage: haelt der fs_hz-Auto-Detect-Fix
genug, dass das 50-Hz-trainierte Modell auf 100-Hz-Daten generalisiert?

Nicht: 'ist 100 Hz besser als 50 Hz' — das ist E2 (Downsample-A/B).
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score, classification_report
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.train_loso import _zscore_per_session, _burst_metrics  # noqa: E402
from src.profiles import find_windows

MODEL_PATH = ROOT / "models" / "rf_all.joblib"
WIN_PATH = find_windows("S032")
FIG_DIR = ROOT / "reports" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

bundle = joblib.load(MODEL_PATH)
clf = bundle["model"]
feature_cols = bundle["feature_cols"]
print(f"Model trained on: {bundle['trained_on']}  ({bundle['n_windows']} windows)")

w = pd.read_csv(WIN_PATH)
w["session_id"] = "S032"
y_true = w["label"].to_numpy()

# Per-session z-score wie im Training: hier nur eine Session -> equivalent zu
# standardize global. Wichtig damit Feature-Skala passt.
X = _zscore_per_session(w, feature_cols)[feature_cols].to_numpy()
proba = clf.predict_proba(X)[:, 1]
pred = (proba >= 0.5).astype(int)

print("\n--- S032 @ 100 Hz, cold from rf_all ---")
print(f"n windows: {len(w)}  ({100*y_true.mean():.1f}% writing)")
print(f"accuracy:  {accuracy_score(y_true, pred):.3f}")
print(f"F1(write): {f1_score(y_true, pred):.3f}")
print(f"ROC-AUC:   {roc_auc_score(y_true, proba):.3f}")
print()
print(classification_report(y_true, pred, target_names=["idle", "writing"], digits=3))

# Burst-aggregierte Metriken @ 1/5/10/30s
burst = _burst_metrics(proba, y_true, w, scales_sec=(1.0, 5.0, 10.0, 30.0))
print("--- Burst-aggregated ---")
print(f"{'scale':>6} {'acc':>7} {'f1':>7} {'auc':>7}")
for scale, m in burst.items():
    print(f"{scale:>6} {m['accuracy']:>7.3f} {m['f1_writing']:>7.3f} {m['roc_auc']:>7.3f}")

# Plot: probability trace vs ground truth across the full session
t = (w["t_center_ms"] - w["t_center_ms"].min()) / 1000.0
fig, ax = plt.subplots(2, 1, figsize=(14, 5), sharex=True,
                       gridspec_kw={"height_ratios": [3, 1]})
ax[0].plot(t, proba, color="#3b82f6", lw=0.8, label="p(writing)")
ax[0].axhline(0.5, color="grey", ls="--", lw=0.5)
ax[0].fill_between(t, 0, 1, where=(y_true == 1), color="#fbbf24",
                   alpha=0.25, step="pre", label="ground truth (writing)")
ax[0].set_ylabel("Wahrscheinlichkeit")
ax[0].set_ylim(0, 1)
ax[0].set_title(
    f"S032 @ 100 Hz — RF kalt aus 50-Hz-Korpus  "
    f"(acc={accuracy_score(y_true, pred):.3f}, AUC={roc_auc_score(y_true, proba):.3f})"
)
ax[0].legend(loc="upper right", fontsize=8)
ax[1].plot(t, (pred == y_true).astype(int), color="#10b981", lw=0.4)
ax[1].set_ylabel("correct")
ax[1].set_xlabel("Zeit (s)")
ax[1].set_ylim(-0.1, 1.1)
fig.tight_layout()
out = FIG_DIR / "s032_cold_predict.png"
fig.savefig(out, dpi=120)
print(f"\nPlot: {out}")
