"""Aggregierte LOSO-Confusion-Matrix für die Präsentation.

Trainiert den Headline-RF in einer LOSO-by-person-Schleife, sammelt
alle Test-Predictions über die Folds und rendert die 2x2-Matrix als
Heatmap. Zwei Panels: links absolute Counts, rechts row-normalisierte
Recalls. Eine zusätzliche Footer-Zeile fasst die globalen Metriken
(Acc, F1, AUC) zusammen.

CLI
---
    python scripts/plot_confusion_matrix.py
    python scripts/plot_confusion_matrix.py --no-zscore
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.training.train_loso import (  # noqa: E402
    _load_windows,
    _select_sessions,
    _zscore_per_session,
)

OUT_PATH = ROOT / "reports" / "figures" / "confusion_matrix_loso.png"


def _collect_predictions(
    sessions: pd.DataFrame,
    feature_cols: list[str],
    all_windows: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y_true, y_pred, y_proba = [], [], []
    persons = sorted(sessions["person_id"].dropna().unique())
    for held in persons:
        test_mask = all_windows["person_id"] == held
        train = all_windows.loc[~test_mask]
        test = all_windows.loc[test_mask]
        clf = RandomForestClassifier(
            n_estimators=200,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
        )
        clf.fit(train[feature_cols], train["label"])
        y_true.append(test["label"].to_numpy())
        y_pred.append(clf.predict(test[feature_cols]))
        y_proba.append(clf.predict_proba(test[feature_cols])[:, 1])
        print(f"  fold {held:6s}  n_test={len(test):5d}")
    return (
        np.concatenate(y_true),
        np.concatenate(y_pred),
        np.concatenate(y_proba),
    )


def _annotate(ax: plt.Axes, m: np.ndarray, fmt: str, total: float | None = None) -> None:
    vmax = m.max()
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            val = m[i, j]
            color = "white" if val > vmax * 0.55 else "#0f172a"
            txt = fmt.format(val)
            if total is not None:
                txt += f"\n({val / total:.1%})"
            ax.text(j, i, txt, ha="center", va="center",
                    color=color, fontsize=14, fontweight="bold")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true")
    ap.add_argument("--min-windows", type=int, default=0)
    args = ap.parse_args()

    sessions = _select_sessions(args.include_all, args.min_windows)
    if sessions.empty:
        raise SystemExit("Keine trainierbaren Sessions gefunden.")
    frames = []
    for _, row in sessions.iterrows():
        df = _load_windows(row["session_id"])
        df["session_id"] = row["session_id"]
        df["person_id"] = row["person_id"]
        frames.append(df)
    all_windows = pd.concat(frames, ignore_index=True)

    feature_cols = [
        c for c in all_windows.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    if not args.no_zscore:
        all_windows = _zscore_per_session(all_windows, feature_cols)

    persons = sorted(sessions["person_id"].dropna().unique())
    print(f"Sessions: {len(sessions)}   Probanden: {len(persons)}   "
          f"Windows: {len(all_windows)}   zscore={not args.no_zscore}")

    y_true, y_pred, y_proba = _collect_predictions(
        sessions, feature_cols, all_windows
    )

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    cm_norm = cm / cm.sum(axis=1, keepdims=True)
    total = cm.sum()
    acc = accuracy_score(y_true, y_pred)
    f1_w = f1_score(y_true, y_pred, pos_label=1)
    auc = roc_auc_score(y_true, y_proba)

    print("\n=== Aggregierte LOSO Confusion Matrix ===")
    print(f"TN={cm[0,0]:5d}  FP={cm[0,1]:5d}")
    print(f"FN={cm[1,0]:5d}  TP={cm[1,1]:5d}")
    print(f"Acc={acc:.3f}  F1(w)={f1_w:.3f}  AUC={auc:.3f}")

    labels = ["idle", "writing"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))

    # Left: absolute counts
    ax = axes[0]
    im = ax.imshow(cm, cmap="Blues", aspect="equal")
    ax.set_xticks([0, 1], labels)
    ax.set_yticks([0, 1], labels)
    ax.set_xlabel("Predicted", fontsize=11, fontweight="bold")
    ax.set_ylabel("True", fontsize=11, fontweight="bold")
    ax.set_title("Absolute Counts", fontsize=12)
    _annotate(ax, cm, "{:,d}", total=float(total))
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # Right: row-normalized (recall)
    ax = axes[1]
    im = ax.imshow(cm_norm, cmap="Blues", aspect="equal", vmin=0, vmax=1)
    ax.set_xticks([0, 1], labels)
    ax.set_yticks([0, 1], labels)
    ax.set_xlabel("Predicted", fontsize=11, fontweight="bold")
    ax.set_ylabel("True", fontsize=11, fontweight="bold")
    ax.set_title("Row-normalized (Recall per Class)", fontsize=12)
    _annotate(ax, cm_norm, "{:.1%}")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    fig.suptitle(
        f"LOSO-by-person Confusion Matrix — Random Forest, N={len(persons)} Probanden, "
        f"{total:,} Windows\n"
        f"Accuracy {acc:.3f}   F1(writing) {f1_w:.3f}   ROC-AUC {auc:.3f}",
        fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=160, bbox_inches="tight")
    print(f"→ {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
