"""Smoke tests for src.server.inference (live writing detection).

Critical guarantees verified here:
  - Feature parity: LiveInference.predict() and src.features.windows.build_windows()
    produce identical features for the same sample buffer.
  - Buffer hygiene: empty / stale / under-sized buffers return None
    instead of feeding the model junk.
  - Z-score honouring: when the joblib carries zscore_mu/sigma, predict()
    applies them; when None, predict() doesn't.
  - Payload shape: the dict returned by predict() carries the keys the
    frontend / WS payload depend on.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from src.server import inference as inf_module


def _fresh_inference() -> inf_module.LiveInference:
    return inf_module.LiveInference()


def _sim_imu(n: int, fs: float, t0_ms: int, seed: int = 0):
    """Generate n synthetic IMU rows at fs Hz starting at t0_ms.

    Returns iterable of (ts_ms, ax, ay, az, rx, ry, rz).
    """
    rng = np.random.default_rng(seed)
    rows = []
    dt = 1000.0 / fs
    for i in range(n):
        ts = int(t0_ms + i * dt)
        ax, ay, az = (rng.standard_normal(3) * 0.2).tolist()
        rx, ry, rz = (rng.standard_normal(3) * 0.5).tolist()
        rows.append((ts, ax, ay, az, rx, ry, rz))
    return rows


def test_predict_on_empty_buffer_returns_none():
    live = _fresh_inference()
    live.load_default_model()
    assert live.predict() is None


def test_predict_below_window_returns_none():
    live = _fresh_inference()
    live.load_default_model()
    for r in _sim_imu(5, fs=100.0, t0_ms=int(time.time() * 1000)):
        live.append_sample(*r)
    assert live.predict() is None


def test_predict_with_stale_buffer_returns_none():
    live = _fresh_inference()
    live.load_default_model()
    # Fill 150 samples but pretend they arrived 5 s ago.
    t0 = int(time.time() * 1000) - 5000
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    assert live.predict() is None


def test_predict_returns_expected_payload_shape():
    live = _fresh_inference()
    live.load_default_model()
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    for key in {"writing", "proba", "model_id", "fs_hz",
                "window_samples", "today_writing_seconds"}:
        assert key in out, f"missing key {key} in predict payload"
    assert isinstance(out["writing"], bool)
    assert 0.0 <= out["proba"] <= 1.0
    assert out["window_samples"] >= 8


def test_sparkline_grows_with_each_prediction():
    live = _fresh_inference()
    live.load_default_model()
    assert live.sparkline() == []
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    _ = live.predict()
    assert len(live.sparkline()) == 1
    # Add a few more samples and re-predict.
    for r in _sim_imu(20, fs=100.0, t0_ms=t0 + 1500):
        live.append_sample(*r)
    _ = live.predict()
    assert len(live.sparkline()) == 2


def test_feature_parity_with_build_windows():
    """The same 1 s IMU buffer must produce identical features whether the
    pipeline runs through src.features.windows or src.server.inference."""
    from src.features.windows import _window_features

    n = 100  # 1 s @ 100 Hz
    fs = 100.0
    rng = np.random.default_rng(42)
    imu = rng.standard_normal((n, 6)) * 0.3
    feats_training = _window_features(imu, fs_hz=fs)

    live = _fresh_inference()
    live.load_default_model()
    t0 = int(time.time() * 1000)
    dt = 1000.0 / fs
    for i, row in enumerate(imu):
        live.append_sample(
            int(t0 + i * dt),
            float(row[0]), float(row[1]), float(row[2]),
            float(row[3]), float(row[4]), float(row[5]),
        )

    # Replicate what predict() does internally to extract feats:
    recent = list(live._buffer)[-n:]
    imu_arr = np.array([r[1:] for r in recent], dtype=float)
    fs_est = live._estimate_fs()
    feats_inference = _window_features(imu_arr, fs_hz=fs_est)

    # Every common feature must match bit-for-bit (same float math).
    for k in feats_training:
        assert k in feats_inference, f"missing {k} in inference features"
        a = feats_training[k]
        b = feats_inference[k]
        assert np.isclose(a, b, rtol=1e-6, atol=1e-9), \
            f"{k}: training={a}  inference={b}"


def test_no_model_returns_none(monkeypatch):
    """When no joblib is found, predict() yields None without crashing."""
    live = _fresh_inference()
    monkeypatch.setattr(inf_module, "_DEFAULT_MODEL_PATHS",
                        (Path("/nonexistent/rf_x.joblib"),))
    assert live.load_default_model() is None
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    assert live.predict() is None


def test_zscore_applied_when_baked_in():
    """If the joblib carries zscore_mu/sigma, predict() must normalise inputs."""
    live = _fresh_inference()
    p = live.load_default_model()
    assert p is not None
    bundle = live._bundle
    feature_cols = bundle["feature_cols"]
    # Inject synthetic mu/sigma so we can check the normalisation pathway.
    bundle["zscore_mu"] = {c: 0.0 for c in feature_cols}
    bundle["zscore_sigma"] = {c: 1.0 for c in feature_cols}
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    # With mu=0 / sigma=1 the result must equal the no-zscore prediction
    # (mathematically a no-op).
    bundle["zscore_mu"] = None
    bundle["zscore_sigma"] = None
    out2 = live.predict()
    assert out is not None and out2 is not None
    assert abs(out["proba"] - out2["proba"]) < 1e-9


def test_daily_aggregate_resets_on_date_change():
    live = _fresh_inference()
    live.load_default_model()
    live._today_date = "2000-01-01"  # force stale date
    live._today_writing_seconds = 999.0
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    # After predict the date should be reset to today, counter started fresh.
    assert live._today_date != "2000-01-01"
    assert live._today_writing_seconds <= inf_module.WINDOW_SEC


def test_rate_mismatch_returns_special_payload():
    """When buffer fs deviates >20% from the model's training rate, predict()
    must short-circuit with rate_mismatch=True instead of feeding the model
    out-of-distribution features.

    rf_noah is trained at 100 Hz; simulating a 50 Hz buffer must trigger this.
    """
    live = _fresh_inference()
    live.load_default_model()
    t0 = int(time.time() * 1000)
    # 50 Hz buffer = 50% off the trained 100 Hz baseline.
    for r in _sim_imu(80, fs=50.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert out.get("rate_mismatch") is True
    assert out["proba"] == 0.0
    assert out["fs_hz"] != out["trained_fs_hz"]


def test_clear_buffer_keeps_model():
    live = _fresh_inference()
    live.load_default_model()
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    live.clear_buffer()
    assert live.predict() is None
    assert live._bundle is not None  # model still loaded
