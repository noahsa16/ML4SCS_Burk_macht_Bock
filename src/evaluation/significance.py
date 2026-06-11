"""Gepaarte Signifikanztests für Per-Fold-Metriken (LOSO-A/B).

Motivation: Fold-σ liegt bei ~3.4 pp (N=14). Differenzen von <1 pp zwischen
zwei Konfigurationen (gap-Wert, Z-Score an/aus, Gravity an/aus, center vs
causal) sind ohne gepaarten Test nicht von Rauschen zu trennen. Da beide
Konfigurationen auf **denselben** Folds (Personen) ausgewertet werden, ist
der Wilcoxon signed-rank Test auf den paarweisen Differenzen das passende
verteilungsfreie Verfahren.

CLI: ``python -m src.evaluation.significance A.csv B.csv [--metric accuracy]``
vergleicht zwei ``loso_cv.csv`` (per-fold) auf gemeinsamen ``held_out``-Folds.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon


def paired_fold_test(a: np.ndarray, b: np.ndarray, alpha: float = 0.05) -> dict:
    """Wilcoxon signed-rank Test auf paarweisen Fold-Differenzen ``a - b``.

    ``a`` und ``b`` sind die Metrik (z.B. accuracy) pro Fold, **gleiche
    Reihenfolge / gleiche Folds**. Returns ``n``, ``median_diff`` (a−b),
    ``mean_diff``, ``statistic``, ``p_value`` und ``significant`` (p < alpha).
    Bei identischen Eingaben (alle Differenzen 0) ist das Ergebnis
    definitionsgemäß nicht signifikant (p = 1.0).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"a/b müssen gleiche Form haben, hat {a.shape} vs {b.shape}")
    if a.ndim != 1 or len(a) == 0:
        raise ValueError("a/b müssen nicht-leere 1D-Arrays sein")

    diff = a - b
    n = int(len(diff))
    median_diff = float(np.median(diff))
    mean_diff = float(np.mean(diff))

    if np.allclose(diff, 0.0):
        return {"n": n, "median_diff": 0.0, "mean_diff": 0.0,
                "statistic": float("nan"), "p_value": 1.0, "significant": False}
    try:
        stat, p = wilcoxon(a, b)
    except ValueError:
        # e.g. alle Nicht-Null-Differenzen gleiches Vorzeichen bei sehr kleinem n
        stat, p = float("nan"), 1.0
    return {"n": n, "median_diff": median_diff, "mean_diff": mean_diff,
            "statistic": float(stat), "p_value": float(p),
            "significant": bool(p < alpha)}


def compare_cv_files(path_a: Path, path_b: Path, metric: str = "accuracy") -> dict:
    """Lädt zwei ``loso_cv.csv``, paart auf ``held_out`` und testet ``metric``."""
    a = pd.read_csv(path_a)
    b = pd.read_csv(path_b)
    key = "held_out" if "held_out" in a.columns else a.columns[0]
    merged = a[[key, metric]].merge(b[[key, metric]], on=key, suffixes=("_a", "_b"))
    if merged.empty:
        raise ValueError(f"Keine gemeinsamen Folds in Spalte {key!r}")
    res = paired_fold_test(merged[f"{metric}_a"].to_numpy(),
                           merged[f"{metric}_b"].to_numpy())
    res["metric"] = metric
    res["n_common_folds"] = len(merged)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a", type=Path, help="loso_cv.csv der Konfiguration A")
    ap.add_argument("b", type=Path, help="loso_cv.csv der Konfiguration B")
    ap.add_argument("--metric", default="accuracy",
                    help="Spaltenname der zu vergleichenden Metrik")
    args = ap.parse_args()
    res = compare_cv_files(args.a, args.b, args.metric)
    verdict = "SIGNIFIKANT" if res["significant"] else "n.s. (Rauschen)"
    print(f"Wilcoxon paired ({res['metric']}, {res['n_common_folds']} Folds): "
          f"median Δ(A−B) = {res['median_diff']:+.4f}, "
          f"p = {res['p_value']:.4f} → {verdict}")


if __name__ == "__main__":
    main()
