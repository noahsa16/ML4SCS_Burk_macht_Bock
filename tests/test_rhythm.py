"""Tests fuer die Rhythmus-Features (src/features/rhythm.py) + windows-Opt-in."""
import numpy as np
import pandas as pd

from src.features.rhythm import (
    RHYTHM_FEATURE_NAMES,
    autocorr_peak,
    rhythm_window_features,
    spectral_flatness,
)
from src.features.windows import build_windows


def test_flatness_periodic_low_noise_high():
    fs = 50.0
    t = np.arange(50) / fs
    sine = np.sin(2 * np.pi * 6 * t)           # reine 6-Hz-Schwingung (peakig)
    rng = np.random.default_rng(0)
    noise = rng.normal(size=50)                 # breitbandig (flach)
    assert spectral_flatness(sine) < spectral_flatness(noise)
    assert spectral_flatness(np.ones(50)) == 1.0   # konstant -> maximal flach


def test_autocorr_peak_periodic_high_random_low():
    fs = 50.0
    t = np.arange(50) / fs
    sine = np.sin(2 * np.pi * 6 * t)           # periodisch -> hoher Peak
    rng = np.random.default_rng(1)
    rand = rng.normal(size=50)                  # irregulaer -> niedriger Peak
    assert autocorr_peak(sine, fs) > 0.5
    assert autocorr_peak(sine, fs) > autocorr_peak(rand, fs)
    assert autocorr_peak(np.ones(50), fs) == 0.0   # konstant -> 0


def test_rhythm_window_features_keys():
    acc = np.random.default_rng(2).normal(size=50)
    gyro = np.random.default_rng(3).normal(size=50)
    f = rhythm_window_features(acc, gyro, 50.0)
    assert set(f) == set(RHYTHM_FEATURE_NAMES)
    assert all(isinstance(v, float) for v in f.values())


def _synthetic_merged(n=200, fs=50.0, seed=0):
    rng = np.random.default_rng(seed)
    ts = (np.arange(n) * (1000.0 / fs)).astype(float)
    d = {"ts": ts, "local_ts_ms": ts,
         "label_writing": (np.arange(n) % 40 < 20).astype(int)}
    for c in ("ax", "ay", "az", "rx", "ry", "rz"):
        d[c] = rng.normal(size=n)
    return pd.DataFrame(d)


def test_build_windows_rhythm_optin_default_bit_identical():
    merged = _synthetic_merged()
    base = build_windows(merged, rhythm=False)
    withr = build_windows(merged, rhythm=True)
    # gleiche Fensterzahl; rhythm fuegt genau die 4 Spalten hinzu
    assert len(base) == len(withr)
    new_cols = set(withr.columns) - set(base.columns)
    assert new_cols == set(RHYTHM_FEATURE_NAMES)
    # bestehende Spalten unveraendert (bit-identisch)
    common = list(base.columns)
    pd.testing.assert_frame_equal(base[common], withr[common])
