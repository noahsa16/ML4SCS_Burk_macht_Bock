"""Check whether errors cluster near task boundaries (alignment hypothesis).

If pen/watch alignment is off by 1-2s, errors should pile up within a few
seconds of task transitions — the label flips while the model is still
predicting the old state. If errors are uniformly distributed inside the
task, the model is making genuine mistakes (not alignment artefacts).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.train_loso import _zscore_per_session, _load_windows  # type: ignore

SESSIONS = ["S007", "S008", "S009", "S011"]
SESSION_TO_PERSON = {"S007": "Noah", "S008": "P01", "S009": "P02", "S011": "P03"}
NON_FEATURE_COLS = {"session_id", "label", "t_center_ms", "task_id", "task_category"}


def analyze(held_out: str, df: pd.DataFrame, feat_cols: list[str]) -> None:
    person = SESSION_TO_PERSON[held_out]
    train = df[df["session_id"] != held_out]
    test = df[df["session_id"] == held_out].copy().reset_index(drop=True)

    clf = ExtraTreesClassifier(
        n_estimators=400, class_weight="balanced",
        n_jobs=-1, random_state=42,
    )
    clf.fit(train[feat_cols].to_numpy(), train["label"].to_numpy())
    proba = clf.predict_proba(test[feat_cols].to_numpy())[:, 1]
    pred = (proba >= 0.5).astype(int)
    y_test = test["label"].to_numpy()
    test["pred"] = pred
    test["correct"] = (pred == y_test).astype(int)
    test["task"] = test["task_id"].fillna("outside_task").replace("", "outside_task")

    # Find task transitions: positions where task changes from previous row
    test = test.sort_values("t_center_ms").reset_index(drop=True)
    task_changed = test["task"].ne(test["task"].shift())
    boundaries_ms = test.loc[task_changed, "t_center_ms"].to_numpy()

    # Distance (in ms) of each window to the nearest task boundary
    def dist_to_nearest(t: float) -> float:
        if len(boundaries_ms) == 0:
            return float("nan")
        return float(np.min(np.abs(boundaries_ms - t)))

    test["dist_to_boundary_s"] = test["t_center_ms"].apply(dist_to_nearest) / 1000.0

    # Bucket: 0-2s, 2-5s, 5-15s, >15s from a boundary
    bins = [0, 2, 5, 15, 1e9]
    labels = ["0-2s", "2-5s", "5-15s", ">15s"]
    test["bucket"] = pd.cut(test["dist_to_boundary_s"], bins=bins, labels=labels, right=False)

    summary = test.groupby("bucket", observed=True).agg(
        n=("correct", "size"),
        accuracy=("correct", "mean"),
        error_rate=("correct", lambda x: 1 - x.mean()),
    ).round(3)
    summary["share_of_errors"] = (
        test[test["correct"] == 0].groupby("bucket", observed=True).size() / (1 - test["correct"]).sum()
    ).round(3)
    summary["share_of_windows"] = (summary["n"] / summary["n"].sum()).round(3)

    print(f"\n=== {person} ({held_out}): error vs. distance to task-boundary ===")
    print(summary.to_string())

    # Alignment-shift signature: if labels are shifted, the very first/last
    # seconds of each writing task should be systematically wrong in one direction.
    # Look at error type at task starts (within 2s).
    near_boundary = test[test["dist_to_boundary_s"] < 2.0].copy()
    near_boundary["err_dir"] = "ok"
    near_boundary.loc[(y_test[near_boundary.index] == 1) & (near_boundary["pred"] == 0), "err_dir"] = "FN"
    near_boundary.loc[(y_test[near_boundary.index] == 0) & (near_boundary["pred"] == 1), "err_dir"] = "FP"

    err_at_boundary = near_boundary[near_boundary["err_dir"] != "ok"]["err_dir"].value_counts()
    print(f"  Within 2s of boundary: {len(near_boundary)} windows, "
          f"{len(near_boundary) - near_boundary['correct'].sum()} errors  "
          f"(FN={err_at_boundary.get('FN', 0)}, FP={err_at_boundary.get('FP', 0)})")


def main() -> None:
    frames = [_load_windows(s) for s in SESSIONS]
    df = pd.concat(frames, ignore_index=True)
    feat_cols = [c for c in df.columns if c not in NON_FEATURE_COLS]
    df = _zscore_per_session(df, feat_cols)
    for sid in SESSIONS:
        analyze(sid, df, feat_cols)


if __name__ == "__main__":
    main()
