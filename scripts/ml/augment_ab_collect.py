"""Sammelt die per-(Seed, Bedingung) cv-CSVs eines PARALLELEN Augment-A/B-Sweeps
und baut Seed-Mittel + gepaarten Wilcoxon (acc + AUC) + Report.

Gegenstueck zum sequentiellen ``augment_ab.py`` (lokal): dort fahren alle Laeufe
in einem Prozess, hier liefert jeder GitHub-Actions-Matrix-Job EINE
``deep_loso``-cv (held_out/accuracy/roc_auc) als Artefakt ``cv-s<seed>-<aug|noaug>/``.

Eingang: ``<root>`` mit Unterordnern ``cv-*`` (je genau eine cv-CSV). Die
Bedingung kommt aus dem Ordner-Suffix (``-aug`` -> augmentiert, sonst Baseline).

Ausgang: ``-o`` Markdown-Report (mean +/- Seed-sigma je Bedingung, gepaarter
Wilcoxon, Per-Fold-Tabelle) + Claim-Gate-Hinweis. Reine pandas/scipy-Logik,
kein torch — der collect-Job braucht keine Modell-Deps.
"""
from __future__ import annotations

import argparse
import glob
import os
import statistics as st
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
from src.evaluation.significance import paired_fold_test  # noqa: E402


def _seed_average(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Per-held_out-Mittel von accuracy + roc_auc ueber mehrere Seed-Laeufe."""
    cat = pd.concat(frames, ignore_index=True)
    return (
        cat.groupby("held_out", as_index=False)[["accuracy", "roc_auc"]]
        .mean()
        .sort_values("held_out")
        .reset_index(drop=True)
    )


def _paired(aug: pd.DataFrame, base: pd.DataFrame, metric: str) -> dict:
    """Gepaarter Wilcoxon auf gemeinsamen Folds, Differenz aug - base."""
    m = aug[["held_out", metric]].merge(
        base[["held_out", metric]], on="held_out", suffixes=("_aug", "_base")
    )
    res = paired_fold_test(
        m[f"{metric}_aug"].to_numpy(), m[f"{metric}_base"].to_numpy()
    )
    res["metric"] = metric
    return res


def load_runs(root: str) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    """Lese die cv-*-Artefakte; teile in (no-aug, aug) anhand des Namens-Suffix."""
    base, aug = [], []
    for d in sorted(glob.glob(os.path.join(root, "cv-*"))):
        name = os.path.basename(d)
        csvs = sorted(glob.glob(os.path.join(d, "*.csv")))
        if not csvs:
            continue
        df = pd.read_csv(csvs[0])
        if "accuracy" not in df.columns or "held_out" not in df.columns:
            continue
        (aug if name.endswith("-aug") else base).append(df)
    return base, aug


def _cohort_means(runs: list[pd.DataFrame]) -> list[float]:
    return [float(df["accuracy"].mean()) for df in runs]


def build_report(base_runs, aug_runs) -> str:
    base = _seed_average(base_runs)
    aug = _seed_average(aug_runs)
    res_acc = _paired(aug, base, "accuracy")
    res_auc = _paired(aug, base, "roc_auc")

    bm, am = _cohort_means(base_runs), _cohort_means(aug_runs)
    base_mu = st.mean(bm) if bm else 0.0
    base_sd = st.pstdev(bm) if len(bm) > 1 else 0.0
    aug_mu = st.mean(am) if am else 0.0
    aug_sd = st.pstdev(am) if len(am) > 1 else 0.0
    merged = aug.merge(base, on="held_out", suffixes=("_aug", "_base"))

    lines = [
        "# Augmentation-A/B (parallel) — Ergebnis",
        "",
        f"no-aug-Laeufe: {len(base_runs)} | aug-Laeufe: {len(aug_runs)} | "
        f"Folds: {len(aug)} | Transforms: scale(0.8-1.2) + rotate(+/-10 deg)",
        "",
        "## Kohorten-Mean-Accuracy (Seed-Spread)",
        f"- no-aug: {base_mu:.4f} +/- {base_sd:.4f} (Seed-sigma)",
        f"- aug:    {aug_mu:.4f} +/- {aug_sd:.4f} (Seed-sigma)",
        f"- delta (aug - no-aug): {aug_mu - base_mu:+.4f}",
        "",
        "## Gepaarter Wilcoxon (seed-gemittelte Folds, aug - no-aug)",
        f"- accuracy: delta_mean {res_acc['mean_diff']:+.4f}, "
        f"p={res_acc['p_value']:.4f}, signifikant={res_acc['significant']}",
        f"- roc_auc:  delta_mean {res_auc['mean_diff']:+.4f}, "
        f"p={res_auc['p_value']:.4f}, signifikant={res_auc['significant']}",
        "",
        "## Verdikt (Claim-Gate)",
        "Gewinn NUR wenn delta ausserhalb des Seed-sigma-Bands UND p < 0.05 "
        "(acc + AUC). Sonst als Rauschen reporten — kein Headline-Claim.",
        "",
        "## Per-Fold (seed-gemittelt)",
        "| held_out | acc no-aug | acc aug | d_acc | auc no-aug | auc aug |",
        "|---|---|---|---|---|---|",
    ]
    for r in merged.itertuples():
        lines.append(
            f"| {r.held_out} | {r.accuracy_base:.3f} | {r.accuracy_aug:.3f} | "
            f"{r.accuracy_aug - r.accuracy_base:+.3f} | "
            f"{r.roc_auc_base:.3f} | {r.roc_auc_aug:.3f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", help="Verzeichnis mit cv-<name>/-Unterordnern")
    ap.add_argument("-o", "--out", default="augment_ab_summary.md")
    args = ap.parse_args()

    base_runs, aug_runs = load_runs(args.root)
    if not base_runs or not aug_runs:
        raise SystemExit(
            f"Zu wenige Laeufe: no-aug={len(base_runs)}, aug={len(aug_runs)} "
            f"(brauche je >= 1). cv-*-Artefakte in {args.root!r} pruefen."
        )
    report = build_report(base_runs, aug_runs)
    Path(args.out).write_text(report)
    print(report)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
