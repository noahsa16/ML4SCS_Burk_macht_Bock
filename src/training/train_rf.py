"""Random-Forest-Baseline für die Schreib-Erkennung.

Lädt das gemergte Dataset, baut Sliding-Window-Features, macht einen
**temporalen** 80/20-Split (zeitlich zusammenhängend, keine Leakage zwischen
benachbarten überlappenden Fenstern) und trainiert einen
``RandomForestClassifier``.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
)

from src.features.windows import load_session_windows

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"


def _load_windows(session_id: str) -> pd.DataFrame:
    """Read precomputed windows CSV if available, else build on the fly."""
    cached = DATA_PROC / f"{session_id}_windows.csv"
    if cached.exists():
        return pd.read_csv(cached)
    return load_session_windows(session_id)


def temporal_split(
    df: pd.DataFrame, test_frac: float = 0.2, gap_windows: int = 4
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sort by time, take last ``test_frac`` as test, drop a buffer around the
    cut so overlapping windows don't leak."""
    df = df.sort_values("t_center_ms").reset_index(drop=True)
    n = len(df)
    split = int(n * (1.0 - test_frac))
    train = df.iloc[: max(0, split - gap_windows)]
    test = df.iloc[split:]
    return train, test


def train(
    session_id: str = "S029",
    n_estimators: int = 200,
    random_state: int = 42,
    save_to: Path | None = None,
) -> dict:
    feats = _load_windows(session_id)
    if feats.empty:
        raise RuntimeError(f"No windows produced for {session_id}.")

    feature_cols = [c for c in feats.columns if c not in {"label", "t_center_ms"}]
    train_df, test_df = temporal_split(feats)

    X_train = train_df[feature_cols].to_numpy()
    y_train = train_df["label"].to_numpy()
    X_test = test_df[feature_cols].to_numpy()
    y_test = test_df["label"].to_numpy()

    print(
        f"Windows: total={len(feats)}  train={len(train_df)}  test={len(test_df)}\n"
        f"Label balance — train: {np.bincount(y_train).tolist()} | "
        f"test: {np.bincount(y_test).tolist()}\n"
        f"Features: {len(feature_cols)}"
    )

    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=random_state,
        class_weight="balanced",
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    print("\n=== Test set ===")
    print(classification_report(y_test, y_pred, digits=3))
    print("Confusion matrix [rows=true, cols=pred]:")
    print(confusion_matrix(y_test, y_pred))
    try:
        print(f"ROC-AUC: {roc_auc_score(y_test, y_proba):.3f}")
    except ValueError:
        print("ROC-AUC: n/a (only one class in test)")

    importances = (
        pd.Series(clf.feature_importances_, index=feature_cols)
        .sort_values(ascending=False)
        .head(10)
    )
    print("\nTop-10 feature importances:")
    print(importances.to_string())

    if save_to is None:
        save_to = MODEL_DIR / f"rf_{session_id}.joblib"
    save_to.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": clf, "feature_cols": feature_cols}, save_to)
    print(f"\nModell gespeichert: {save_to}")

    return {
        "model": clf,
        "feature_cols": feature_cols,
        "train_size": len(train_df),
        "test_size": len(test_df),
    }


if __name__ == "__main__":
    import sys

    sid = sys.argv[1] if len(sys.argv) > 1 else "S029"
    train(session_id=sid)
