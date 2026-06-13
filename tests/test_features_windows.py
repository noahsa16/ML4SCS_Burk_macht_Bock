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


# ── Modern-Pool: gravity-aware features ─────────────────────────────


def _synthetic_merged_modern(duration_s: float, fs_hz: float) -> pd.DataFrame:
    """Wie _synthetic_merged + konstanter Gravity-Vektor (palm-down)."""
    df = _synthetic_merged(duration_s, fs_hz)
    n = len(df)
    df["gx"] = np.zeros(n)
    df["gy"] = np.zeros(n)
    df["gz"] = np.full(n, -1.0)
    return df


def test_legacy_merged_produces_no_gravity_features():
    merged = _synthetic_merged(10.0, 50.0)
    feats = build_windows(merged, max_gap_ms=0.0)

    assert "tilt_x_mean" not in feats.columns
    assert "tilt_z_mean" not in feats.columns
    assert "tilt_change" not in feats.columns


def test_modern_merged_appends_four_gravity_features():
    merged = _synthetic_merged_modern(10.0, 50.0)
    feats = build_windows(merged, max_gap_ms=0.0)

    from src.features.gravity import GRAVITY_FEATURE_NAMES
    for name in GRAVITY_FEATURE_NAMES:
        assert name in feats.columns, f"missing {name}"

    # Stationary palm-down gravity (gz = -1) → tilt_z ≈ π,
    # tilt_change ≈ 0 across all windows.
    assert (feats["tilt_z_mean"] - np.pi).abs().max() < 1e-4
    assert (feats["tilt_change"]).abs().max() < 1e-6


def test_partial_gravity_columns_treated_as_legacy():
    # Defensive: nur gx vorhanden (kaputter Export) → keine Gravity-Features.
    merged = _synthetic_merged(10.0, 50.0)
    merged["gx"] = 0.0
    feats = build_windows(merged, max_gap_ms=0.0)

    assert "tilt_z_mean" not in feats.columns


# ── Profil-sortierter CLI-Output (windows/{profile}/) ───────────────


import sys

import pytest

from src import profiles
from src.features import windows as W


@pytest.fixture
def proc(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "DATA_PROC", tmp_path)
    monkeypatch.setattr(profiles, "DATA_PROC", tmp_path)
    monkeypatch.setattr(profiles, "WINDOWS_DIR", tmp_path / "windows")
    return tmp_path


def _run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["python -m src.features", *argv])
    W.main()


def test_main_writes_legacy_merged_into_50hz_folder(proc, monkeypatch):
    _synthetic_merged(30.0, 50.0).to_csv(proc / "S900_merged.csv", index=False)

    _run_main(monkeypatch, "S900", "--max-gap-ms", "0")

    assert (proc / "windows" / "50hz" / "S900_windows.csv").exists()
    assert not (proc / "S900_windows.csv").exists()


def test_main_writes_modern_merged_into_100hz_grav_folder(proc, monkeypatch):
    _synthetic_merged_modern(30.0, 100.0).to_csv(proc / "S901_merged.csv", index=False)

    _run_main(monkeypatch, "S901", "--max-gap-ms", "0")

    assert (proc / "windows" / "100hz_grav" / "S901_windows.csv").exists()


def test_main_merged_suffix_reads_view_without_touching_native(proc, monkeypatch):
    # Modern-Session: native merged + Legacy-View-merged (Downsample-Bridge).
    # --merged-suffix legacy muss die View bauen und nativ unangetastet lassen.
    _synthetic_merged_modern(30.0, 100.0).to_csv(proc / "S902_merged.csv", index=False)
    _synthetic_merged(30.0, 50.0).to_csv(proc / "S902_merged_legacy.csv", index=False)

    _run_main(monkeypatch, "S902", "--merged-suffix", "legacy", "--max-gap-ms", "0")

    assert (proc / "windows" / "50hz" / "S902_windows.csv").exists()
    assert not (proc / "windows" / "100hz_grav" / "S902_windows.csv").exists()


def test_t_center_and_closing_follow_capture_clock():
    """t_center_ms und das Label-Closing müssen auf der per-Sample-Capture-
    Uhr (ts) rechnen, nicht auf der Batch-Ankunftszeit local_ts_ms — sonst
    werden Spill-Strecken (Ankunft Minuten später) zeitlich falsch verortet."""
    import numpy as np
    import pandas as pd
    from src.features.windows import build_windows, IMU_COLS

    n = 200  # 4 s @ 50 Hz
    ts = 1_700_000_000_000.0 + np.arange(n) * 20.0
    local = ts.copy()
    local[100:150] += 60_000.0  # eine 1-s-Strecke kommt 60 s verspätet an
    rng = np.random.default_rng(0)
    data = {c: rng.normal(size=n) for c in IMU_COLS}
    data["ts"] = ts
    data["local_ts_ms"] = local
    data["label_writing"] = 0
    merged = pd.DataFrame(data)

    out = build_windows(merged, window_sec=1.0, stride_sec=0.5, max_gap_ms=0)
    assert not out.empty
    t_center = out["t_center_ms"].to_numpy(dtype=float)
    assert t_center.min() >= ts.min()
    assert t_center.max() <= ts.max(), \
        "t_center_ms darf nicht in die Ankunftszeit der Spill-Strecke springen"
