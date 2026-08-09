"""Trainiert rf_acc_only_live.joblib — Deployment-Modell für den Passiv-Pfad.

Der passive Ganztags-Tracker (CMSensorRecorder, accel-only) hat **kein Gyroskop**
und liefert **rohe Gesamtbeschleunigung** (inkl. Schwerkraft), nicht
userAcceleration. Damit das Modell ohne Filter und ohne Gravity-Diskrepanz
deployt, trainiert es auf den **30 schwerkraft-offset-invarianten Features**
(std/range/FFT-DC-removed/zcr/jerk/corr — auf Roh-Accel == userAccel by
construction). Gedroppt sind Gyro (kein Sensor) und die offset-sensitiven Features
(mean/min/max/rms je Achse + alle acc_mag — schwerkraft-dominiert). Pooled Z-Score
eingebacken → live-deploybar ohne Calibration-Phase (wie rf_all_live).

Begründung des Pivots (Option b statt High-Pass): die Decision-Scale-Validierung
zeigte, dass ein Komplementär-High-Pass 4–7 pp systematisch kostet (HMM verstärkt
den Fehler). Die invariante Teilmenge kostet dagegen nur +0.4 pp LOSO (n.s.),
deployt aber strukturell sauber. Per-fold: nur P09 −1.6 pp (Soft-Writer-Amplitude),
P17 +1.1 pp, kein Kollaps.

Trainings-Pool: Legacy (50hz, N=15) — datenreichste Quelle, CMSensorRecorder ~50 Hz
→ Raten-Match.

Output: ``models/rf_acc_only_live.joblib`` (model + feature_cols + zscore_mu/sigma
+ Metadaten). rf_all.joblib / rf_all_live.joblib bleiben unangetastet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from acc_only_loso import _is_gyro_feature  # noqa: E402
from src.training.train_loso import _select_sessions, _load_windows  # noqa: E402

MODELS = ROOT / "models"


def _is_gravity_sensitive(name: str) -> bool:
    """Schwerkraft-offset-sensitiv → auf Roh-Accel ≠ userAccel, daher gedroppt.

    Die absolute Achsen-Lage (mean/min/max/rms) trägt den ~1g-Offset; acc_mag ist
    nichtlinear in der Schwerkraft. std/range/FFT(DC-removed)/zcr/jerk/corr sind
    dagegen offset-invariant (konstanter Offset ändert sie nicht) → bleiben.
    """
    for ax in ("ax", "ay", "az"):
        if name in (f"{ax}_mean", f"{ax}_min", f"{ax}_max", f"{ax}_rms"):
            return True
    return name.startswith("acc_mag")


def main() -> None:
    sessions = _select_sessions(include_all=False, min_windows=0, profile="50hz")
    if sessions.empty:
        raise SystemExit("no eligible sessions")

    print(f"Loading windows from {len(sessions)} sessions...")
    dfs = [_load_windows(sid, "50hz") for sid in sessions["session_id"]]
    all_df = pd.concat(dfs, ignore_index=True)
    all_df = all_df.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )

    meta = {"label", "t_center_ms", "session_id", "person_id",
            "task_id", "task_category"}
    full_cols = [c for c in all_df.columns if c not in meta]
    fcols = [c for c in full_cols
             if not _is_gyro_feature(c) and not _is_gravity_sensitive(c)]
    n_gyro = sum(_is_gyro_feature(c) for c in full_cols)
    n_grav = sum(_is_gravity_sensitive(c) for c in full_cols
                 if not _is_gyro_feature(c))
    print(f"Total windows: {len(all_df)}  |  gravity-invariant features: {len(fcols)} "
          f"(dropped {n_gyro} gyro + {n_grav} gravity-sensitive)")
    print(f"Class balance: {100*all_df.label.mean():.1f}% writing")

    # Pooled mu/sigma (NOT per-session) → live-deployable, baked into the joblib.
    mu = all_df[fcols].mean()
    sigma = all_df[fcols].std().replace(0.0, 1.0).fillna(1.0)
    X = ((all_df[fcols] - mu) / sigma).to_numpy()
    y = all_df["label"].to_numpy()

    print("\nTraining RF (200 trees, balanced)...")
    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced", random_state=42, n_jobs=-1,
    )
    clf.fit(X, y)

    pred = clf.predict(X)
    proba = clf.predict_proba(X)[:, 1]
    print(f"In-sample acc: {accuracy_score(y, pred):.3f}  "
          f"f1: {f1_score(y, pred):.3f}  auc: {roc_auc_score(y, proba):.3f}")

    out = MODELS / "rf_acc_only_live.joblib"
    joblib.dump({
        "model": clf,
        "feature_cols": fcols,
        "trained_on": sorted(sessions["session_id"].tolist()),
        "n_windows": len(all_df),
        "person_id": None,
        "sample_rate_hz": 50,
        "zscore_mu": mu.to_dict(),
        "zscore_sigma": sigma.to_dict(),
        "normalisation": "pooled",
        "channels": "accel_only",
        "features": "gravity_invariant",
        "note": (
            "Passive deployment model (CMSensorRecorder accel-only, RAW total accel). "
            "30 gravity-offset-invariant features (no gyro; dropped mean/min/max/rms "
            "per axis + acc_mag), POOLED z-score baked in. Deploys without a gravity "
            "filter and without raw-vs-userAccel discrepancy by construction. Legacy "
            "pool N=15. LOSO cost vs full-47 acc-only: +0.4pp (n.s.). Companion HMM "
            "params: models/hmm_live.json."
        ),
    }, out)
    print(f"\n-> {out}")
    print(f"   {len(fcols)} gravity-invariant features, pooled mu/sigma over {len(all_df)} windows")


if __name__ == "__main__":
    main()
