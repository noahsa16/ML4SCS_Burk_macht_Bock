"""Tests fuer die destillierten tsfresh-Winner-Features + windows-Opt-in."""
import numpy as np
import pandas as pd

from src.features.tsfresh_winners import (
    WINNER_FEATURE_NAMES,
    autocorrelation,
    change_quantiles,
    cid_ce,
    tsfresh_winner_features,
)
from src.features.windows import build_windows


def test_autocorrelation_periodic_vs_noise():
    fs = 50.0
    t = np.arange(100) / fs
    # 10-Hz-Sinus: Periode = 5 Samples -> lag 5 stark positiv
    sine = np.sin(2 * np.pi * 10 * t)
    assert autocorrelation(sine, 5) > 0.9
    rng = np.random.default_rng(0)
    assert abs(autocorrelation(rng.normal(size=100), 5)) < 0.3
    assert autocorrelation(np.ones(50), 3) == 0.0  # konstant -> var-Guard


def test_change_quantiles_and_cid():
    rng = np.random.default_rng(1)
    x = rng.normal(size=100)
    cq = change_quantiles(x, 0.2, 0.8)
    assert cq > 0.0
    assert change_quantiles(np.ones(50), 0.2, 0.8) == 0.0
    assert cid_ce(np.ones(50)) == 0.0  # konstant -> 0
    smooth = np.sin(np.linspace(0, 2 * np.pi, 100))
    rough = rng.normal(size=100)
    assert cid_ce(rough) > cid_ce(smooth)  # rauer = komplexer


def test_winner_features_shape_and_names():
    rng = np.random.default_rng(2)
    w = rng.normal(size=(50, 6))
    f = tsfresh_winner_features(w)
    assert set(f) == set(WINNER_FEATURE_NAMES)
    assert len(f) == 42
    assert all(np.isfinite(v) for v in f.values())


def _synthetic_merged(n=200, fs=50.0, seed=0):
    rng = np.random.default_rng(seed)
    ts = (np.arange(n) * (1000.0 / fs)).astype(float)
    d = {"ts": ts, "local_ts_ms": ts,
         "label_writing": (np.arange(n) % 40 < 20).astype(int)}
    for c in ("ax", "ay", "az", "rx", "ry", "rz"):
        d[c] = rng.normal(size=n)
    return pd.DataFrame(d)


def test_build_windows_winners_optin_default_bit_identical():
    merged = _synthetic_merged()
    base = build_windows(merged, tsfresh_winners=False)
    withw = build_windows(merged, tsfresh_winners=True)
    assert len(base) == len(withw)
    assert set(withw.columns) - set(base.columns) == set(WINNER_FEATURE_NAMES)
    pd.testing.assert_frame_equal(base[list(base.columns)],
                                  withw[list(base.columns)])
