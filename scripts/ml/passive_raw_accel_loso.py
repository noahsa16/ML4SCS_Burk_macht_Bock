"""Echte Passiv-Zahl: rohe Gesamt-Beschleunigung statt userAcceleration.

`scripts/ml/acc_only_loso.py` misst die acc-only-Lücke, behält dabei aber die
`userAcceleration`-Features. Der reale `CMSensorRecorder` liefert **rohe
Gesamt-Beschleunigung** (inkl. Schwerkraft) — und die Schwerkraft-Trennung zu
`userAcceleration` braucht selbst das Gyroskop. Das ist der „Roh-Accel-Abschlag",
den die erste Ablation nicht beziffern konnte.

Dieses Skript misst ihn **ohne neue Aufnahmen**: die Modern-Pool-Sessions
(P12–P15, P17) haben `userAcceleration` (ax/ay/az) UND `gravity` (gx/gy/gz)
separat aufgezeichnet → `roh = userAcceleration + gravity` ist rekonstruierbar.
Gepaarter Vergleich auf denselben Probanden, identisches 47-Feature-acc-only-Set
(kein Gyro, keine Gravity-Tilt-Features), einziger Unterschied ist die Accel-Quelle:

  Arm A (linear): ax/ay/az = userAcceleration            ← optimistischer acc-only
  Arm B (roh):    ax/ay/az = userAcceleration + gravity  ← echtes CMSensorRecorder-Signal

Δ(A−B) = der Roh-Accel-Abschlag. Caveat: N=5 Modern-Probanden → corroborating, für
einen gepaarten Wilcoxon strukturell unterpowert (min p=0.0625), nicht confirming.

CLI::

    python scripts/ml/passive_raw_accel_loso.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from acc_only_loso import (  # noqa: E402
    _hmm_filter_per_fold,
    _is_gyro_feature,
    _run_arm,
    _summary,
    _test,
)
from src.features.windows import build_windows  # noqa: E402
from src.training.train_loso import _zscore_per_session  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"

# Modern-Study-Sessions mit separat aufgezeichneter Gravity.
MODERN = [("S038", "P12"), ("S039", "P13"), ("S040", "P14"),
          ("S041", "P15"), ("S043", "P17")]


def _windows_for(sid: str, *, total_accel: bool) -> pd.DataFrame:
    """Build 88-feature windows for a modern session, optionally on raw total accel.

    Gravity columns are dropped before windowing so no gravity-tilt features
    enter — `CMSensorRecorder` has no separated gravity either. ``total_accel``
    overwrites ax/ay/az with userAcceleration+gravity (the raw signal).
    """
    m = pd.read_csv(DATA_PROC / f"{sid}_merged.csv")
    if total_accel:
        for a, g in (("ax", "gx"), ("ay", "gy"), ("az", "gz")):
            m[a] = m[a] + m[g]
    m = m.drop(columns=[c for c in ("gx", "gy", "gz") if c in m.columns])
    w = build_windows(m)
    return w


def _arm_windows(total_accel: bool) -> pd.DataFrame:
    frames = []
    for sid, pid in MODERN:
        w = _windows_for(sid, total_accel=total_accel)
        w["session_id"] = sid
        w["person_id"] = pid
        frames.append(w)
    return pd.concat(frames, ignore_index=True)


def run() -> None:
    groups = [pid for _, pid in MODERN]
    print(f"Modern-Pool N={len(groups)}: {groups}\n")

    results = {}
    for arm, total in (("linear (userAccel)", False), ("roh (total accel)", True)):
        w = _arm_windows(total_accel=total)
        feat = [c for c in w.columns
                if c not in {"label", "t_center_ms", "session_id", "person_id",
                             "task_id", "task_category"}]
        acc_cols = [c for c in feat if not _is_gyro_feature(c)]
        w = _zscore_per_session(w, feat)
        tbl, oof = _run_arm(w, acc_cols, groups, "person_id", None)
        hmm = _hmm_filter_per_fold(oof).rename(
            columns={"hmm_acc": "accuracy", "hmm_auc": "roc_auc"})
        results[arm] = {"tbl": tbl, "hmm": hmm, "n_feat": len(acc_cols)}
        print(f"=== {arm}  ({len(acc_cols)} acc-only features) ===")
        _summary(tbl, arm.split()[0])
        print(f"  {'':14s} +HMM acc={hmm['accuracy'].mean():.3f}"
              f"±{hmm['accuracy'].std():.3f}  AUC={hmm['roc_auc'].mean():.3f}\n")

    lin, raw = results["linear (userAccel)"], results["roh (total accel)"]
    print("=== Roh-Accel-Abschlag (linear − roh, gleiche Probanden) ===")
    print("  roh @1s:")
    _test(lin["tbl"], raw["tbl"], "accuracy")
    if "acc_30s" in lin["tbl"]:
        print("  roh @30s:")
        _test(lin["tbl"], raw["tbl"], "acc_30s")
    print("  +HMM (Live-Pfad):")
    _test(lin["hmm"], raw["hmm"], "accuracy")

    MODELS.mkdir(exist_ok=True)
    raw["tbl"].to_csv(MODELS / "passive_raw_accel_cv.csv", index=False)
    raw["hmm"].to_csv(MODELS / "passive_raw_accel_hmm_cv.csv", index=False)
    lin["tbl"].to_csv(MODELS / "passive_linear_accel_cv.csv", index=False)
    print(f"\n→ {MODELS / 'passive_raw_accel_cv.csv'} (+ _hmm, + linear-Vergleich)")


if __name__ == "__main__":
    run()
