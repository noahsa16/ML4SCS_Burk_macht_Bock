"""Quasi-zufaelliger (Sobol) Hyperparameter-Sampler für die Deep-HP-Studie.

Playbook-Prinzip: quasi-zufaellige Suche fuer die Exploration (gleichmaessige
Abdeckung, saubere Isolations-Plots) statt Grid/Bayesian. Reine Numerik,
deterministisch ueber ``seed`` -> unit-testbar.
"""
from __future__ import annotations

import math

from scipy.stats import qmc

_BATCH = (32, 64, 128)


def _log_uniform(u: float, lo: float, hi: float) -> float:
    return float(math.exp(math.log(lo) + u * (math.log(hi) - math.log(lo))))


def sobol_configs(n: int, seed: int = 0) -> list[dict]:
    """``n`` Sobol-Punkte -> HP-Configs. Dims: lr, dropout, batch, weight_decay."""
    sampler = qmc.Sobol(d=4, scramble=True, seed=seed)
    pts = sampler.random(n)  # (n, 4) in [0,1)
    out = []
    for lr_u, do_u, b_u, wd_u in pts:
        out.append({
            "lr": round(_log_uniform(lr_u, 1e-4, 1e-2), 6),
            "dropout": round(float(do_u) * 0.5, 3),
            "batch_size": _BATCH[min(int(b_u * len(_BATCH)), len(_BATCH) - 1)],
            "weight_decay": round(_log_uniform(wd_u, 1e-6, 1e-2), 8),
        })
    return out


def is_at_boundary(value: float, lo: float, hi: float,
                   log: bool = False, tol: float = 0.05) -> bool:
    """True, wenn ``value`` innerhalb ``tol`` (Anteil des Bereichs) am Rand liegt."""
    if log:
        value, lo, hi = math.log(value), math.log(lo), math.log(hi)
    span = hi - lo
    return (value - lo) <= tol * span or (hi - value) <= tol * span
