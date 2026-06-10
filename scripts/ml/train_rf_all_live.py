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
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.training.train_loso import _select_sessions, _load_windows  # noqa: E402

MODELS = ROOT / "models"


def main() -> None:
    # Why: rf_all_live ist die Deployment-Variante der Headline — und die
    # ist der Legacy-Pool (50hz-Windows, inkl. Downsample-Views der
    # Modern-Sessions). Native Auflösung würde 92-Feature-Modern-Windows
    # mit 88-Feature-Legacy mischen (NaN-Gravity → RF.fit-Crash).
    sessions = _select_sessions(include_all=False, min_windows=0, profile="50hz")
    if sessions.empty:
        raise SystemExit("no eligible sessions")

    print(f"Loading windows from {len(sessions)} sessions...")
    dfs = []
    for sid in sessions["session_id"]:
        df = _load_windows(sid, "50hz")
        dfs.append(df)
    all_df = pd.concat(dfs, ignore_index=True)
    all_df = all_df.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )
    fcols = [c for c in all_df.columns
             if c not in {"label", "t_center_ms", "session_id", "person_id",
                          "task_id", "task_category"}]
    print(f"Total windows: {len(all_df)}  |  features: {len(fcols)}")
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
        "sample_rate_hz": 50,
        "zscore_mu": mu.to_dict(),
        "zscore_sigma": sigma.to_dict(),
        "normalisation": "pooled",
        "note": (
            "Live-deployment variant. Trained with POOLED z-score "
            "(vs. headline rf_all.joblib which used per-session z-score). "
            "LOSO-Headline numbers refer to the per-session model, not this one."
        ),
    }, out)
    print(f"\n-> {out}")
    print(f"   mu/sigma baked in over {len(all_df)} pooled windows")


if __name__ == "__main__":
    main()
