"""Aggregiert die per-Config cv-CSVs eines GitHub-Actions-Sweeps zu einer
Ergebnis-Tabelle (mean accuracy / roc_auc je Config), sortiert nach Accuracy.

Zwei CSV-Formen kommen vor und werden beide behandelt:
- ``train_loso``-cv (held_out/accuracy/roc_auc) — EINE Config pro Datei →
  ein Ergebnis, beschriftet mit dem Artefakt-Namen (cv-<name>).
- ``sweep_window_size``-cv (config/model/held_out/accuracy/roc_auc) — VIELE
  Combos pro Datei → wird nach ``config``/``model`` gruppiert.

Aufruf:  python scripts/ml/sweep_collect.py <root> [-o sweep_summary.md]
``<root>`` enthält je Artefakt ein Unterverzeichnis ``cv-<name>/`` mit CSVs.
"""
from __future__ import annotations

import argparse
import glob
import os

import pandas as pd


def _summarize(label: str, df: pd.DataFrame) -> dict:
    acc = df["accuracy"].dropna()
    auc = df["roc_auc"].dropna() if "roc_auc" in df.columns else pd.Series(dtype=float)
    return {
        "config": label,
        "n_folds": int(acc.shape[0]),
        "acc": round(float(acc.mean()), 4) if not acc.empty else None,
        "auc": round(float(auc.mean()), 4) if not auc.empty else None,
    }


def collect(root: str) -> pd.DataFrame:
    rows: list[dict] = []
    for d in sorted(glob.glob(os.path.join(root, "cv-*"))):
        base = os.path.basename(d)[len("cv-"):]
        csvs = sorted(glob.glob(os.path.join(d, "*.csv")))
        if not csvs:
            rows.append({"config": base, "n_folds": 0, "acc": None, "auc": None})
            continue
        df = pd.read_csv(csvs[0])
        if "accuracy" not in df.columns:
            rows.append({"config": base, "n_folds": 0, "acc": None, "auc": None})
            continue
        # Multi-Config-Dateien (Window-Sweep) nach config/model aufschlüsseln.
        keys = [c for c in ("config", "model") if c in df.columns]
        if keys:
            for vals, sub in df.groupby(keys, sort=False):
                vals = vals if isinstance(vals, tuple) else (vals,)
                rows.append(_summarize(":".join(map(str, vals)), sub))
        else:
            rows.append(_summarize(base, df))
    out = pd.DataFrame(rows, columns=["config", "n_folds", "acc", "auc"])
    if not out.empty:
        out = out.sort_values("acc", ascending=False, na_position="last").reset_index(drop=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Verzeichnis mit cv-<name>/-Unterordnern")
    ap.add_argument("-o", "--out", default="sweep_summary.md")
    args = ap.parse_args()

    res = collect(args.root)
    table = res.to_markdown(index=False)
    with open(args.out, "w") as f:
        f.write("# LOSO-Sweep — Ergebnis (sortiert nach accuracy)\n\n")
        f.write(table + "\n")
    print(table)


if __name__ == "__main__":
    main()
