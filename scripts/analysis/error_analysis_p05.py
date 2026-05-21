"""Per-task error analysis for the P05 (S017) LOSO fold.

Mirrors src.training.train_loso headline config (RF-200, per-session
z-score, max_gap_ms=2000 already baked into the cached windows CSVs)
so the numbers match the headline metric.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.train_loso import _zscore_per_session, _load_windows  # type: ignore

SESSIONS = ["S007", "S008", "S009", "S011", "S013", "S015", "S017"]
SESSION_TO_PERSON = {
    "S007": "Noah", "S008": "P01", "S009": "P02", "S011": "P03",
    "S013": "Taji", "S015": "P04", "S017": "P05",
}
NON_FEATURE_COLS = {"session_id", "label", "t_center_ms", "task_id", "task_category"}


def analyze(held_out: str, df: pd.DataFrame, feat_cols: list[str]) -> None:
    person = SESSION_TO_PERSON[held_out]
    train = df[df["session_id"] != held_out]
    test = df[df["session_id"] == held_out].copy().reset_index(drop=True)

    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced",
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
    test["cat"] = test["task_category"].fillna("outside").replace("", "outside")

    print(f"\n=== Error Analysis: {person} ({held_out}) — held out from N=7 LOSO ===\n")
    cm = confusion_matrix(y_test, pred)
    print("Confusion matrix (rows=true, cols=pred):")
    print(f"             pred=0   pred=1")
    print(f"  true=0    {cm[0,0]:>6}   {cm[0,1]:>6}")
    print(f"  true=1    {cm[1,0]:>6}   {cm[1,1]:>6}")
    print(f"\nOverall: acc={(pred==y_test).mean():.3f}  f1(writing)={f1_score(y_test, pred):.3f}")
    print(f"FP rate (predicted writing when idle): {cm[0,1]/cm[0].sum():.3f}")
    print(f"FN rate (missed writing): {cm[1,0]/cm[1].sum():.3f}")

    print("\n--- Per-Category Performance (writing tasks vs. idle/pause) ---")
    by_cat = test.groupby("cat").agg(
        n=("label", "size"),
        pct_true_writing=("label", "mean"),
        pct_pred_writing=("pred", "mean"),
        acc=("correct", "mean"),
        mean_proba=("proba", "mean"),
    ).round(3)
    print(by_cat.to_string())

    print("\n--- Per-Task Performance ---")
    by_task = test.groupby(["cat", "task"]).agg(
        n=("label", "size"),
        pct_true_writing=("label", "mean"),
        pct_pred_writing=("pred", "mean"),
        acc=("correct", "mean"),
        mean_proba=("proba", "mean"),
    ).round(3).sort_values("n", ascending=False)
    print(by_task.to_string())

    print("\n--- Error Types by Task ---")
    err_table = test.pivot_table(
        index=["cat", "task"], columns="error_type", values="t_center_ms",
        aggfunc="count", fill_value=0,
    )
    for col in ("TP", "TN", "FP", "FN"):
        if col not in err_table.columns:
            err_table[col] = 0
    err_table = err_table[["TP", "TN", "FP", "FN"]]
    err_table["FP_rate_of_idle"] = (
        err_table["FP"] / (err_table["FP"] + err_table["TN"]).replace(0, np.nan)
    ).round(3)
    err_table["FN_rate_of_writing"] = (
        err_table["FN"] / (err_table["FN"] + err_table["TP"]).replace(0, np.nan)
    ).round(3)
    print(err_table.to_string())

    print("\n--- FP Concentration: where are the 'predicted writing while idle' coming from? ---")
    fp = test[test["error_type"] == "FP"]
    total_fp = len(fp)
    if total_fp:
        share = (fp.groupby(["cat", "task"]).size() / total_fp).sort_values(ascending=False).round(3)
        print(f"Total FPs: {total_fp}")
        print(share.to_string())

    print("\n--- FN Concentration: where are the 'missed writing' coming from? ---")
    fn = test[test["error_type"] == "FN"]
    total_fn = len(fn)
    if total_fn:
        share = (fn.groupby(["cat", "task"]).size() / total_fn).sort_values(ascending=False).round(3)
        print(f"Total FNs: {total_fn}")
        print(share.to_string())

    print("\n--- Model Confidence ---")
    correct_proba = test[test["correct"] == 1]["proba"]
    error_proba = test[test["correct"] == 0]["proba"]
    print(f"Correct: mean_proba={correct_proba.mean():.3f}  "
          f"|distance_from_0.5|_mean={(correct_proba - 0.5).abs().mean():.3f}")
    print(f"Errors:  mean_proba={error_proba.mean():.3f}  "
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
    for _, length, etype, task in streaks[:12]:
        secs = length * 0.5
        print(f"  {etype}  streak={length} windows (~{secs:.1f}s)  task={task}")


def main() -> None:
    frames = [_load_windows(s) for s in SESSIONS]
    df = pd.concat(frames, ignore_index=True)
    feat_cols = [c for c in df.columns if c not in NON_FEATURE_COLS]
    df = _zscore_per_session(df, feat_cols)

    targets = sys.argv[1:] or ["S017"]
    for sid in targets:
        analyze(sid, df, feat_cols)


if __name__ == "__main__":
    main()
