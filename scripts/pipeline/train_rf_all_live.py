"""Trainiert rf_all_live.joblib - Deployment-Variante des generischen Modells.

Das Headline rf_all.joblib wurde mit PER-SESSION Z-Score trainiert (jede
Session bekommt ihren eigenen mu/sigma vor dem Training). Im Live-Betrieb
gibt es aber genau diese "Session-Statistiken" nicht - eine neue Session
hat noch keine Historie, gegen die sie normalisieren koennte.

Diese Variante trainiert deshalb mit POOLED Z-Score (mu/sigma ueber den
gesamten Korpus, nicht per Session). Damit ist die Trainings-Verteilung
identisch mit der Live-Inferenz-Verteilung (statisches mu/sigma im Joblib).

Erwarteter Trade-off vs. Headline rf_all:
  - LOSO-Acc/AUC vermutlich leicht schlechter (per-session Z-Score
    entfernt subject-Baselines staerker als pooled), aber:
  - im Live-Deployment ehrlich, keinerlei Calibration-Phase noetig

Das Original rf_all.joblib bleibt unangetastet (Headline-Artefakt).

Profil-Wahl (``--profile``):
  - ``100hz_grav`` (DEFAULT): die 13 nativen Modern-Sessions (100 Hz, je eine
    andere Person). Die 4 Gravity-Features werden GEDROPPT -> 88 Features,
    identisch zum Legacy-Feature-Set. Damit ist ``is_modern`` in der Inferenz
    False (kein Gravity-Guard), das Modell laeuft im bestehenden 88-Feature-
    Pfad, aber mit ``sample_rate_hz=100`` -> matcht den aktuellen 100-Hz-Watch-
    Stream (der 50-Hz-Vorgaenger triggerte dort den rate_mismatch-Guard).
    Cross-subject bringt Gravity nichts (reports/feature_ablation.md), deshalb
    bewusst weggelassen.
  - ``50hz``: der Legacy-Pool (22 Sessions, 50hz-Windows inkl. Downsample-Views
    der Modern-Sessions) -> die urspruengliche 50-Hz-Variante, reproduzierbar.

Beide schreiben in denselben Deployment-Slot ``models/rf_all_live.joblib``
(der generische Live-Picker-Eintrag "generic").
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.features.gravity import GRAVITY_FEATURE_NAMES  # noqa: E402
from src.training.train_loso import _select_sessions, _load_windows  # noqa: E402

MODELS = ROOT / "models"

# Profil -> native Sample-Rate, die im Joblib landet (rate_mismatch-Guard).
_PROFILE_RATE_HZ = {"100hz_grav": 100, "100hz": 100, "50hz": 50}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--profile", default="100hz_grav",
        choices=sorted(_PROFILE_RATE_HZ),
        help="Windows-Profil (Default 100hz_grav = generisches 100-Hz-Modell)",
    )
    args = ap.parse_args()
    profile = args.profile
    sample_rate_hz = _PROFILE_RATE_HZ[profile]

    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    if sessions.empty:
        raise SystemExit(f"no eligible sessions for profile {profile!r}")

    print(f"Profile {profile!r} ({sample_rate_hz} Hz) — "
          f"loading windows from {len(sessions)} sessions "
          f"({sessions['person_id'].nunique()} distinct persons)...")
    dfs = []
    for sid in sessions["session_id"]:
        df = _load_windows(sid, profile)
        dfs.append(df)
    all_df = pd.concat(dfs, ignore_index=True)
    all_df = all_df.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )
    # Why: Gravity ist cross-subject kein Generalisierungssignal
    # (reports/feature_ablation.md, Δacc −0.005) und wuerde das Modell auf
    # is_modern=92-Feature stellen — dann braucht die Live-Inferenz einen
    # Gravity-Stream + Guard. Bewusst auf die 88 Legacy-Features reduzieren,
    # damit das 100-Hz-Modell im bestehenden 88-Feature-Pfad laeuft.
    drop = {"label", "t_center_ms", "session_id", "person_id",
            "task_id", "task_category", *GRAVITY_FEATURE_NAMES}
    fcols = [c for c in all_df.columns if c not in drop]
    print(f"Total windows: {len(all_df)}  |  features: {len(fcols)} "
          f"(gravity dropped: {sorted(set(all_df.columns) & set(GRAVITY_FEATURE_NAMES))})")
    print(f"Class balance: {100*all_df.label.mean():.1f}% writing")

    # Pooled mu/sigma across the entire corpus (NOT per-session).
    mu = all_df[fcols].mean()
    sigma = all_df[fcols].std().replace(0.0, 1.0).fillna(1.0)
    X = ((all_df[fcols] - mu) / sigma).to_numpy()
    y = all_df["label"].to_numpy()

    print("\nTraining RF (200 trees, balanced)...")
    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    clf.fit(X, y)

    # Quick sanity on in-sample fit (just to confirm training succeeded).
    pred = clf.predict(X)
    proba = clf.predict_proba(X)[:, 1]
    print(f"In-sample acc: {accuracy_score(y, pred):.3f}  "
          f"f1: {f1_score(y, pred):.3f}  "
          f"auc: {roc_auc_score(y, proba):.3f}")

    out = MODELS / "rf_all_live.joblib"
    joblib.dump({
        "model": clf,
        "feature_cols": fcols,
        "trained_on": sorted(sessions["session_id"].tolist()),
        "n_windows": len(all_df),
        "person_id": None,
        "sample_rate_hz": sample_rate_hz,
        "zscore_mu": mu.to_dict(),
        "zscore_sigma": sigma.to_dict(),
        "normalisation": "pooled",
        "note": (
            f"Generic live-deployment model ({profile}, {sample_rate_hz} Hz, "
            f"{len(fcols)} features, gravity dropped). POOLED z-score baked in "
            "(vs. headline rf_all.joblib which used per-session z-score). "
            "LOSO-Headline numbers refer to the per-session model, not this one."
        ),
    }, out)
    print(f"\n-> {out}")
    print(f"   {sample_rate_hz} Hz | {len(fcols)} feat | "
          f"mu/sigma baked in over {len(all_df)} pooled windows")


if __name__ == "__main__":
    main()
