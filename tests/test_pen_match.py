"""Tests for pen↔IMU variance-based alignment.

Synthetic IMU has high acceleration noise everywhere except inside three
defined "still" windows. We pretend the pen reported strokes at those
still windows MINUS some known offset (= the pen clock is δ ahead/behind
the watch clock by that much). Running pen_match should recover that δ.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.alignment import (
    DEFAULT_PARAMS,
    match_pen_data,
    pen_match,
    strokes_from_dot_types,
)


def _build_imu(
    duration_sec: float = 60.0,
    fs_hz: float = 50.0,
    still_windows: list[tuple[float, float]] | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthesize an IMU stream where ``still_windows`` (start,end seconds
    from t0) carry low acc-variance and everything else carries high noise.
    """
    rng = np.random.default_rng(seed)
    n = int(duration_sec * fs_hz)
    t0 = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
    timestamps = pd.to_datetime(
        [t0 + timedelta(seconds=i / fs_hz) for i in range(n)]
    )

    # High-noise baseline: σ=0.5 m/s² on top of gravity
    ax = rng.normal(0.0, 0.5, n).astype(np.float32)
    ay = rng.normal(0.0, 0.5, n).astype(np.float32)
    az = (9.81 + rng.normal(0.0, 0.5, n)).astype(np.float32)

    if still_windows:
        for s, e in still_windows:
            i0 = int(s * fs_hz)
            i1 = int(e * fs_hz)
            # Replace with σ=0.02 noise inside the window
            ax[i0:i1] = rng.normal(0.0, 0.02, i1 - i0).astype(np.float32)
            ay[i0:i1] = rng.normal(0.0, 0.02, i1 - i0).astype(np.float32)
            az[i0:i1] = (9.81 + rng.normal(0.0, 0.02, i1 - i0)).astype(np.float32)

    return pd.DataFrame({
        "timestamp": timestamps,
        "ax": ax, "ay": ay, "az": az,
    })


def _build_pen(
    stroke_windows_sec: list[tuple[float, float]],
    fs_hz: float = 80.0,
    pen_clock_offset_sec: float = 0.0,
) -> pd.DataFrame:
    """Build a pen DataFrame with strokes at given (start,end) seconds,
    optionally shifted by ``pen_clock_offset_sec`` relative to the watch.
    """
    t0 = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for sid, (s, e) in enumerate(stroke_windows_sec):
        n = max(2, int((e - s) * fs_hz))
        for i in range(n):
            t = s + (e - s) * i / (n - 1) + pen_clock_offset_sec
            rows.append({
                "timestamp": t0 + timedelta(seconds=t),
                "StrokeID": sid,
                "x": 10.0 + i, "y": 20.0,
            })
    return pd.DataFrame(rows)


def test_recovers_zero_offset():
    """Strokes aligned to still windows on a shared clock → δ ≈ 0."""
    still = [(10.0, 12.0), (25.0, 27.0), (40.0, 42.0)]
    imu = _build_imu(still_windows=still)
    pen = _build_pen(still, pen_clock_offset_sec=0.0)
    result = match_pen_data(imu, pen)
    assert result is not None
    assert abs(result.delta_sec) < 0.5, f"expected ~0, got {result.delta_sec}"
    # Clean signal → minimum should be a clear outlier in the search grid.
    assert result.sigma_minimal_variance < -2.0


def test_recovers_known_offset():
    """If the pen clock is 3 s ahead, the algorithm should report δ = -3."""
    still = [(10.0, 12.0), (25.0, 27.0), (40.0, 42.0)]
    imu = _build_imu(still_windows=still)
    # Pen says strokes occurred 3s LATER than they really did → we need
    # to subtract 3s from pen timestamps to recover alignment.
    pen = _build_pen(still, pen_clock_offset_sec=3.0)
    result = match_pen_data(imu, pen)
    assert result is not None
    assert abs(result.delta_sec - (-3.0)) < 0.2, \
        f"expected ~-3.0, got {result.delta_sec}"


def test_flat_curve_when_no_signal():
    """Without still windows, no shift produces a meaningful minimum."""
    imu = _build_imu(still_windows=None)  # uniform noise
    pen = _build_pen([(10.0, 12.0), (25.0, 27.0), (40.0, 42.0)])
    result = match_pen_data(imu, pen)
    assert result is not None
    # Sigma should be near zero (curve is flat) — definitely not strongly
    # negative.
    assert result.sigma_minimal_variance > -2.0, \
        f"expected weak signal, got sigma={result.sigma_minimal_variance}"


def test_strokes_from_dot_types():
    df = pd.DataFrame({
        "dot_type": ["PEN_DOWN", "PEN_MOVE", "PEN_MOVE", "PEN_UP",
                     "PEN_HOVER",
                     "PEN_DOWN", "PEN_MOVE", "PEN_UP"],
        "x": [10, 11, 12, 13, -1, 20, 21, 22],
        "y": [10, 10, 10, 10, -1, 20, 20, 20],
    })
    out = strokes_from_dot_types(df)
    # PEN_HOVER + framing event dropped → 7 rows, then drop the x=-1: 7 rows.
    # Actually: HOVER not in {DOWN,MOVE,UP} so dropped; x=-1 dropped via framing filter.
    # Remaining: 4 + 3 = 7 rows.
    assert len(out) == 7
    assert sorted(out["StrokeID"].unique().tolist()) == [0, 1]
    # First 4 rows are stroke 0, last 3 are stroke 1.
    assert (out["StrokeID"].iloc[:4] == 0).all()
    assert (out["StrokeID"].iloc[4:] == 1).all()


def test_strokes_from_dot_types_drops_orphan_moves():
    """PEN_MOVE before any PEN_DOWN should be dropped (no stroke open)."""
    df = pd.DataFrame({
        "dot_type": ["PEN_MOVE", "PEN_MOVE", "PEN_DOWN", "PEN_MOVE"],
        "x": [1, 2, 3, 4], "y": [1, 1, 1, 1],
    })
    out = strokes_from_dot_types(df)
    assert len(out) == 2  # only the rows from PEN_DOWN onward
    assert (out["StrokeID"] == 0).all()


def test_returns_none_for_empty_inputs():
    imu = _build_imu(duration_sec=1.0, still_windows=None)
    pen = pd.DataFrame(columns=["timestamp", "StrokeID", "x", "y"])
    assert match_pen_data(imu, pen) is None
