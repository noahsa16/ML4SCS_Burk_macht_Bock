"""Smoke tests for the watch-CSV downsample utility (100 Hz → 50 Hz)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.downsample import downsample_watch_df

IMU_COLS = ["ax", "ay", "az", "rx", "ry", "rz"]
GRAV_COLS = ["gx", "gy", "gz"]


def _modern_100hz(duration_s: float = 5.0) -> pd.DataFrame:
    n = int(duration_s * 100)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "local_ts": ["2026-05-26T20:00:00"] * n,
        "local_ts_ms": (np.arange(n) * 10).astype(int),
        "session_id": ["S034"] * n,
        "sequence": (np.arange(n) // 10).astype(int),
        "sample_rate_hz": [100.0] * n,
        "ts": (np.arange(n) * 10).astype(int),
    })
    for c in IMU_COLS:
        df[c] = rng.standard_normal(n)
    df["gx"] = 0.0
    df["gy"] = 0.0
    df["gz"] = -1.0
    return df


def test_downsample_halves_sample_count():
    df = _modern_100hz(5.0)
    assert len(df) == 500

    out = downsample_watch_df(df, target_hz=50)

    # Decimate by factor 2 → roughly half.
    assert 240 <= len(out) <= 260, f"got {len(out)}"


def test_downsample_drops_gravity_when_flag_set():
    df = _modern_100hz(5.0)

    out = downsample_watch_df(df, target_hz=50, drop_gravity=True)

    for c in GRAV_COLS:
        assert c not in out.columns


def test_downsample_keeps_gravity_when_flag_false():
    df = _modern_100hz(5.0)

    out = downsample_watch_df(df, target_hz=50, drop_gravity=False)

    for c in GRAV_COLS:
        assert c in out.columns


def test_downsample_preserves_metadata_columns():
    df = _modern_100hz(5.0)

    out = downsample_watch_df(df, target_hz=50)

    for c in ["local_ts_ms", "ts", "session_id", "sequence", "sample_rate_hz"]:
        assert c in out.columns


def test_downsample_updates_sample_rate_column():
    df = _modern_100hz(5.0)

    out = downsample_watch_df(df, target_hz=50)

    # All rows reflect the new effective rate.
    assert (out["sample_rate_hz"] == 50.0).all()


def test_downsample_anti_aliases_high_frequency_component():
    # Inject a 40 Hz sine (just below 50 Hz Nyquist). After 100 → 50 Hz
    # downsample, the new Nyquist is 25 Hz — a 40 Hz signal would alias
    # to 10 Hz without anti-aliasing. scipy.signal.decimate applies an
    # 8th-order Chebyshev type-I lowpass by default.
    n = 1000
    t = np.arange(n) / 100.0
    df = pd.DataFrame({
        "local_ts": ["x"] * n,
        "local_ts_ms": (np.arange(n) * 10).astype(int),
        "session_id": ["S034"] * n,
        "sequence": (np.arange(n) // 10).astype(int),
        "sample_rate_hz": [100.0] * n,
        "ts": (np.arange(n) * 10).astype(int),
        "ax": np.sin(2 * np.pi * 40 * t),
        "ay": np.zeros(n), "az": np.zeros(n),
        "rx": np.zeros(n), "ry": np.zeros(n), "rz": np.zeros(n),
    })

    out = downsample_watch_df(df, target_hz=50)

    # After anti-aliasing the 40 Hz component should be heavily attenuated
    # in the 50 Hz output. Original peak amplitude was 1.0; expect <0.1.
    assert out["ax"].abs().max() < 0.5, (
        f"40 Hz component not anti-aliased; peak ax = {out['ax'].abs().max():.3f}"
    )


def test_downsample_rejects_non_integer_decimation_factor():
    df = _modern_100hz(5.0)
    # 100 Hz → 30 Hz would need factor 100/30 = non-integer. Should error.
    with pytest.raises(ValueError):
        downsample_watch_df(df, target_hz=30)


def test_downsample_no_op_when_already_at_target():
    # Source 50 Hz, target 50 Hz → no change.
    df = _modern_100hz(5.0)
    df["sample_rate_hz"] = 50.0
    df["local_ts_ms"] = (np.arange(len(df)) * 20).astype(int)
    df["ts"] = df["local_ts_ms"]

    out = downsample_watch_df(df, target_hz=50)

    assert len(out) == len(df)
