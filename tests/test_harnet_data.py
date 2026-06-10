"""Smoke-Tests fuer die harnet-Daten-Bruecke (vor jedem Training).

Deckt ab: Fenster-Shapes, Resample-Laengen-Arithmetik (50/100 -> 30 Hz),
Label-Mehrheitslogik, Stable-Sort-Invarianz bei local_ts_ms-Ties
(Regression analog test_merge), und dass die Fenster-Werte im g-Bereich
bleiben (kein versehentlicher Z-Score).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.signal import resample_poly

from src.training.deep import harnet_data as hd
from src.training.deep.harnet_data import (
    HARNET_VARIANTS,
    STRIDE_SAMPLES,
    WIN_SAMPLES,
    build_harnet_windows,
    detect_source_hz,
    load_session_harnet,
)


def _synthetic_merged(
    n: int = 500, fs: int = 50, dc: float = 0.05, amp: float = 0.02,
    writing_first_half: bool = True, tied_local: bool = False,
) -> pd.DataFrame:
    """Watch-base merged-CSV: kleine g-Accel (DC + Sinus), 1. Haelfte writing.

    ``ts`` ist die monotone per-Sample-Uhr (ms); ``local_ts_ms`` traegt
    Batch-Ties (10 Samples pro Stempel) wie echte Daten. ``tied_local=True``
    macht local_ts_ms komplett konstant — Extremfall fuer den Sort-Test.
    """
    t0 = 1_778_850_000_000
    dt_ms = round(1000 / fs)
    ts = t0 + np.arange(n) * dt_ms
    if tied_local:
        local = np.full(n, float(t0))
    else:
        local = (t0 + (np.arange(n) // 10) * (10 * dt_ms)).astype(float)
    rng = np.random.default_rng(0)
    base = dc + amp * np.sin(np.arange(n) * 0.1)
    if writing_first_half:
        label = np.where(np.arange(n) < n // 2, 1, 0)
    else:
        label = np.zeros(n, dtype=int)
    return pd.DataFrame({
        "ts": ts,
        "local_ts_ms": local,
        "ax": base, "ay": base * 0.5, "az": base * -0.3,
        "rx": rng.normal(size=n), "ry": rng.normal(size=n), "rz": rng.normal(size=n),
        "label_writing": label,
    })


def test_build_shape_50hz():
    """500 Samples @ 50 Hz -> 300 @ 30 Hz -> 3 Fenster (win 150, stride 75)."""
    X, y, t = build_harnet_windows(_synthetic_merged(n=500, fs=50), source_hz=50)
    assert X.shape == (3, 3, WIN_SAMPLES)  # (n_windows, 3 Kanaele, 150)
    assert y.shape == (3,) and t.shape == (3,)
    assert X.dtype == np.float32
    assert set(np.unique(y)).issubset({0, 1})


def test_build_shape_100hz():
    """600 Samples @ 100 Hz -> 180 @ 30 Hz -> 1 Fenster."""
    X, y, t = build_harnet_windows(_synthetic_merged(n=600, fs=100), source_hz=100)
    assert X.shape == (1, 3, WIN_SAMPLES)
    assert len(y) == 1 and len(t) == 1


def test_build_shape_harnet10_window():
    """harnet10 nutzt 300/150: 1000 @ 50 Hz -> 600 @ 30 Hz -> 3 Fenster (3,300)."""
    v = HARNET_VARIANTS["harnet10"]
    assert (v["win_samples"], v["stride_samples"]) == (300, 150)
    X, y, t = build_harnet_windows(
        _synthetic_merged(n=1000, fs=50), source_hz=50,
        win_samples=v["win_samples"], stride_samples=v["stride_samples"],
    )
    # (600-300)//150 + 1 = 3
    assert X.shape == (3, 3, 300)
    assert len(y) == 3 and len(t) == 3


def test_harnet_variants_table():
    assert HARNET_VARIANTS["harnet5"] == {"win_samples": 150, "stride_samples": 75}
    assert HARNET_VARIANTS["harnet10"] == {"win_samples": 300, "stride_samples": 150}


def test_resample_length_arithmetic():
    """resample_poly-Laenge = ceil(n*up/down): 500@50->300, 600@100->180."""
    assert len(resample_poly(np.zeros(500), 3, 5)) == 300
    assert len(resample_poly(np.zeros(600), 3, 10)) == 180
    # Fensterzahl konsistent: (300-150)//75 + 1 = 3 ; (180-150)//75 + 1 = 1
    assert (300 - WIN_SAMPLES) // STRIDE_SAMPLES + 1 == 3
    assert (180 - WIN_SAMPLES) // STRIDE_SAMPLES + 1 == 1


def test_label_majority():
    """Fenster ganz in der writing-Haelfte -> 1, ganz in idle -> 0."""
    X, y, t = build_harnet_windows(
        _synthetic_merged(n=600, fs=50, writing_first_half=True), source_hz=50
    )
    assert y[0] == 1
    assert y[-1] == 0


def test_stable_sort_invariance_under_local_ts_ties():
    """Shuffle der Zeilen aendert die Fenster nicht — sortiert wird nach ts.

    Regression zum Sort-Stability-Bug: local_ts_ms ist hier komplett konstant
    (Extrem-Ties). Wuerde nach local_ts_ms statt ts sortiert, scrambled die
    Shuffle-Reihenfolge die Samples und die Fenster waeren verschieden.
    """
    merged = _synthetic_merged(n=500, fs=50, tied_local=True)
    X_sorted, y_sorted, _ = build_harnet_windows(merged, source_hz=50)

    shuffled = merged.sample(frac=1.0, random_state=7).reset_index(drop=True)
    X_shuf, y_shuf, _ = build_harnet_windows(shuffled, source_hz=50)

    np.testing.assert_array_equal(X_sorted, X_shuf)
    np.testing.assert_array_equal(y_sorted, y_shuf)


def test_values_stay_in_g_range_no_zscore():
    """Fenster-Werte bleiben klein (g), DC-Offset erhalten — kein Z-Score.

    Ein versehentlicher Per-Kanal-Z-Score wuerde auf Mittel 0 / Std 1
    zentrieren: |Werte| ~ O(1) und Mittel ~ 0. Roh-g bleibt ~0.02 g.
    """
    X, _, _ = build_harnet_windows(_synthetic_merged(n=500, fs=50), source_hz=50)
    assert np.abs(X).max() < 1.0           # z-skaliert waere |max| ~ O(1.4)
    assert 0.005 < float(X.mean()) < 0.1   # DC-Offset erhalten, nicht zentriert


def test_detect_source_hz():
    assert detect_source_hz(np.arange(0, 1000, 20, dtype=float)) == 50   # dt=20
    assert detect_source_hz(np.arange(0, 1000, 10, dtype=float)) == 100  # dt=10


def test_detect_source_hz_out_of_band_raises():
    with pytest.raises(ValueError, match="ausserhalb"):
        detect_source_hz(np.arange(0, 1000, 50, dtype=float))  # 20 Hz, ungueltig


def test_build_missing_column_raises():
    merged = _synthetic_merged().drop(columns=["ax"])
    with pytest.raises(ValueError, match="missing columns"):
        build_harnet_windows(merged, source_hz=50)


def test_build_bad_source_hz_raises():
    with pytest.raises(ValueError, match="source_hz must be"):
        build_harnet_windows(_synthetic_merged(), source_hz=30)


def test_build_too_short_returns_empty():
    """50 Samples @ 50 Hz -> 30 @ 30 Hz < 150 -> leere Fenster."""
    X, y, t = build_harnet_windows(_synthetic_merged(n=50, fs=50), source_hz=50)
    assert X.shape == (0, 3, WIN_SAMPLES)
    assert len(y) == 0 and len(t) == 0


def test_load_session_harnet_detects_rate(tmp_path, monkeypatch):
    """load_session_harnet liest native merged, detektiert die Rate aus ts."""
    monkeypatch.setattr(hd, "DATA_PROC", tmp_path)
    _synthetic_merged(n=500, fs=50).to_csv(tmp_path / "S999_merged.csv", index=False)
    X, y, t = load_session_harnet("S999")
    assert X.shape == (3, 3, WIN_SAMPLES)


def test_load_session_harnet_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(hd, "DATA_PROC", tmp_path)
    with pytest.raises(FileNotFoundError, match="src.merge"):
        load_session_harnet("S999")
