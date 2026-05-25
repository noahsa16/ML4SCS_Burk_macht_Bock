"""Bit-exact feature diff between LiveInference and the cached training
features that the model was trained on.

If features match -> model proba should match -> AUC and accuracy will match.
If features diverge -> we know exactly which features and by how much.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

DATA = ROOT / "data"

session_id = sys.argv[1] if len(sys.argv) > 1 else "S033"

# 1) Gold standard: feed cached features into the trained model.
bundle = joblib.load(ROOT / "models" / "rf_noah.joblib")
clf = bundle["model"]
fcols = bundle["feature_cols"]

cached = pd.read_csv(DATA / "processed" / f"{session_id}_windows.csv")
print(f"cached windows: {len(cached)}")
X_cached = cached[fcols].to_numpy()
proba_cached = clf.predict_proba(X_cached)[:, 1]
y = cached["label"].to_numpy()
acc_cached = float((((proba_cached >= 0.5).astype(int)) == y).mean())
from sklearn.metrics import roc_auc_score, f1_score
print(f"  acc (cached features -> model):  {acc_cached:.3f}")
print(f"  f1  (cached features -> model):  {f1_score(y, (proba_cached >= 0.5).astype(int)):.3f}")
print(f"  auc (cached features -> model):  {roc_auc_score(y, proba_cached):.3f}")
print(f"  mean proba writing: {proba_cached[y==1].mean():.3f}")
print(f"  mean proba idle:    {proba_cached[y==0].mean():.3f}")

# 2) Recompute features from the merged CSV using the SAME build_windows logic.
print()
merged = pd.read_csv(DATA / "processed" / f"{session_id}_merged.csv")
fs_inferred = infer_fs_hz(merged)
print(f"infer_fs_hz on merged: {fs_inferred:.3f}")
print(f"trained sample_rate_hz: {bundle.get('sample_rate_hz')}")

# 3) Now compute features from the RAW WATCH csv (no merge), the way
# live inference effectively does.  This is what the live buffer would
# see — no pen labels, just raw samples.
watch = pd.read_csv(DATA / "raw" / "watch" / f"{session_id}_watch.csv").dropna(
    subset=["ax", "ay", "az", "rx", "ry", "rz", "ts"]).sort_values("ts").reset_index(drop=True)
print(f"watch rows: {len(watch)}")

# Replicate live behaviour: take 1 s windows striding by 0.5 s.
# But for fs we use the ts-diff-based estimate (which is what _estimate_fs does).
n_total = len(watch)
ts_arr = watch["ts"].to_numpy()
overall_fs = (n_total - 1) * 1000.0 / (ts_arr[-1] - ts_arr[0])
print(f"overall fs from ts: {overall_fs:.3f}")

n_win = int(round(1.0 * overall_fs))
stride = int(round(0.5 * overall_fs))
print(f"n_win={n_win}  stride={stride}")

ts_diff_each_window = []
proba_live = []
proba_y_aligned = []
feature_diffs: dict[str, list[float]] = {c: [] for c in fcols}

imu_arr = watch[["ax","ay","az","rx","ry","rz"]].to_numpy(dtype=float)

# Match each window to the cached window by t_center_ms.
cached_indexed = cached.set_index("t_center_ms")
cached_t = cached["t_center_ms"].to_numpy()

for start in range(0, n_total - n_win + 1, stride):
    end = start + n_win
    window_ts = ts_arr[start:end]
    # live's _estimate_fs uses (n-1)*1000/(last-first) of buffer:
    local_fs = (n_win - 1) * 1000.0 / (window_ts[-1] - window_ts[0])
    t_center = float(window_ts.mean())

    feats_live = _window_features(imu_arr[start:end], fs_hz=local_fs)
    x = np.array([feats_live[c] for c in fcols], dtype=float)
    p = float(clf.predict_proba(x.reshape(1, -1))[0, 1])
    proba_live.append(p)
    ts_diff_each_window.append(t_center)

    # nearest cached row to t_center
    idx = int(np.argmin(np.abs(cached_t - t_center)))
    if abs(cached_t[idx] - t_center) <= 400:  # ms tolerance
        proba_y_aligned.append(cached["label"].iat[idx])
        # Diff features
        for c in fcols:
            cached_v = float(cached[c].iat[idx])
            diff = feats_live[c] - cached_v
            feature_diffs[c].append(diff)
    else:
        proba_y_aligned.append(np.nan)

proba_live = np.array(proba_live)
y_aligned = np.array(proba_y_aligned)
mask = ~np.isnan(y_aligned)
yA = y_aligned[mask].astype(int)
pA = proba_live[mask]
acc_live = float((((pA >= 0.5).astype(int)) == yA).mean())
print()
print(f"live-recomputed features:")
print(f"  acc:  {acc_live:.3f}")
print(f"  f1 :  {f1_score(yA, (pA >= 0.5).astype(int)):.3f}")
print(f"  auc:  {roc_auc_score(yA, pA):.3f}")
print(f"  mean proba writing: {pA[yA==1].mean():.3f}")
print(f"  mean proba idle:    {pA[yA==0].mean():.3f}")

print()
print("Feature divergence (top 20 by mean abs diff):")
diffs_summary = []
for c in fcols:
    arr = np.array(feature_diffs[c])
    if len(arr) == 0:
        continue
    diffs_summary.append((c, np.mean(np.abs(arr)), np.std(arr)))
diffs_summary.sort(key=lambda r: -r[1])
for name, mad, sd in diffs_summary[:20]:
    print(f"  {name:30s}  mean|diff|={mad:.5f}  std={sd:.5f}")
