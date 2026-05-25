"""Regression tests for fs_hz handling in src.features.windows.

Background: until 2026-05-24 build_windows() defaulted fs_hz=50 hardcoded.
S032 100-Hz-Selbsttest deckte auf, dass Fensterlaenge / Stride / FFT-Bins /
Jerk-Skalierung dann allesamt um Faktor 2 daneben liegen. Diese Tests
verriegeln den Fix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.windows import build_windows, infer_fs_hz

IMU_COLS = ["ax", "ay", "az", "rx", "ry", "rz"]


def _synthetic_merged(duration_s: float, fs_hz: float) -> pd.DataFrame:
    n = int(duration_s * fs_hz)
    t_ms = np.arange(n) * (1000.0 / fs_hz)
    rng = np.random.default_rng(0)
    data = {c: rng.standard_normal(n) for c in IMU_COLS}
    data["local_ts_ms"] = t_ms
    data["label_writing"] = (np.arange(n) % 2).astype(int)
    return pd.DataFrame(data)


def test_infer_fs_hz_50():
    merged = _synthetic_merged(10.0, 50.0)
    assert abs(infer_fs_hz(merged) - 50.0) < 0.1


def test_infer_fs_hz_100():
    merged = _synthetic_merged(10.0, 100.0)
    assert abs(infer_fs_hz(merged) - 100.0) < 0.1


def test_infer_fs_hz_robust_to_batching():
    # Simuliere Batch=40 @ 100Hz: alle 40 Samples teilen sich denselben
    # local_ts_ms, naechster Batch 400ms spaeter. Eine median(diff)-Inferenz
    # wuerde hier faelschlich 2.5 Hz liefern.
    n_batches = 50
    batch = 40
    t_ms = np.repeat(np.arange(n_batches) * 400.0, batch)
    n = len(t_ms)
    rng = np.random.default_rng(0)
    df = pd.DataFrame({c: rng.standard_normal(n) for c in IMU_COLS})
    df["local_ts_ms"] = t_ms
    df["label_writing"] = 0
    fs = infer_fs_hz(df)
    assert 90 < fs < 105, f"erwartete ~100 Hz, bekam {fs:.2f}"


def test_infer_fs_hz_falls_back_when_short():
    df = pd.DataFrame({c: [0.0] for c in IMU_COLS} | {"local_ts_ms": [0.0], "label_writing": [0]})
    assert infer_fs_hz(df, fallback=50.0) == 50.0


def test_build_windows_window_count_independent_of_rate():
    # 60s session: erwarte ~ (60 - 1) / 0.5 + 1 = 119 Fenster bei jedem Rate.
    expected = 119
    for fs in (50.0, 100.0):
        merged = _synthetic_merged(60.0, fs)
        feats = build_windows(merged, max_gap_ms=0.0)
        assert len(feats) == expected, f"fs={fs}Hz lieferte {len(feats)} statt {expected}"


def test_build_windows_explicit_fs_overrides_inference():
    # Erzwingt fs_hz=50 auch bei 100-Hz-Daten -> doppelt so viele Fenster
    merged = _synthetic_merged(60.0, 100.0)
    feats_auto = build_windows(merged, max_gap_ms=0.0)              # auto = 100Hz
    feats_forced = build_windows(merged, fs_hz=50.0, max_gap_ms=0.0)  # alte Bug-Pfad
    assert len(feats_forced) > len(feats_auto)
