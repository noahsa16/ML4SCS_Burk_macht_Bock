"""Smoke tests for gravity-aware window features (Modern-Pool).

CoreMotion liefert motion.gravity in G's (units of standard gravity),
nicht m/s² — d. h. |g| ≈ 1.0 für ein ruhendes Wrist, nicht 9.81.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.features.gravity import (
    GRAVITY_FEATURE_NAMES,
    _gravity_window_features,
)


def _window(gx, gy, gz, n=50):
    """Build a synthetic window DataFrame with given gravity vector."""
    return pd.DataFrame({
        "gx": np.full(n, gx, dtype=float),
        "gy": np.full(n, gy, dtype=float),
        "gz": np.full(n, gz, dtype=float),
    })


def test_feature_names_are_six():
    assert len(GRAVITY_FEATURE_NAMES) == 6


def test_stationary_palm_down_z_axis_aligned_with_gravity():
    # Watch on flat surface, screen up: gravity points along -z (down).
    # tilt_z = arccos(-1) = pi. tilt_x = tilt_y = arccos(0) = pi/2.
    feats = _gravity_window_features(_window(0.0, 0.0, -1.0))

    assert feats["grav_mag_mean"] == pytest.approx(1.0, abs=1e-6)
    assert feats["grav_mag_std"] == pytest.approx(0.0, abs=1e-6)
    assert feats["tilt_z_mean"] == pytest.approx(math.pi, abs=1e-4)
    assert feats["tilt_x_mean"] == pytest.approx(math.pi / 2, abs=1e-4)
    assert feats["tilt_y_mean"] == pytest.approx(math.pi / 2, abs=1e-4)
    assert feats["tilt_change"] == pytest.approx(0.0, abs=1e-6)


def test_stationary_palm_side_x_axis_aligned():
    # Gravity along +x. tilt_x = arccos(1) = 0.
    feats = _gravity_window_features(_window(1.0, 0.0, 0.0))

    assert feats["tilt_x_mean"] == pytest.approx(0.0, abs=1e-4)
    assert feats["tilt_y_mean"] == pytest.approx(math.pi / 2, abs=1e-4)
    assert feats["tilt_z_mean"] == pytest.approx(math.pi / 2, abs=1e-4)


def test_tilt_change_picks_up_rotation_within_window():
    # Two halves of the window with different tilts → tilt_change > 0.
    n = 50
    half = n // 2
    df = pd.DataFrame({
        "gx": np.concatenate([np.zeros(half), np.ones(n - half)]),
        "gy": np.zeros(n),
        "gz": np.concatenate([-np.ones(half), np.zeros(n - half)]),
    })

    feats = _gravity_window_features(df)

    assert feats["tilt_change"] > 0.0
    # Rough sanity: a single 90° flip spread across the window's diffs
    # should average to a non-trivial radian value.
    assert feats["tilt_change"] < math.pi


def test_missing_gravity_columns_returns_nan_features():
    df = pd.DataFrame({"ax": [0.1] * 50, "ay": [0.2] * 50, "az": [0.3] * 50})

    feats = _gravity_window_features(df)

    assert set(feats.keys()) == set(GRAVITY_FEATURE_NAMES)
    for name, val in feats.items():
        assert math.isnan(val), f"{name} should be NaN, got {val}"


def test_nan_gravity_values_return_nan_features():
    df = pd.DataFrame({
        "gx": [0.0, np.nan, 0.0],
        "gy": [0.0, 0.0, 0.0],
        "gz": [-1.0, -1.0, -1.0],
    })

    feats = _gravity_window_features(df)

    for name, val in feats.items():
        assert math.isnan(val), f"{name} should be NaN, got {val}"


def test_tiny_gravity_magnitude_does_not_explode():
    # Near-zero gravity (free-fall, sensor error): should not crash on
    # division. tilt angles will be undefined but the function shouldn't
    # raise.
    df = pd.DataFrame({
        "gx": [1e-9] * 50,
        "gy": [0.0] * 50,
        "gz": [0.0] * 50,
    })

    feats = _gravity_window_features(df)

    # Must not raise; values can be anything finite or NaN.
    for val in feats.values():
        assert not math.isinf(val)
