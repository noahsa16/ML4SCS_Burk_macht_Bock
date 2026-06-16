"""Gepaarte Signifikanztests auf Per-Fold-Metriken.

Reviewer-Befund: „+0.4–0.8 pp" Gewinne bei Fold-σ ≈ 3.4 pp sind ohne
gepaarten Test nicht von Rauschen zu unterscheiden. paired_fold_test()
ist die Primitive, die jede A/B-Behauptung absichern soll.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.evaluation.significance import paired_fold_test


def test_identical_folds_are_not_significant():
    a = np.array([0.80, 0.85, 0.90, 0.78, 0.88])
    res = paired_fold_test(a, a.copy())
    assert res["n"] == 5
    assert res["median_diff"] == 0.0
    assert res["significant"] is False
    assert res["p_value"] == pytest.approx(1.0)


def test_large_consistent_gain_is_significant():
    # b is consistently ~10 pp below a across all folds -> should be significant
    a = np.array([0.80, 0.85, 0.90, 0.78, 0.88, 0.83, 0.86, 0.91])
    b = a - 0.10
    res = paired_fold_test(a, b)
    assert res["median_diff"] == pytest.approx(0.10, abs=1e-9)
    assert res["p_value"] < 0.05
    assert res["significant"] is True


def test_tiny_noisy_difference_is_not_significant():
    # Sub-pp differences with mixed sign (noise) -> not significant
    rng = np.random.default_rng(0)
    a = 0.85 + rng.normal(0, 0.03, 14)
    b = a + rng.normal(0, 0.001, 14)  # negligible, mixed-sign perturbation
    res = paired_fold_test(a, b)
    assert res["significant"] is False


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        paired_fold_test(np.array([0.8, 0.9]), np.array([0.8, 0.9, 0.7]))
