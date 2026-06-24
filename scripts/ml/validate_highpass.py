"""Validiert den GravityHighPass gegen echte userAcceleration (Modern-Sessions).

raw = userAccel + gravity ist aus den Modern-Sessions rekonstruierbar; der Filter
darauf soll die echte userAccel treffen. Entscheidet, ob Option (c) High-Pass das
Roh-Accel-Problem löst, ohne das Modell anzufassen.

CLI: python scripts/ml/validate_highpass.py [--alpha 0.9]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.gravity_highpass import GravityHighPass  # noqa: E402
from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODERN = [("S038", "P12"), ("S039", "P13"), ("S040", "P14"),
          ("S041", "P15"), ("S043", "P17")]


def _features_over(samples: np.ndarray, fs_hz: float, cols: list[str]) -> np.ndarray:
    """Build 1 s / 0.5 s windows of accel-only feature rows, restricted to cols.

    samples: (N,3) accel; gyro columns are zero-filled so _window_features runs,
    then only the requested acc-only cols are kept.
    """
    win = int(round(1.0 * fs_hz))
    stride = int(round(0.5 * fs_hz))
    six = np.column_stack([samples, np.zeros((len(samples), 3))])
    rows = []
    for start in range(0, len(six) - win + 1, stride):
        feats = _window_features(six[start:start + win], fs_hz=fs_hz)
        rows.append([feats[c] for c in cols])
    return np.asarray(rows, dtype=float)


def highpass_feature_agreement(true_user, raw, fs_hz, feature_cols, alpha=0.9) -> dict:
    f_true = _features_over(np.asarray(true_user, float), fs_hz, feature_cols)
    f_hp = _features_over(GravityHighPass(alpha).process(raw), fs_hz, feature_cols)
    n = min(len(f_true), len(f_hp))
    f_true, f_hp = f_true[:n], f_hp[:n]
    diff = f_true - f_hp
    cols_corr = []
    for j in range(f_true.shape[1]):
        if f_true[:, j].std() > 1e-9 and f_hp[:, j].std() > 1e-9:
            cols_corr.append(np.corrcoef(f_true[:, j], f_hp[:, j])[0, 1])
    return {
        "rmse": float(np.sqrt(np.mean(diff ** 2))),
        "max_abs": float(np.max(np.abs(diff))) if diff.size else float("nan"),
        "corr": float(np.mean(cols_corr)) if cols_corr else float("nan"),
    }


def run(alpha: float) -> None:
    import joblib
    bundle = joblib.load(ROOT / "models" / "rf_acc_only_live.joblib")
    cols = bundle["feature_cols"]
    print(f"alpha={alpha}  features={len(cols)}\n")
    for sid, pid in MODERN:
        merged = pd.read_csv(DATA_PROC / f"{sid}_merged.csv")
        fs = infer_fs_hz(merged)
        true_user = merged[["ax", "ay", "az"]].to_numpy(float)
        raw = true_user + merged[["gx", "gy", "gz"]].to_numpy(float)
        out = highpass_feature_agreement(true_user, raw, fs, cols, alpha)
        print(f"  {pid} ({sid}): corr={out['corr']:.4f}  rmse={out['rmse']:.4f}  "
              f"max_abs={out['max_abs']:.4f}")
    print("\nVerdikt: corr→1 / kleine rmse über alle = High-Pass trägt (Option c).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alpha", type=float, default=0.9)
    run(ap.parse_args().alpha)
