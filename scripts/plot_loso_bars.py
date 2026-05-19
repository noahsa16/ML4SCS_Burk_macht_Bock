"""Per-Subject LOSO Bar-Chart: macht aus '0.856 ± 0.032' eine Verteilung.

Liest die gecachten Per-Fold-Predictions aus models/burst_sweep_preds.csv
(generiert von scripts/plot_burst_sweep.py — falls noch nicht vorhanden,
muss der Sweep einmal vollständig laufen) und plottet pro Proband acc + AUC
als Doppel-Bar, mit Mean-Linien quer durch beide Serien.

CLI
---
    python scripts/plot_loso_bars.py
    python scripts/plot_loso_bars.py --sort by-auc      # vs. by-name (default)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, f1_score

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "models" / "burst_sweep_preds.csv"
OUT_FIG = ROOT / "reports" / "figures" / "loso_bars.png"
OUT_CSV = ROOT / "models" / "loso_per_fold.csv"


def _per_fold_metrics(preds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for held, g in preds.groupby("held_out", sort=False):
        y = g["label"].to_numpy()
        p = g["proba"].to_numpy()
        pred = (p >= 0.5).astype(int)
        try:
            auc = float(roc_auc_score(y, p))
        except ValueError:
            auc = float("nan")
        rows.append({
            "held_out": held,
            "n_windows": len(g),
            "n_writing": int(y.sum()),
            "accuracy": float((pred == y).mean()),
            "roc_auc": auc,
            "f1_writing": float(f1_score(y, pred, pos_label=1, zero_division=0)),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sort", choices=["by-name", "by-auc", "by-acc"],
                    default="by-name")
    args = ap.parse_args()

    if not CACHE.exists():
        raise SystemExit(
            f"Cache fehlt: {CACHE.relative_to(ROOT)}\n"
            f"Erst einmal scripts/plot_burst_sweep.py ohne --use-cache laufen lassen."
        )
    preds = pd.read_csv(CACHE)
    df = _per_fold_metrics(preds)

    if args.sort == "by-auc":
        df = df.sort_values("roc_auc", ascending=False).reset_index(drop=True)
    elif args.sort == "by-acc":
        df = df.sort_values("accuracy", ascending=False).reset_index(drop=True)
    else:
        df = df.sort_values("held_out").reset_index(drop=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    acc_mean, acc_std = df["accuracy"].mean(), df["accuracy"].std()
    auc_mean, auc_std = df["roc_auc"].mean(), df["roc_auc"].std()
    print(f"acc = {acc_mean:.3f} ± {acc_std:.3f}")
    print(f"auc = {auc_mean:.3f} ± {auc_std:.3f}")

    fig, ax = plt.subplots(figsize=(11, 6.5))
    x = np.arange(len(df))
    w = 0.38

    acc_color = "#d97706"
    auc_color = "#1d4ed8"

    bars_auc = ax.bar(x - w/2, df["roc_auc"], width=w,
                      color=auc_color, alpha=0.92, label="ROC-AUC",
                      edgecolor="white", linewidth=0.8)
    bars_acc = ax.bar(x + w/2, df["accuracy"], width=w,
                      color=acc_color, alpha=0.92, label="Accuracy",
                      edgecolor="white", linewidth=0.8)

    # Mean-Linien quer.
    ax.axhline(auc_mean, color=auc_color, lw=1.4, ls="--", alpha=0.7,
               zorder=1)
    ax.axhline(acc_mean, color=acc_color, lw=1.4, ls="--", alpha=0.7,
               zorder=1)
    ax.text(-0.55, auc_mean,
            f"  AUC mean\n  {auc_mean:.3f} ± {auc_std:.3f}",
            color=auc_color, fontsize=9, ha="left", va="center",
            fontweight="bold",
            bbox=dict(facecolor="white", edgecolor=auc_color,
                      boxstyle="round,pad=0.25", alpha=0.95))
    ax.text(-0.55, acc_mean,
            f"  acc mean\n  {acc_mean:.3f} ± {acc_std:.3f}",
            color=acc_color, fontsize=9, ha="left", va="center",
            fontweight="bold",
            bbox=dict(facecolor="white", edgecolor=acc_color,
                      boxstyle="round,pad=0.25", alpha=0.95))

    # Werte über den Bars.
    for bars, vals in [(bars_auc, df["roc_auc"]), (bars_acc, df["accuracy"])]:
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.004,
                    f"{v:.3f}", ha="center", va="bottom",
                    fontsize=8.5, color="#1f2937")

    ax.set_xticks(x)
    ax.set_xticklabels(df["held_out"], fontsize=10)
    ax.set_ylabel("Metric  (Sample-level, 1s Decision-Window)", fontsize=11)
    ax.set_xlabel("Hold-Out Proband (LOSO-by-person)", fontsize=11)
    ax.set_title(
        f"LOSO Per-Subject Performance — N={len(df)} Probanden\n"
        f"Random Forest · 200 Trees · class_weight=balanced · "
        f"per-session z-score",
        fontsize=12, fontweight="bold",
    )

    ax.legend(loc="lower left", framealpha=0.95, fontsize=10)
    ax.grid(True, axis="y", alpha=0.25)
    ymin = float(min(df["accuracy"].min(), df["roc_auc"].min()) - 0.03)
    ax.set_ylim(ymin, 1.0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=150, bbox_inches="tight")
    print(f"→ {OUT_FIG.relative_to(ROOT)}")
    print(f"→ {OUT_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
