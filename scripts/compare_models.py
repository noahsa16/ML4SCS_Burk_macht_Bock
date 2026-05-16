"""Vergleicht mehrere Modelle auf dem ersten Cross-Subject LOSO-Fold.

Lädt alle Sessions mit verdict ∈ {trainable, usable} aus sessions.csv und
trainiert pro Modell eine LOSO-by-person Kreuzvalidierung. Reportet
acc / F1(writing) / ROC-AUC pro Fold und Mittelwerte sowie eine
10-s Burst-aggregierte AUC (Decision-Window, vgl. train_loso.py).

CLI
---
    python scripts/compare_models.py
    python scripts/compare_models.py --by session
    python scripts/compare_models.py --include-all
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

ROOT = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT / "data" / "processed"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"
TRAINABLE = {"trainable", "usable"}

BURST_SCALE_SEC = 10.0


def _load_sessions(include_all: bool) -> pd.DataFrame:
    s = pd.read_csv(SESSIONS_CSV)
    if not include_all:
        if "verdict" in s.columns:
            s = s[s["verdict"].isin(TRAINABLE)]
        if "study_mode" in s.columns:
            s = s[s["study_mode"].fillna("") != "test"]
    s = s[s["session_id"].apply(lambda x: (DATA_PROC / f"{x}_windows.csv").exists())]
    return s.reset_index(drop=True)


def _zscore_per_session(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    # Why: same fix as train_loso._zscore_per_session — subject-dependent
    # baselines shift absolute feature values; standardizing per session
    # removes that domain shift so the model learns relative-to-baseline
    # patterns rather than absolute thresholds.
    out = df.copy()
    grouped = out.groupby("session_id", sort=False)[feature_cols]
    mu = grouped.transform("mean")
    sigma = grouped.transform("std").replace(0.0, 1.0).fillna(1.0)
    out[feature_cols] = (out[feature_cols] - mu) / sigma
    return out


def _load_all_windows(sessions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for sid in sessions["session_id"]:
        df = pd.read_csv(DATA_PROC / f"{sid}_windows.csv")
        df["session_id"] = sid
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.merge(sessions[["session_id", "person_id"]], on="session_id", how="left")


def _models() -> dict[str, object]:
    """Build the comparison panel. Linear/MLP get a StandardScaler in front."""
    return {
        "Dummy(most_frequent)": DummyClassifier(strategy="most_frequent"),
        "LogReg": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", n_jobs=-1, random_state=42,
        ),
        "ExtraTrees": ExtraTreesClassifier(
            n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=42,
        ),
        "HistGradBoost": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, random_state=42,
        ),
        "MLP(64,32)": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(
                hidden_layer_sizes=(64, 32), max_iter=300,
                early_stopping=True, random_state=42,
            )),
        ]),
        "SVM-RBF": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", C=1.0, gamma="scale",
                        probability=True, class_weight="balanced")),
        ]),
    }


def _burst_auc(proba: np.ndarray, y_true: np.ndarray, test_df: pd.DataFrame,
               scale_sec: float = BURST_SCALE_SEC) -> tuple[float, float]:
    """Per-Session rolling-mean smoothing, then AUC + accuracy@0.5."""
    df = test_df.reset_index(drop=True).copy()
    df["_p"] = proba
    df["_y"] = y_true
    df = df.sort_values(["session_id", "t_center_ms"]).reset_index(drop=True)
    chunks = []
    for _, g in df.groupby("session_id", sort=False):
        t = g["t_center_ms"].to_numpy()
        stride_ms = float(np.median(np.diff(t))) if len(t) >= 2 else 500.0
        n = max(1, int(round(scale_sec * 1000.0 / (stride_ms or 500.0))))
        chunks.append(g["_p"].rolling(n, center=True, min_periods=1).mean().to_numpy())
    smoothed = np.concatenate(chunks)
    y = df["_y"].to_numpy()
    try:
        auc = float(roc_auc_score(y, smoothed))
    except ValueError:
        auc = float("nan")
    acc = float(((smoothed >= 0.5).astype(int) == y).mean())
    return acc, auc


def _eval_fold(model, train_df, test_df, feat_cols) -> dict:
    y_test = test_df["label"].to_numpy()
    X_train = train_df[feat_cols].to_numpy()
    y_train = train_df["label"].to_numpy()
    X_test = test_df[feat_cols].to_numpy()

    t0 = time.perf_counter()
    model.fit(X_train, y_train)
    fit_s = time.perf_counter() - t0

    y_pred = model.predict(X_test)
    if hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(X_test)[:, 1]
    elif hasattr(model, "decision_function"):
        z = model.decision_function(X_test)
        y_proba = 1.0 / (1.0 + np.exp(-z))
    else:
        y_proba = y_pred.astype(float)

    try:
        auc = float(roc_auc_score(y_test, y_proba))
    except ValueError:
        auc = float("nan")
    b_acc, b_auc = _burst_auc(y_proba, y_test, test_df)
    return {
        "fit_s": fit_s,
        "accuracy": float((y_pred == y_test).mean()),
        "f1_writing": float(f1_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "roc_auc": auc,
        "acc_10s": b_acc,
        "auc_10s": b_auc,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--by", choices=["person", "session"], default="person")
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true",
                    help="Disable per-session z-score normalization (default: on).")
    args = ap.parse_args()

    sessions = _load_sessions(args.include_all)
    group_col = "person_id" if args.by == "person" else "session_id"
    groups = sessions[group_col].dropna().unique().tolist()
    print(f"Sessions: {sessions['session_id'].tolist()}")
    print(f"Folds ({args.by}): {groups}\n")
    if len(groups) < 2:
        raise SystemExit(f"Need ≥ 2 unique {args.by}s, got {groups}")

    all_w = _load_all_windows(sessions)
    feat_cols = [
        c for c in all_w.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    if not args.no_zscore:
        all_w = _zscore_per_session(all_w, feat_cols)
    print(f"Windows total: {len(all_w)}   Features: {len(feat_cols)}   "
          f"zscore_per_session={not args.no_zscore}\n")

    rows = []
    for name, builder in _models().items():
        print(f"=== {name} ===")
        for held in groups:
            from sklearn.base import clone
            try:
                model = clone(builder)
            except TypeError:
                model = builder
            test_mask = all_w[group_col] == held
            train_df = all_w[~test_mask]
            test_df = all_w[test_mask]
            if len(np.unique(test_df["label"])) < 2:
                print(f"  [{held}] skipped (single-class test)")
                continue
            r = _eval_fold(model, train_df, test_df, feat_cols)
            print(f"  hold-out={held:>6}  fit={r['fit_s']:6.2f}s  "
                  f"acc={r['accuracy']:.3f}  f1={r['f1_writing']:.3f}  "
                  f"auc={r['roc_auc']:.3f}  |10s burst: "
                  f"acc={r['acc_10s']:.3f}  auc={r['auc_10s']:.3f}")
            rows.append({"model": name, "held_out": held, **r})
        print()

    df = pd.DataFrame(rows)
    if df.empty:
        print("No valid folds — nothing to summarise.")
        return
    summary = (df.groupby("model", sort=False)
                 [["accuracy", "f1_writing", "roc_auc", "acc_10s", "auc_10s"]]
                 .agg(["mean", "std"]))
    print("=" * 78)
    print("Mean ± Std across folds:\n")
    pd.set_option("display.float_format", lambda v: f"{v:.3f}")
    print(summary.to_string())

    # Preserve the no-zscore baseline for comparison.
    out_name = "model_compare.csv" if args.no_zscore else "model_compare_zscore.csv"
    out_csv = ROOT / "models" / out_name
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"\n→ {out_csv}")


if __name__ == "__main__":
    main()
