"""Statistical rigor for the learning-curve forecast.

Provides four scientifically-needed pieces that the bare power-law fit
lacks:

1. ``fit_power_law``     -- single point estimate (existing default).
2. ``bootstrap_ci``      -- non-parametric resampling of the per-fold
                            measurements, returns 5%/50%/95% prediction
                            bands across an n-grid.
3. ``fit_alternatives``  -- log / sqrt / power / exp saturation models,
                            ranked by AIC/BIC + RSS so we can defend the
                            choice of power-law instead of asserting it.
4. ``loso_curve_validation``
                         -- holds out one subject at a time, refits the
                            forecast on the remaining subjects, predicts
                            the held-out subject's empirical means; mean
                            absolute error = out-of-sample forecast skill.

All functions are degradation-safe: with very small samples the fit
will fail or return wide bands, never crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


# ---- saturation models ---------------------------------------------

def _power(n, c, a, b):
    return c - a * np.power(n, -b)


def _logmodel(n, alpha, beta):
    return alpha + beta * np.log(n)


def _sqrt(n, c, a):
    return c - a / np.sqrt(n)


def _exp(n, c, a, b):
    return c - a * np.exp(-b * n)


@dataclass
class AltFit:
    name: str
    params: tuple
    predict: Callable
    rss: float
    k: int        # num params
    n: int        # num samples
    aic: float
    bic: float


def _fit_one(model_fn, xs, ys, p0, bounds, n_params) -> AltFit | None:
    try:
        popt, _ = curve_fit(model_fn, xs, ys, p0=p0, bounds=bounds, maxfev=5000)
    except Exception:
        return None
    yhat = model_fn(xs, *popt)
    rss = float(np.sum((ys - yhat) ** 2))
    n = len(ys)
    if rss <= 0 or n <= n_params:
        # Underdetermined -- AIC/BIC undefined.  Return RSS only.
        aic = float("nan")
        bic = float("nan")
    else:
        aic = n * np.log(rss / n) + 2 * n_params
        bic = n * np.log(rss / n) + n_params * np.log(n)
    return AltFit(
        name="", params=tuple(popt), predict=lambda x, p=popt: model_fn(x, *p),
        rss=rss, k=n_params, n=n, aic=aic, bic=bic,
    )


def fit_power_law(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float] | None:
    fit = _fit_one(_power, xs, ys, p0=[0.95, 0.3, 0.4],
                   bounds=([0.5, 0.0, 0.05], [1.0, 5.0, 3.0]), n_params=3)
    return tuple(fit.params) if fit else None


def fit_alternatives(xs: np.ndarray, ys: np.ndarray) -> dict[str, AltFit]:
    """Fit all four candidate saturation forms; return them keyed by name."""
    out: dict[str, AltFit] = {}
    specs = [
        ("power", _power, [0.95, 0.3, 0.4], ([0.5, 0.0, 0.05], [1.0, 5.0, 3.0]), 3),
        ("log",   _logmodel, [0.5, 0.1], ([-2.0, -1.0], [2.0, 1.0]), 2),
        ("sqrt",  _sqrt, [0.9, 0.3], ([0.5, 0.0], [1.0, 5.0]), 2),
        ("exp",   _exp, [0.9, 0.3, 0.5], ([0.5, 0.0, 0.01], [1.0, 5.0, 5.0]), 3),
    ]
    for name, fn, p0, bounds, k in specs:
        fit = _fit_one(fn, xs, ys, p0, bounds, k)
        if fit is None:
            continue
        fit.name = name
        out[name] = fit
    return out


# ---- bootstrap -----------------------------------------------------

@dataclass
class BootstrapBand:
    n_grid: np.ndarray
    lo: np.ndarray        # 5th percentile
    mid: np.ndarray       # 50th percentile (median bootstrap fit)
    hi: np.ndarray        # 95th percentile
    asymptote_samples: np.ndarray  # bootstrap distribution of C
    n_successful: int     # how many of n_boot fits succeeded


def bootstrap_ci(
    raw_xs: np.ndarray, raw_ys: np.ndarray,
    n_grid: np.ndarray, n_boot: int = 1000,
    rng_seed: int = 42,
) -> BootstrapBand:
    """Non-parametric bootstrap on per-fold measurements.

    Resample (xs, ys) pairs with replacement n_boot times, refit
    power-law each time, evaluate on n_grid, return percentile bands.
    """
    rng = np.random.default_rng(rng_seed)
    n = len(raw_xs)
    if n < 2:
        nan = np.full_like(n_grid, np.nan, dtype=float)
        return BootstrapBand(n_grid, nan, nan, nan, np.array([]), 0)

    preds = []
    cs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        xb, yb = raw_xs[idx], raw_ys[idx]
        # need ≥2 unique x to fit
        if len(np.unique(xb)) < 2:
            continue
        fit = fit_power_law(xb, yb)
        if fit is None:
            continue
        c, a, b = fit
        preds.append(_power(n_grid, c, a, b))
        cs.append(c)

    if len(preds) < 10:
        nan = np.full_like(n_grid, np.nan, dtype=float)
        return BootstrapBand(n_grid, nan, nan, nan, np.array(cs), len(preds))

    arr = np.vstack(preds)
    return BootstrapBand(
        n_grid=n_grid,
        lo=np.nanpercentile(arr, 5, axis=0),
        mid=np.nanpercentile(arr, 50, axis=0),
        hi=np.nanpercentile(arr, 95, axis=0),
        asymptote_samples=np.array(cs),
        n_successful=len(preds),
    )


# ---- LOSO curve-fit validation -------------------------------------

@dataclass
class LosoResult:
    mae_per_subject: dict[str, float]
    mae_mean: float
    n_predictions: int


def loso_curve_validation(
    sub_df: pd.DataFrame,        # rows: {test_person, n_train, acc} for ONE model
) -> LosoResult:
    """Leave-one-subject-out validation of the forecast itself.

    For each subject S:
      - fit power-law using ONLY folds where test_person != S
      - predict S's empirical mean acc at each n_train S was tested on
      - record |predicted - actual|
    """
    subjects = sorted(sub_df["test_person"].dropna().unique().tolist())
    mae_per: dict[str, float] = {}
    n_preds = 0
    for s in subjects:
        train = sub_df[sub_df["test_person"] != s]
        held = sub_df[sub_df["test_person"] == s]
        if len(train) < 3 or len(held) == 0:
            continue
        fit = fit_power_law(train["n_train"].to_numpy(float),
                            train["acc"].to_numpy(float))
        if fit is None:
            continue
        c, a, b = fit
        errs = []
        for n_train, g in held.groupby("n_train"):
            actual = float(g["acc"].mean())
            predicted = float(_power(n_train, c, a, b))
            errs.append(abs(actual - predicted))
            n_preds += 1
        if errs:
            mae_per[s] = float(np.mean(errs))

    mae_mean = float(np.mean(list(mae_per.values()))) if mae_per else float("nan")
    return LosoResult(mae_per_subject=mae_per, mae_mean=mae_mean,
                      n_predictions=n_preds)
