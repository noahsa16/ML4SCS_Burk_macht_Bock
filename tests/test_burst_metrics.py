"""Burst-Aggregation muss kausal sein.

Die Burst-Metriken werden als User-facing Live-„Schreibzeit-Tracker"-Zahl
verkauft. Ein Live-Tracker kann zum Zeitpunkt t keine Fenster aus der
Zukunft sehen — die Glättung darf also nur nach hinten (trailing) schauen,
nicht zentriert. Regression gegen das alte ``rolling(center=True)``.
"""
from __future__ import annotations

import numpy as np

from src.training.train_loso import _causal_rolling_mean, _parse_burst_scales


def test_causal_rolling_mean_is_trailing():
    vals = np.array([1.0, 2.0, 3.0, 4.0])
    out = _causal_rolling_mean(vals, 2)
    # window [i-1, i], min_periods=1 -> first element is itself
    assert np.allclose(out, [1.0, 1.5, 2.5, 3.5])


def test_causal_rolling_mean_does_not_use_future():
    base = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    alt = base.copy()
    alt[4:] = 99.0  # perturb only the *future* tail (indices 4,5)
    n = 3
    sm_base = _causal_rolling_mean(base, n)
    sm_alt = _causal_rolling_mean(alt, n)
    # Positions strictly before the perturbation (0..3) must be untouched:
    # a trailing window cannot look ahead into indices 4,5.
    assert np.allclose(sm_base[:4], sm_alt[:4])
    # And the perturbation does change the present/future positions:
    assert not np.allclose(sm_base[4:], sm_alt[4:])


def test_parse_burst_scales_basic():
    assert _parse_burst_scales("5,10,30") == (5.0, 10.0, 30.0)


def test_parse_burst_scales_strips_sorts_dedupes():
    assert _parse_burst_scales(" 30, 5 ,5, 10 ") == (5.0, 10.0, 30.0)


def test_parse_burst_scales_drops_nonpositive():
    assert _parse_burst_scales("0,-3,5") == (5.0,)


def test_parse_burst_scales_empty_is_no_burst():
    assert _parse_burst_scales("") == ()
    assert _parse_burst_scales("  ") == ()
