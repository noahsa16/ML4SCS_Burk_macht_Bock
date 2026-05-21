"""Burst-Window-Sweep: acc + AUC vs. Decision-Window-Größe.

Headline-Visualisierung für die Präsentation. Erzählt die "Physik" der
Schreib-Bursts: ab ~5-10 s Decision-Window erholen sich die Metriken
schlagartig, weil hochfrequentes Modell-Rauschen aus-mittelt während
echte Schreib-/Idle-Phasen länger als das Smoothing-Fenster sind.

Pipeline (analog zu src.training.train_loso):
  1. Lade trainierbare Sessions (verdict ∈ {trainable, usable}, kein test_mode)
  2. Per-Session-z-score auf den 88 Features
  3. LOSO-by-person: RF 200 Trees, class_weight=balanced
  4. Pro Fold: predict_proba → für jede Sweep-Skala _burst_metrics
  5. Aggregation: Mean ± σ über N Folds, geplottet als zwei Kurven
     (acc + AUC) mit σ-Band.

Caching: pro Run werden die Per-Fold-Predictions in
    models/burst_sweep_preds.parquet
gespeichert. Mit --use-cache lädt der Sweep daraus ohne RF-Retraining.

CLI
---
    python scripts/plots/plot_burst_sweep.py                  # full pipeline
    python scripts/plots/plot_burst_sweep.py --use-cache      # nur Plot neu rendern
    python scripts/plots/plot_burst_sweep.py --scales "1,2,3,5,8,10,15,20,30"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.train_loso import (
    _burst_metrics,
    _load_windows,
    _select_sessions,
    _zscore_per_session,
)
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

OUT_FIG = ROOT / "reports" / "figures" / "burst_sweep.png"
OUT_CSV = ROOT / "models" / "burst_sweep_summary.csv"
CACHE_PARQUET = ROOT / "models" / "burst_sweep_preds.csv"

DEFAULT_SCALES = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0)


def _compute_fold_predictions(
    all_w: pd.DataFrame,
    feat_cols: list[str],
    n_estimators: int,
    random_state: int,
) -> pd.DataFrame:
    """LOSO-by-person → DataFrame mit Spalten [held_out, session_id, t_center_ms, label, proba]."""
    persons = sorted(all_w["person_id"].dropna().unique())
    print(f"Folds (by person): {persons}")

    rows: list[pd.DataFrame] = []
    for held in persons:
        test_mask = all_w["person_id"] == held
        train_df = all_w[~test_mask]
        test_df = all_w[test_mask]
        if len(np.unique(test_df["label"])) < 2:
            print(f"  [{held}] skipped (single-class test)")
            continue

        clf = RandomForestClassifier(
            n_estimators=n_estimators, random_state=random_state,
            class_weight="balanced", n_jobs=-1,
        )
        t0 = time.perf_counter()
        clf.fit(train_df[feat_cols].to_numpy(), train_df["label"].to_numpy())
        proba = clf.predict_proba(test_df[feat_cols].to_numpy())[:, 1]
        dt = time.perf_counter() - t0
        try:
            auc1 = roc_auc_score(test_df["label"].to_numpy(), proba)
        except ValueError:
            auc1 = float("nan")
        print(f"  [{held}]  fit={dt:5.1f}s  n_test={len(test_df):>5}  "
              f"1s-AUC={auc1:.3f}")
        rows.append(pd.DataFrame({
            "held_out": held,
            "session_id": test_df["session_id"].to_numpy(),
            "t_center_ms": test_df["t_center_ms"].to_numpy(),
            "label": test_df["label"].to_numpy(),
            "proba": proba,
        }))
    return pd.concat(rows, ignore_index=True)


def _sweep_from_preds(preds: pd.DataFrame,
                      scales: tuple[float, ...]) -> pd.DataFrame:
    """Pro Fold und Skala _burst_metrics. Liefert long-format DataFrame."""
    out: list[dict] = []
    for held, fold_df in preds.groupby("held_out", sort=False):
        # _burst_metrics erwartet `test_df` mit session_id + t_center_ms +
        # label-Spalte; proba/y kommen separat als arrays rein.
        b = _burst_metrics(
            fold_df["proba"].to_numpy(),
            fold_df["label"].to_numpy(),
            fold_df[["session_id", "t_center_ms", "label"]].copy(),
            scales_sec=scales,
        )
        for scale_key, m in b.items():
            out.append({
                "held_out": held,
                "scale_sec": float(scale_key.rstrip("s")),
                "accuracy": m["accuracy"],
                "roc_auc": m["roc_auc"],
                "f1_writing": m["f1_writing"],
            })
    return pd.DataFrame(out)


def _plot_sweep(summary: pd.DataFrame, scales: tuple[float, ...],
                n_folds: int) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6.5))

    # Aggregation: Mean ± σ pro Skala über die Folds.
    agg = (summary.groupby("scale_sec", sort=True)
                  [["accuracy", "roc_auc", "f1_writing"]]
                  .agg(["mean", "std"]).reset_index())
    xs = agg["scale_sec"].to_numpy()

    def _line(metric: str, color: str, label: str, marker: str):
        mean = agg[(metric, "mean")].to_numpy()
        std = agg[(metric, "std")].to_numpy()
        ax.fill_between(xs, mean - std, mean + std, color=color, alpha=0.18)
        ax.plot(xs, mean, color=color, lw=2.2, marker=marker,
                markersize=8, label=label)
        # Punkt-Annotationen für Mean-Werte.
        for x, m in zip(xs, mean):
            ax.annotate(f"{m:.3f}", (x, m), textcoords="offset points",
                        xytext=(0, 10 if metric == "roc_auc" else -16),
                        fontsize=8, ha="center", color=color)

    _line("roc_auc", "#1d4ed8", "ROC-AUC", "o")
    _line("accuracy", "#d97706", "Accuracy", "s")

    # Peak-Marker: optimales Decision-Window pro Metrik.
    auc_mean = agg[("roc_auc", "mean")].to_numpy()
    acc_mean = agg[("accuracy", "mean")].to_numpy()
    auc_peak_x = xs[int(np.nanargmax(auc_mean))]
    acc_peak_x = xs[int(np.nanargmax(acc_mean))]
    for px, color in [(auc_peak_x, "#1d4ed8"), (acc_peak_x, "#d97706")]:
        ax.axvline(px, color=color, lw=0.8, ls=":", alpha=0.45)
    # Band zwischen den beiden Peaks (visuell, ohne Label).
    lo, hi = sorted([auc_peak_x, acc_peak_x])
    ax.axvspan(lo, hi, color="#10b981", alpha=0.08, zorder=0)

    ax.set_xscale("log")
    ax.set_xticks(list(scales))
    ax.set_xticklabels([f"{int(s)}s" for s in scales])
    ax.set_xlabel("Decision-Window (Sekunden, log-Skala)", fontsize=11)
    ax.set_ylabel("Metric  (Mean ± σ über LOSO-Folds)", fontsize=11)
    ax.set_title(
        f"Burst-Window-Sweep — LOSO-by-person (N={n_folds})\n"
        f"Random Forest · 200 Trees · class_weight=balanced · "
        f"per-session z-score",
        fontsize=12, fontweight="bold",
    )
    ax.legend(loc="lower right", framealpha=0.95, fontsize=11)
    ax.grid(True, which="both", alpha=0.25)
    ax.set_ylim(bottom=min(0.80, ax.get_ylim()[0]))

    fig.tight_layout()
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=150, bbox_inches="tight")
    print(f"→ {OUT_FIG.relative_to(ROOT)}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(OUT_CSV, index=False)
    print(f"→ {OUT_CSV.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true")
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--random-state", type=int, default=42)
    ap.add_argument("--scales", type=str,
                    default=",".join(f"{s:g}" for s in DEFAULT_SCALES),
                    help="Komma-getrennte Sekunden-Werte")
    ap.add_argument("--min-windows", type=int, default=0)
    ap.add_argument("--use-cache", action="store_true",
                    help="Predictions aus models/burst_sweep_preds.parquet laden.")
    args = ap.parse_args()

    scales = tuple(float(s) for s in args.scales.split(","))
    print(f"Sweep-Skalen: {scales}")

    if args.use_cache and CACHE_PARQUET.exists():
        print(f"← cache: {CACHE_PARQUET.relative_to(ROOT)}")
        preds = pd.read_csv(CACHE_PARQUET)
    else:
        sessions = _select_sessions(args.include_all, args.min_windows)
        if sessions.empty:
            raise SystemExit("Keine trainierbaren Sessions gefunden.")
        print(f"Sessions: {sessions['session_id'].tolist()}")
        frames = [_load_windows(sid) for sid in sessions["session_id"]]
        all_w = pd.concat(frames, ignore_index=True).merge(
            sessions[["session_id", "person_id"]], on="session_id", how="left",
        )
        feat_cols = [
            c for c in all_w.columns
            if c not in {"label", "t_center_ms", "session_id", "person_id",
                         "task_id", "task_category"}
        ]
        if not args.no_zscore:
            all_w = _zscore_per_session(all_w, feat_cols)
        print(f"Windows: {len(all_w)}   Features: {len(feat_cols)}   "
              f"zscore={not args.no_zscore}\n")

        preds = _compute_fold_predictions(
            all_w, feat_cols, args.n_estimators, args.random_state,
        )
        CACHE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        preds.to_csv(CACHE_PARQUET, index=False)
        print(f"→ {CACHE_PARQUET.relative_to(ROOT)} (cache)\n")

    summary = _sweep_from_preds(preds, scales)
    n_folds = summary["held_out"].nunique()
    _plot_sweep(summary, scales, n_folds)


if __name__ == "__main__":
    main()
