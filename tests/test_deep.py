"""Smoke-Tests fuer das Deep-Sequenz-Modell-Paket."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.training.deep.data import build_raw_windows


def _synthetic_merged(n_samples: int = 600) -> pd.DataFrame:
    """600 Samples @ 50 Hz = 12 s; erste Haelfte writing, zweite idle."""
    t0 = 1_700_000_000_000.0
    times = t0 + np.arange(n_samples) * 20.0  # 20 ms Abstand = 50 Hz
    rng = np.random.default_rng(0)
    label = np.where(np.arange(n_samples) < n_samples // 2, 1, 0)
    return pd.DataFrame({
        "local_ts_ms": times,
        "ax": rng.normal(size=n_samples), "ay": rng.normal(size=n_samples),
        "az": rng.normal(size=n_samples), "rx": rng.normal(size=n_samples),
        "ry": rng.normal(size=n_samples), "rz": rng.normal(size=n_samples),
        "label_writing": label,
    })


def test_build_raw_windows_shape():
    merged = _synthetic_merged()
    X, y, t = build_raw_windows(merged, seq_len=50, stride=25)
    # 600 Samples, win=50, stride=25 -> (600-50)/25 + 1 = 23 Fenster
    assert X.shape == (23, 50, 6)
    assert y.shape == (23,)
    assert t.shape == (23,)
    assert X.dtype == np.float32
    assert set(np.unique(y)).issubset({0, 1})


def test_build_raw_windows_seq_len_250():
    merged = _synthetic_merged()
    X, _, _ = build_raw_windows(merged, seq_len=250, stride=25)
    # (600-250)/25 + 1 = 15 Fenster
    assert X.shape == (15, 250, 6)


def test_build_raw_windows_label_threshold():
    merged = _synthetic_merged()
    X, y, _ = build_raw_windows(merged, seq_len=50, stride=25,
                                max_gap_ms=0.0)
    # Fruehe Fenster (ganz in der writing-Haelfte) -> 1, spaete -> 0.
    assert y[0] == 1
    assert y[-1] == 0


def test_build_raw_windows_too_short_returns_empty():
    merged = _synthetic_merged(n_samples=10)
    X, y, t = build_raw_windows(merged, seq_len=50, stride=25)
    assert X.shape == (0, 50, 6)
    assert len(y) == 0 and len(t) == 0


def test_build_raw_windows_missing_column_raises():
    merged = _synthetic_merged().drop(columns=["rz"])
    with pytest.raises(ValueError, match="missing columns"):
        build_raw_windows(merged, seq_len=50)
