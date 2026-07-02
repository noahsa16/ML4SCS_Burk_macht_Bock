"""Tests fuer die Hard-Negative-Features (windows.py hard_negative_feats=True).

SHAP-Diff-Befund (reports/shap_hard_negative_diff.md): rx_band_3_8 und
gyro_mag_jerk_mean_abs trennen P17s Tippen von Schreiben schon korrekt, werden
aber von lauteren Accel-Jerk-Features ueberstimmt. Diese Opt-in-Features
verschaerfen beide Signale (Gyro-Achsen-Jerk, Accel-rx-Korrelation, Ratio).
"""
import numpy as np
import pandas as pd

from src.features.windows import build_windows

HARD_NEG_COLS = (
    "rx_jerk_std", "rx_jerk_mean_abs",
    "ry_jerk_std", "ry_jerk_mean_abs",
    "rz_jerk_std", "rz_jerk_mean_abs",
    "corr_ax_rx", "corr_ay_rx", "corr_az_rx",
    "rx_ay_ratio",
)


def _synthetic_merged(n=200, fs=50.0, seed=0):
    rng = np.random.default_rng(seed)
    ts = (np.arange(n) * (1000.0 / fs)).astype(float)
    d = {"ts": ts, "local_ts_ms": ts,
         "label_writing": (np.arange(n) % 40 < 20).astype(int)}
    for c in ("ax", "ay", "az", "rx", "ry", "rz"):
        d[c] = rng.normal(size=n)
    return pd.DataFrame(d)


def test_build_windows_hard_negative_optin_default_bit_identical():
    merged = _synthetic_merged()
    base = build_windows(merged, hard_negative_feats=False)
    withh = build_windows(merged, hard_negative_feats=True)
    assert len(base) == len(withh)
    new_cols = set(withh.columns) - set(base.columns)
    assert new_cols == set(HARD_NEG_COLS)
    common = list(base.columns)
    pd.testing.assert_frame_equal(base[common], withh[common])


def test_hard_negative_feats_finite_and_bounded():
    merged = _synthetic_merged(seed=1)
    withh = build_windows(merged, hard_negative_feats=True)
    for c in HARD_NEG_COLS:
        assert withh[c].apply(np.isfinite).all(), c
    # corr features stay in [-1, 1]
    for c in ("corr_ax_rx", "corr_ay_rx", "corr_az_rx"):
        assert withh[c].between(-1.0, 1.0).all()


def test_rx_ay_ratio_matches_manual_computation():
    merged = _synthetic_merged(seed=2)
    withh = build_windows(merged, hard_negative_feats=True)
    expected = withh["rx_band_3_8"] / (withh["ay_jerk_mean_abs"] + 1e-3)
    pd.testing.assert_series_equal(withh["rx_ay_ratio"], expected, check_names=False)


def test_rx_ay_ratio_stable_when_jerk_is_zero():
    # Warum: ay_jerk_mean_abs kann bei einem konstanten Signal 0 sein -- die
    # Ratio darf dann nicht explodieren/NaN werden (Divisions-Bug-Regression).
    n = 100
    d = {"ts": np.arange(n) * 20.0, "local_ts_ms": np.arange(n) * 20.0,
         "label_writing": np.zeros(n, dtype=int),
         "ax": np.zeros(n), "ay": np.zeros(n), "az": np.zeros(n),
         "rx": np.ones(n) * 0.5, "ry": np.zeros(n), "rz": np.zeros(n)}
    merged = pd.DataFrame(d)
    withh = build_windows(merged, hard_negative_feats=True)
    assert withh["ay_jerk_mean_abs"].eq(0.0).all()
    assert np.isfinite(withh["rx_ay_ratio"]).all()
