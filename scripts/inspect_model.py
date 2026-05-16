"""
Visualize a trained RF model from models/rf_{session}.joblib.

Usage:
    python scripts/inspect_model.py S037
    python scripts/inspect_model.py S037 --tree-idx 0 --max-depth 4
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    ConfusionMatrixDisplay, RocCurveDisplay, confusion_matrix,
)
from sklearn.tree import plot_tree

ROOT = Path(__file__).parents[1]


def _temporal_split(df: pd.DataFrame, frac: float = 0.8, gap: int = 4):
    df = df.sort_values("t_center_ms").reset_index(drop=True)
    cut = int(len(df) * frac)
    train = df.iloc[: cut - gap // 2]
    test = df.iloc[cut + gap // 2 :]
    return train, test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--tree-idx", type=int, default=0,
                    help="Which tree to plot (0..n_estimators-1)")
    ap.add_argument("--max-depth", type=int, default=4,
                    help="Limit displayed depth (full trees are unreadable)")
    args = ap.parse_args()

    model_path = ROOT / "models" / f"rf_{args.session}.joblib"
    windows_path = ROOT / "data" / "processed" / f"{args.session}_windows.csv"
    if not model_path.exists():
        raise SystemExit(f"Model not found: {model_path}")

    bundle = joblib.load(model_path)
    # within_session.train_rf saves {"model": rf, "feature_cols": [...]}
    rf = bundle["model"] if isinstance(bundle, dict) else bundle
    feature_names = (bundle.get("feature_cols") if isinstance(bundle, dict) else None) \
        or list(getattr(rf, "feature_names_in_", [])) \
        or [f"f{i}" for i in range(rf.n_features_in_)]
    print(f"Loaded {type(rf).__name__}")
    print(f"  n_estimators : {rf.n_estimators}")
    print(f"  max_depth    : {rf.max_depth}")
    print(f"  class_weight : {rf.class_weight}")
    print(f"  n_features   : {rf.n_features_in_}")
    print(f"  n_classes    : {rf.n_classes_}")

    # ── Figure 1: feature importances ────────────────────────────────────────
    imps = pd.Series(rf.feature_importances_, index=feature_names).sort_values()
    fig1, ax = plt.subplots(figsize=(7, 10))
    imps.plot.barh(ax=ax, color="#2a7ae2")
    ax.set_title(f"Feature importances — rf_{args.session}")
    ax.set_xlabel("Mean decrease in impurity")
    fig1.tight_layout()
    out1 = ROOT / "models" / f"rf_{args.session}_importances.png"
    fig1.savefig(out1, dpi=120)
    print(f"\n→ {out1}")

    # ── Figure 2: one example tree (depth-limited) ───────────────────────────
    tree = rf.estimators_[args.tree_idx]
    fig2, ax = plt.subplots(figsize=(18, 10))
    plot_tree(
        tree,
        feature_names=feature_names,
        class_names=["idle", "writing"],
        max_depth=args.max_depth,
        filled=True, rounded=True, impurity=False, fontsize=8, ax=ax,
    )
    ax.set_title(f"Tree {args.tree_idx} (showing depth ≤ {args.max_depth} of {tree.get_depth()})")
    fig2.tight_layout()
    out2 = ROOT / "models" / f"rf_{args.session}_tree{args.tree_idx}.png"
    fig2.savefig(out2, dpi=120)
    print(f"→ {out2}")

    # ── Figures 3+4: test-set evaluation (re-runs the same split) ────────────
    if windows_path.exists():
        df = pd.read_csv(windows_path)
        _, test = _temporal_split(df)
        X_test = test[feature_names].values
        y_test = test["label"].values
        y_pred = rf.predict(X_test)
        y_proba = rf.predict_proba(X_test)[:, 1]

        cm = confusion_matrix(y_test, y_pred)
        fig3, ax = plt.subplots(figsize=(4.5, 4.5))
        ConfusionMatrixDisplay(cm, display_labels=["idle", "writing"]).plot(
            ax=ax, cmap="Blues", colorbar=False, values_format="d")
        ax.set_title(f"Confusion matrix — test ({len(y_test)} windows)")
        fig3.tight_layout()
        out3 = ROOT / "models" / f"rf_{args.session}_confusion.png"
        fig3.savefig(out3, dpi=120)
        print(f"→ {out3}")

        fig4, ax = plt.subplots(figsize=(5.5, 5))
        RocCurveDisplay.from_predictions(y_test, y_proba, ax=ax)
        ax.plot([0, 1], [0, 1], "--", color="gray", lw=0.8)
        ax.set_title(f"ROC — rf_{args.session}")
        fig4.tight_layout()
        out4 = ROOT / "models" / f"rf_{args.session}_roc.png"
        fig4.savefig(out4, dpi=120)
        print(f"→ {out4}")
    else:
        print(f"\n(skipping confusion/ROC — {windows_path} not found)")
        return

    # ── Figure 5: predicted-vs-true timeline over the whole session ──────────
    df_sorted = df.sort_values("t_center_ms").reset_index(drop=True)
    X_all = df_sorted[feature_names].values
    y_true = df_sorted["label"].values
    y_pred_all = rf.predict(X_all)
    y_proba_all = rf.predict_proba(X_all)[:, 1]
    t_sec = (df_sorted["t_center_ms"].values - df_sorted["t_center_ms"].iloc[0]) / 1000.0
    cut_t = t_sec[int(len(df_sorted) * 0.8)]

    fig5, axes = plt.subplots(3, 1, figsize=(14, 5.5), sharex=True,
                              gridspec_kw={"height_ratios": [1, 1, 2]})

    # Why: pcolormesh with a 1-row Y axis renders each window as a colored
    # column; far more readable than a stem/scatter plot for 1700 windows.
    cmap = plt.matplotlib.colors.ListedColormap(["#dfe6ec", "#2a7ae2"])
    for ax, y, title in zip(axes[:2], [y_true, y_pred_all], ["True", "Predicted"]):
        ax.imshow(y.reshape(1, -1), aspect="auto", cmap=cmap,
                  vmin=0, vmax=1,
                  extent=[t_sec[0], t_sec[-1], 0, 1], interpolation="nearest")
        ax.set_yticks([0.5]); ax.set_yticklabels([title])
        ax.axvline(cut_t, color="black", ls="--", lw=1, alpha=0.5)

    # Bottom panel: writing probability (continuous) + agreement strip
    axes[2].fill_between(t_sec, 0, y_proba_all, color="#2a7ae2", alpha=0.4,
                         label="P(writing)")
    axes[2].plot(t_sec, y_proba_all, color="#2a7ae2", lw=0.8)
    axes[2].axhline(0.5, color="gray", ls=":", lw=0.8)
    axes[2].axvline(cut_t, color="black", ls="--", lw=1, alpha=0.5,
                    label=f"train/test cut @ {cut_t:.0f}s")
    # mark misclassifications as red ticks at y=1.05
    miss = y_true != y_pred_all
    axes[2].scatter(t_sec[miss], np.full(miss.sum(), 1.05),
                    s=6, c="#d44", marker="|", label=f"errors (n={miss.sum()})")
    axes[2].set_ylim(0, 1.12); axes[2].set_ylabel("P(writing)")
    axes[2].set_xlabel("Time since session start (s)")
    axes[2].legend(loc="upper right", fontsize=8)

    fig5.suptitle(f"S{args.session[1:]}: predicted vs true over {t_sec[-1]:.0f}s "
                  f"({len(df_sorted)} windows)")
    fig5.tight_layout()
    out5 = ROOT / "models" / f"rf_{args.session}_timeline.png"
    fig5.savefig(out5, dpi=120)
    print(f"→ {out5}")


if __name__ == "__main__":
    main()
