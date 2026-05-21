"""CLI fuer den Deep-Sequenz-Modell-Vergleich.

::

    python -m src.training.deep                       # alle Modelle, beide Fenster
    python -m src.training.deep --model cnn --win 1   # nur 1D-CNN, 1-s-Fenster
    python -m src.training.deep --model lstm --win 5

Schreibt die per-fold Metriken nach ``models/deep_loso.csv`` und
druckt eine Mean-+-Std-Vergleichstabelle (mit der RF-Headline als
Referenzzeile).
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from src.training.deep.train_loso import MODEL_DIR, train_deep_loso

# RF-Headline aus CLAUDE.md (LOSO-by-person, N=10, gap=2500) als Referenz.
RF_HEADLINE = {
    "model": "rf (baseline)",
    "window_sec": 1,
    "accuracy": 0.856,
    "roc_auc": 0.928,
    "f1_writing": 0.864,
    "acc_30s": 0.831,
    "auc_30s": 0.909,
}


def _summary_row(df: pd.DataFrame) -> dict:
    g = df.iloc[0]
    out = {"model": g["model"], "window_sec": int(g["window_sec"])}
    for col in ["accuracy", "roc_auc", "f1_writing", "acc_30s", "auc_30s"]:
        out[col] = float(np.nanmean(df[col]))
        out[f"{col}_std"] = float(np.nanstd(df[col]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.training.deep")
    parser.add_argument(
        "--model", choices=["cnn", "lstm", "gru", "all"], default="all"
    )
    parser.add_argument(
        "--win", choices=["1", "5", "both"], default="both",
        help="Eingabe-Fenster in Sekunden.",
    )
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--max-gap-ms", type=float, default=2500.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    models = ["cnn", "lstm", "gru"] if args.model == "all" else [args.model]
    windows = [1, 5] if args.win == "both" else [int(args.win)]

    all_folds: list[pd.DataFrame] = []
    summaries: list[dict] = []
    for win in windows:
        for model_name in models:
            df = train_deep_loso(
                model_name, win,
                include_all=args.include_all,
                max_gap_ms=args.max_gap_ms,
                seed=args.seed,
            )
            if df.empty:
                print(f"[warn] {model_name}/{win}s: keine Folds.")
                continue
            all_folds.append(df)
            summaries.append(_summary_row(df))

    if not all_folds:
        raise SystemExit("Keine Ergebnisse -- Daten / Filter pruefen.")

    folds_table = pd.concat(all_folds, ignore_index=True)
    out_csv = MODEL_DIR / "deep_loso.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    folds_table.to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}  ({len(folds_table)} fold-Zeilen)")

    summary = pd.DataFrame(summaries + [RF_HEADLINE])
    print("\n=== Vergleich (Mean ueber Folds) ===")
    cols = ["model", "window_sec", "accuracy", "roc_auc", "f1_writing",
            "acc_30s", "auc_30s"]
    print(summary[cols].to_string(index=False,
                                  float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
