"""Shared helpers for the learning-curve forecast.

Window loading, per-session z-score normalization, and the classical
sklearn model bank + fit/eval routine used by ``learning_curve.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT / "data" / "processed"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"
OUT_DIR = ROOT / "forecast"
OUT_DIR.mkdir(exist_ok=True)


def load_windows() -> pd.DataFrame:
    s = pd.read_csv(SESSIONS_CSV)
    s = s[s["verdict"].isin({"trainable", "usable"})]
    s = s[s["study_mode"].fillna("") != "test"]
    s = s[s["session_id"].apply(lambda x: (DATA_PROC / f"{x}_windows.csv").exists())]
    frames = []
    for sid in s["session_id"]:
        df = pd.read_csv(DATA_PROC / f"{sid}_windows.csv")
        df["session_id"] = sid
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.merge(s[["session_id", "person_id"]], on="session_id", how="left")


def zscore_per_session(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    g = out.groupby("session_id", sort=False)[cols]
    mu = g.transform("mean")
    sigma = g.transform("std").replace(0.0, 1.0).fillna(1.0)
    out[cols] = (out[cols] - mu) / sigma
    return out


def sklearn_models() -> dict[str, object]:
    return {
        "ExtraTrees": ExtraTreesClassifier(
            n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=42),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", n_jobs=-1, random_state=42),
        "HistGradBoost": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, random_state=42),
        "LogReg": Pipeline([
            ("sc", StandardScaler()),
            ("lr", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]),
    }


def train_test_sklearn(model, train, test, cols):
    X_tr, y_tr = train[cols].to_numpy(), train["label"].to_numpy()
    X_te, y_te = test[cols].to_numpy(), test["label"].to_numpy()
    if len(np.unique(y_te)) < 2:
        return None
    m = clone(model)
    m.fit(X_tr, y_tr)
    y_pred = m.predict(X_te)
    y_proba = m.predict_proba(X_te)[:, 1]
    return {
        "acc": float((y_pred == y_te).mean()),
        "auc": float(roc_auc_score(y_te, y_proba)),
    }
