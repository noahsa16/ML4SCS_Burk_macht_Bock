"""Passiv-Deployment-PoC: train==deploy auf ROH-Accel (N=5 Modern).

**Kontext / warum dieses Skript existiert.** Der passive Ganztags-Tracker nutzt
`CMSensorRecorder`, das **rohe Gesamtbeschleunigung** liefert (userAccel + Schwerkraft,
ohne Gyro-Fusion). Das Headline-Modell ist auf `userAcceleration` trainiert (Gyro-fusioniert).
Deployt man das userAccel-Modell auf Roh-Accel, bricht es um 8–20 pp ein (train/deploy-
Mismatch; Within-Window-Schwerkraft-Rotation — die Features sind nur gegen *konstanten*
Offset invariant). Auflösung: das Modell **auf Roh trainieren** (train==deploy).

Dieses Skript belegt das auf den N=5 Modern-Sessions (die einzigen mit aufgezeichneter
Gravity → rekonstruierbarem Roh = userAccel + gravity). LOSO-by-person, vergleicht:
userAccel-47 (clean Baseline) vs raw-47 (alle acc-only) vs raw-30 (invariant). Befund
2026-06-24: raw-47 0.818/0.851 ≈ userAccel-47 0.820/0.850 (kein inhärenter Roh-Preis);
**raw-30 0.836/0.867 ist am besten** (Orientierungs-Features schaden cross-subject).

**Deployment-Rezept (wenn mehr Modern-Sessions da):** `train_acc_only_live.py` auf diesen
raw-30-Pfad umstellen (rekonstruiertes Roh über den Modern-Pool, 30 invariante Features,
pooled Z-Score) → `rf_acc_only_live.joblib`. Siehe Memory `passive-tracker-design`.

CLI: ``python scripts/ml/passive_raw_poc.py``
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ml"))

from acc_only_loso import _run_arm, _hmm_filter_per_fold, _is_gyro_feature  # noqa: E402
from src.features.windows import build_windows  # noqa: E402
from src.training.train_loso import _zscore_per_session  # noqa: E402

DATA = ROOT / "data" / "processed"
MODERN = [("S038", "P12"), ("S039", "P13"), ("S040", "P14"),
          ("S041", "P15"), ("S043", "P17")]
GRAV = ["gx", "gy", "gz"]
META = {"label", "t_center_ms", "session_id", "person_id", "task_id", "task_category"}


def _is_gravity_sensitive(name: str) -> bool:
    """Offset-sensitiv (auf Roh ≠ userAccel): absolute Achsen-Lage + Magnitude."""
    for ax in ("ax", "ay", "az"):
        if name in (f"{ax}_mean", f"{ax}_min", f"{ax}_max", f"{ax}_rms"):
            return True
    return name.startswith("acc_mag")


def _windows(use_raw: bool) -> pd.DataFrame:
    frames = []
    for sid, pid in MODERN:
        m = pd.read_csv(DATA / f"{sid}_merged.csv")
        if use_raw:
            m = m.copy()
            m[["ax", "ay", "az"]] = (m[["ax", "ay", "az"]].to_numpy(float)
                                     + m[GRAV].to_numpy(float))
        w = build_windows(m.drop(columns=[c for c in GRAV if c in m.columns]))
        w["session_id"], w["person_id"] = sid, pid
        frames.append(w)
    return pd.concat(frames, ignore_index=True)


def _arm(w: pd.DataFrame, cols: list[str], groups: list, label: str) -> None:
    w = _zscore_per_session(w.copy(), [c for c in w.columns if c not in META])
    tbl, oof = _run_arm(w, cols, groups, "person_id", None)
    hmm = _hmm_filter_per_fold(oof)
    print(f"  {label:24s} @1s acc={tbl['accuracy'].mean():.3f} "
          f"AUC={tbl['roc_auc'].mean():.3f} | +HMM acc={hmm['hmm_acc'].mean():.3f}")


def run() -> None:
    groups = [p for _, p in MODERN]
    w_user, w_raw = _windows(False), _windows(True)
    feat = [c for c in w_user.columns if c not in META]
    acc47 = [c for c in feat if not _is_gyro_feature(c)]
    inv30 = [c for c in acc47 if not _is_gravity_sensitive(c)]
    print(f"N=5 Modern LOSO | acc-only={len(acc47)} invariant={len(inv30)}\n")
    print("=== Baseline (userAccel, clean) ===")
    _arm(w_user, acc47, groups, "userAccel-47")
    print("=== Option 2: train==deploy auf ROH-Accel ===")
    _arm(w_raw, acc47, groups, "raw-47 (orient+motion)")
    _arm(w_raw, inv30, groups, "raw-30 (invariant)  <-- Deployment-Wahl")


if __name__ == "__main__":
    run()
