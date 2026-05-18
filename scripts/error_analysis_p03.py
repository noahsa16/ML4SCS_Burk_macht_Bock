"""Error analysis for the P03 LOSO fold.

Reuses the same training setup as src.training.train_loso so the numbers
match what the headline metric reports.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import confusion_matrix, f1_score

ROOT = Path(__file__).resolve().parents[1]
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

    test["proba"] = proba
    test["pred"] = pred
    test["correct"] = (pred == y_test).astype(int)
    test["error_type"] = "TN"
    test.loc[(y_test == 1) & (pred == 1), "error_type"] = "TP"
    test.loc[(y_test == 1) & (pred == 0), "error_type"] = "FN"
    test.loc[(y_test == 0) & (pred == 1), "error_type"] = "FP"
    test["task"] = test["task_id"].fillna("outside_task").replace("", "outside_task")

    print(f"\n=== Error Analysis: {person} (held out from LOSO) ===\n")
    cm = confusion_matrix(y_test, pred)
    print("Confusion matrix (rows=true, cols=pred):")
    print(f"             pred=0   pred=1")
    print(f"  true=0    {cm[0,0]:>6}   {cm[0,1]:>6}")
    print(f"  true=1    {cm[1,0]:>6}   {cm[1,1]:>6}")
    print(f"\nOverall: acc={(pred==y_test).mean():.3f}  f1(writing)={f1_score(y_test, pred):.3f}")
    print(f"FP rate (predicted writing when idle): {cm[0,1]/cm[0].sum():.3f}")
    print(f"FN rate (missed writing): {cm[1,0]/cm[1].sum():.3f}")

    print("\n--- Per-Task Performance ---")
    grouped = test.groupby("task").agg(
        n_windows=("label", "size"),
        pct_writing_true=("label", "mean"),
        pct_writing_pred=("pred", "mean"),
        accuracy=("correct", "mean"),
        mean_proba=("proba", "mean"),
    ).round(3).sort_values("n_windows", ascending=False)
    print(grouped.to_string())

    print("\n--- Error Types by Task ---")
    err_table = test.pivot_table(
        index="task", columns="error_type", values="t_center_ms",
        aggfunc="count", fill_value=0,
    )
    print(err_table.to_string())

    print("\n--- Model Confidence ---")
    correct_proba = test[test["correct"] == 1]["proba"]
    error_proba = test[test["correct"] == 0]["proba"]
    print(f"Correct predictions:  mean_proba={correct_proba.mean():.3f}  "
          f"|distance_from_0.5|_mean={(correct_proba - 0.5).abs().mean():.3f}")
    print(f"Wrong predictions:    mean_proba={error_proba.mean():.3f}  "
          f"|distance_from_0.5|_mean={(error_proba - 0.5).abs().mean():.3f}")

    print("\n--- Longest Consecutive Error Streaks ---")
    test_sorted = test.sort_values("t_center_ms").reset_index(drop=True)
    streaks = []
    cur_start, cur_len, cur_type, cur_task = None, 0, None, None
    for _, row in test_sorted.iterrows():
        if row["correct"] == 0:
            etype = row["error_type"]
            if cur_type == etype:
                cur_len += 1
            else:
                if cur_len > 0:
                    streaks.append((cur_start, cur_len, cur_type, cur_task))
                cur_start, cur_len, cur_type, cur_task = (
                    row["t_center_ms"], 1, etype, row["task"],
                )
        else:
            if cur_len > 0:
                streaks.append((cur_start, cur_len, cur_type, cur_task))
            cur_start, cur_len, cur_type = None, 0, None
    if cur_len > 0:
        streaks.append((cur_start, cur_len, cur_type, cur_task))

    streaks.sort(key=lambda x: -x[1])
    for _, length, etype, task in streaks[:10]:
        secs = length * 0.5  # 0.5 s stride
        print(f"  {etype}  streak={length} windows (~{secs:.1f}s)  task={task}")


def main() -> None:
    frames = [_load_windows(s) for s in SESSIONS]
    df = pd.concat(frames, ignore_index=True)
    feat_cols = [c for c in df.columns if c not in NON_FEATURE_COLS]
    df = _zscore_per_session(df, feat_cols)

    targets = sys.argv[1:] or SESSIONS
    for sid in targets:
        analyze(sid, df, feat_cols)


if __name__ == "__main__":
    main()
