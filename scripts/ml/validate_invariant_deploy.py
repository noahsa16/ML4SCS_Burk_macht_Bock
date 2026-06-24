"""Validiert die (b)-Kernannahme: die 30 gravity-invarianten Features sind auf
roher Gesamtbeschleunigung == userAcceleration.

Unit-Test: exakte Offset-Invarianz. Reale Auswertung (CLI): auf den Modern-Sessions
(userAccel + gravity vorhanden) die Features beidseitig bauen (echte userAccel vs.
rekonstruierte Roh-Accel = userAccel + gravity) und vergleichen. Erwartet ~identisch;
der kleine Rest ist Within-Window-Gravity-Rotation (zweiter Ordnung).

CLI: python scripts/ml/validate_invariant_deploy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODERN = [("S038", "P12"), ("S039", "P13"), ("S040", "P14"),
          ("S041", "P15"), ("S043", "P17")]


def invariant_features(accel3: np.ndarray, fs_hz: float, cols: list[str]) -> np.ndarray:
    """1 s / 0.5 s windows of the requested feature columns from a (N,3) accel signal.

    Gyro columns are zero-filled so _window_features runs; only `cols` are kept.
    """
    accel3 = np.asarray(accel3, dtype=float)
    win, stride = int(round(fs_hz)), int(round(0.5 * fs_hz))
    six = np.column_stack([accel3, np.zeros((len(accel3), 3))])
    rows = [[_window_features(six[s:s + win], fs_hz=fs_hz)[c] for c in cols]
            for s in range(0, len(six) - win + 1, stride)]
    return np.asarray(rows, dtype=float)


def feature_agreement(true_user, raw, fs_hz, cols) -> dict:
    ft = invariant_features(true_user, fs_hz, cols)
    fr = invariant_features(raw, fs_hz, cols)
    n = min(len(ft), len(fr))
    ft, fr = ft[:n], fr[:n]
    diff = ft - fr
    corr = [np.corrcoef(ft[:, j], fr[:, j])[0, 1]
            for j in range(ft.shape[1])
            if ft[:, j].std() > 1e-9 and fr[:, j].std() > 1e-9]
    return {"max_abs": float(np.max(np.abs(diff))) if diff.size else float("nan"),
            "corr": float(np.mean(corr)) if corr else float("nan")}


def run() -> None:
    import joblib
    # Load first-party trained model (trusted source, same codebase)
    bundle = joblib.load(ROOT / "models" / "rf_acc_only_live.joblib")
    cols = bundle["feature_cols"]
    print(f"features={len(cols)} (gravity-invariant)\n")
    for sid, pid in MODERN:
        m = pd.read_csv(DATA_PROC / f"{sid}_merged.csv")
        fs = infer_fs_hz(m)
        user = m[["ax", "ay", "az"]].to_numpy(float)
        raw = user + m[["gx", "gy", "gz"]].to_numpy(float)
        a = feature_agreement(user, raw, fs, cols)
        print(f"  {pid} ({sid}): corr={a['corr']:.5f}  max_abs={a['max_abs']:.5f}")
    print("\ncorr→1 / max_abs→0 = invariante Features deployen sauber auf Roh-Accel.")


if __name__ == "__main__":
    run()
