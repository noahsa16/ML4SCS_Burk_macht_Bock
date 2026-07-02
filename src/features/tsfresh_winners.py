"""Lean destillierte tsfresh-Winner-Features (42) — Transfer-Kandidaten.

Herkunft (2026-07-02): die volle tsfresh-Bank (~4700 Features) schlug die 88
Hand-Features gepaart signifikant (+0.85 pp acc p=0.0015, +0.52 pp AUC p=0.0005,
N=20, matched windows — siehe reports/tsfresh_transfer.md). Die Top-Importances
konzentrieren sich auf vier Familien, die den 88 fehlen:

- **Per-Achse-Autokorrelation bei festen kurzen Lags** (40–100 ms) — nicht zu
  verwechseln mit dem Rhythmus-Negativbefund (dort Autokorr-PEAK über ein
  Lag-Band auf Magnituden; hier achsen-aufgelöst, fester Lag, signiertes Signal).
- **Quantile** q0.7/q0.9 (die 88 kennen nur min/max/mean/std).
- **change_quantiles**: mittlere |Änderung| innerhalb eines Quantil-Korridors.
- **CID** (complexity-invariant distance, z-normalisiert).

Implementierung folgt der tsfresh-Semantik (population variance, Korridor-Logik),
damit der Transfer-Test die Bank ehrlich repraesentiert.
"""
from __future__ import annotations

import numpy as np

ACC_AXES = ("ax", "ay", "az")
GYRO_AXES = ("rx", "ry", "rz")
GYRO_AC_LAGS = (2, 3, 4, 5)
ACC_AC_LAGS = (3, 5)
QUANTILES = (0.7, 0.9)
CQ_BAND = (0.2, 0.8)


def autocorrelation(x: np.ndarray, lag: int) -> float:
    """tsfresh-Semantik: ((x[:-lag]-mu)*(x[lag:]-mu)).sum() / ((n-lag)*var)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n <= lag:
        return 0.0
    var = float(np.var(x))
    if var < 1e-12:
        return 0.0
    mu = float(np.mean(x))
    return float(np.sum((x[:-lag] - mu) * (x[lag:] - mu)) / ((n - lag) * var))


def change_quantiles(x: np.ndarray, ql: float, qh: float) -> float:
    """Mittlere |Aenderung| zwischen konsekutiven Punkten, die BEIDE im
    [ql, qh]-Quantil-Korridor liegen (tsfresh: f_agg=mean, isabs=True)."""
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0
    lo, hi = np.quantile(x, ql), np.quantile(x, qh)
    inside = (x >= lo) & (x <= hi)
    valid = inside[:-1] & inside[1:]
    if not valid.any():
        return 0.0
    return float(np.mean(np.abs(np.diff(x)[valid])))


def cid_ce(x: np.ndarray) -> float:
    """Complexity estimate, z-normalisiert: sqrt(sum(diff(z)^2))."""
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0
    sigma = float(np.std(x))
    if sigma < 1e-12:
        return 0.0
    z = (x - np.mean(x)) / sigma
    d = np.diff(z)
    return float(np.sqrt(np.dot(d, d)))


def tsfresh_winner_features(window: np.ndarray) -> dict[str, float]:
    """42 Features fuer ein (N, 6)-IMU-Fenster (Spalten ax..az, rx..rz)."""
    feats: dict[str, float] = {}
    axes = ACC_AXES + GYRO_AXES
    for i, name in enumerate(axes):
        x = window[:, i]
        lags = GYRO_AC_LAGS if name in GYRO_AXES else ACC_AC_LAGS
        for lag in lags:
            feats[f"{name}_ac_lag{lag}"] = autocorrelation(x, lag)
        for q in QUANTILES:
            feats[f"{name}_q{int(q * 100)}"] = float(np.quantile(x, q))
        feats[f"{name}_cq_{int(CQ_BAND[0]*100)}_{int(CQ_BAND[1]*100)}"] = (
            change_quantiles(x, *CQ_BAND))
        feats[f"{name}_cid"] = cid_ce(x)
    return feats


WINNER_FEATURE_NAMES = tuple(
    tsfresh_winner_features(np.zeros((50, 6))).keys())
