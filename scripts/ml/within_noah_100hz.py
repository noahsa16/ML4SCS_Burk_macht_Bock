"""Within-Subject 100-Hz-A/B: S032 train -> S033 test (und umgekehrt).

Gleiche Person, gleiches Watch, gleiches Protokoll, gleiche Rate. Einzige
Variabel: Session/Content/Tag (ca. 45min Abstand). Sauberer Test ob die
100-Hz-Pipeline within-subject ueberhaupt generalisiert.

Plus: rf_all (50 Hz LOSO-Korpus) wendet sich kalt auf beide an als Baseline.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.training.train_loso import _zscore_per_session, _burst_metrics  # noqa: E402

PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"


def load(session_id: str) -> pd.DataFrame:
    df = pd.read_csv(PROC / f"{session_id}_windows.csv")
    df["session_id"] = session_id
    return df


def feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in
            {"label", "t_center_ms", "session_id", "person_id",
             "task_id", "task_category"}]


def metrics(name: str, y_true, proba, w_test: pd.DataFrame) -> None:
    pred = (proba >= 0.5).astype(int)
    acc = accuracy_score(y_true, pred)
    f1 = f1_score(y_true, pred)
    auc = roc_auc_score(y_true, proba)
    print(f"\n=== {name} ===")
    print(f"  acc {acc:.3f}   F1(w) {f1:.3f}   AUC {auc:.3f}")
    burst = _burst_metrics(proba, y_true, w_test, scales_sec=(1.0, 5.0, 10.0, 30.0))
    print(f"  burst @1s/5s/10s/30s  AUC: "
          + "  ".join(f"{burst[k]['roc_auc']:.3f}" for k in burst))


s32 = load("S032")
s33 = load("S033")
fcols = feature_cols(s32)
print(f"Features: {len(fcols)}")
print(f"S032: {len(s32)} windows  {100*s32.label.mean():.1f}% writing")
print(f"S033: {len(s33)} windows  {100*s33.label.mean():.1f}% writing")


def train_test(train_df: pd.DataFrame, test_df: pd.DataFrame) -> tuple:
    # Per-session z-score (only one session each side -> standardize)
    tr = _zscore_per_session(train_df, fcols)
    te = _zscore_per_session(test_df, fcols)
    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    clf.fit(tr[fcols].to_numpy(), tr["label"].to_numpy())
    proba = clf.predict_proba(te[fcols].to_numpy())[:, 1]
    return clf, proba


# 1) S032 -> S033
_, p_a = train_test(s32, s33)
metrics("Train S032 (100Hz) -> Test S033 (100Hz)", s33.label.to_numpy(), p_a, s33)

# 2) S033 -> S032
_, p_b = train_test(s33, s32)
metrics("Train S033 (100Hz) -> Test S032 (100Hz)", s32.label.to_numpy(), p_b, s32)

# 3) Baseline: 50-Hz-Korpus -> S033 (kalt, wie E1)
bundle = joblib.load(MODELS / "rf_all.joblib")
clf50 = bundle["model"]
fcols50 = bundle["feature_cols"]
te = _zscore_per_session(s33, fcols50)
proba50 = clf50.predict_proba(te[fcols50].to_numpy())[:, 1]
metrics("Baseline: rf_all (50Hz-Korpus, 10 Probanden) -> S033", s33.label.to_numpy(), proba50, s33)
