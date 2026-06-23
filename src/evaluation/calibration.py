"""Kalibrierungs-Primitive: Reliability-Kurve + Expected Calibration Error.

Geteilte, getestete Mathematik hinter dem Reliability-Diagramm
(`scripts/plots/plot_reliability_diagram.py`) und der Decision-Scale-Auswertung
(`scripts/ml/calibration_decision_scale.py`). „Kalibriert" heißt: wenn das
Modell „70 % writing" sagt, stimmt das auch in 70 % der Fälle — die
Reliability-Kurve liegt dann auf der Diagonale.
"""
from __future__ import annotations

import numpy as np


def reliability_curve(
    y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pro Bin: mean predicted proba, fraction positives, count.

    Bins sind ``[lo, hi)`` außer dem letzten, der rechts-inklusiv ist (sonst
    fällt ``proba == 1.0`` durch). Leere Bins → nan in ``mean_p``/``frac_pos``.
    """
    y_true = np.asarray(y_true, dtype=float)
    proba = np.asarray(proba, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    mean_p = np.full(n_bins, np.nan)
    frac_pos = np.full(n_bins, np.nan)
    counts = np.zeros(n_bins, dtype=int)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (proba >= lo) & (proba < hi) if i < n_bins - 1 \
            else (proba >= lo) & (proba <= hi)
        n = int(mask.sum())
        counts[i] = n
        if n > 0:
            mean_p[i] = proba[mask].mean()
            frac_pos[i] = y_true[mask].mean()
    return mean_p, frac_pos, counts


def expected_calibration_error(
    y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10
) -> float:
    """ECE = Σ (bin_count / n) × |bin_freq − bin_conf|. Leere Eingabe → nan."""
    mean_p, frac_pos, counts = reliability_curve(y_true, proba, n_bins)
    n_total = counts.sum()
    if n_total == 0:
        return float("nan")
    ece = 0.0
    for i in range(n_bins):
        if counts[i] == 0:
            continue
        ece += (counts[i] / n_total) * abs(frac_pos[i] - mean_p[i])
    return float(ece)
