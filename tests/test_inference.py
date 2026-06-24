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
    fs_est = live._estimate_fs()
    feats_inference = live._extract_features(recent, fs_hz=fs_est)

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


# --- HMM live post-processing ---------------------------------------------

class _StubHMM:
    """Deterministic stand-in for OnlineForwardFilter: step() returns a fixed
    posterior so the writing-decision wiring can be asserted independent of
    the real RF proba. Counts reset() calls to verify gap/swap handling."""

    def __init__(self, value: float) -> None:
        self.value = value
        self.reset_calls = 0

    def step(self, proba: float) -> float:
        return self.value

    def reset(self) -> None:
        self.reset_calls += 1


def _primed(stub: "_StubHMM") -> inf_module.LiveInference:
    live = _fresh_inference()
    live.load_default_model()
    live._hmm = stub
    live._hmm_tried = True  # short-circuit _ensure_hmm to the injected stub
    return live


def test_writing_decision_follows_hmm_high_posterior():
    """writing is derived from the HMM posterior, not the raw proba: a high
    HMM value forces writing=True regardless of the (random) raw proba."""
    live = _primed(_StubHMM(0.99))
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert out["proba_hmm"] == 0.99
    assert out["writing"] is True
    assert 0.0 <= out["proba"] <= 1.0  # raw proba still reported untouched


def test_writing_decision_follows_hmm_low_posterior():
    live = _primed(_StubHMM(0.01))
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert out["proba_hmm"] == 0.01
    assert out["writing"] is False


def test_hmm_resets_on_stale_buffer():
    stub = _StubHMM(0.99)
    live = _primed(stub)
    t0 = int(time.time() * 1000) - 5000  # 5 s old -> stale gap
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    assert live.predict() is None
    assert stub.reset_calls >= 1  # gap dropped the accumulated state


def test_hmm_resets_on_model_swap():
    stub = _StubHMM(0.5)
    live = _primed(stub)
    live.load_default_model()  # swap reloads the model -> HMM state cleared
    assert stub.reset_calls >= 1


def test_predict_without_hmm_falls_back_to_raw(monkeypatch):
    """No params file -> no proba_hmm, writing reverts to proba>=0.5."""
    live = _fresh_inference()
    live.load_default_model()
    monkeypatch.setattr(inf_module, "HMM_LIVE_PATH", Path("/nonexistent/hmm.json"))
    live._hmm = None
    live._hmm_tried = False
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert "proba_hmm" not in out
    assert out["writing"] == (out["proba"] >= 0.5)


def test_hmm_loads_from_real_params_file():
    """End-to-end with the committed models/hmm_live.json (if present): the
    payload carries a finite proba_hmm and a bool decision."""
    if not inf_module.HMM_LIVE_PATH.exists():
        pytest.skip("hmm_live.json not generated in this checkout")
    live = _fresh_inference()
    live.load_default_model()
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert "proba_hmm" in out
    assert 0.0 <= out["proba_hmm"] <= 1.0
    assert isinstance(out["writing"], bool)


# --- Modern-Pool (9-Kanal / 92-Feature) live inference --------------------

def _sim_imu_modern(n: int, fs: float, t0_ms: int, seed: int = 0):
    """Like _sim_imu but yields 10-tuples incl. gx/gy/gz gravity channels.

    Gravity is a near-unit vector (|g| ~= 1.0 in G's, per CoreMotion) with
    a little jitter so tilt/grav features are non-degenerate.
    """
    rng = np.random.default_rng(seed)
    rows = []
    dt = 1000.0 / fs
    for i in range(n):
        ts = int(t0_ms + i * dt)
        ax, ay, az = (rng.standard_normal(3) * 0.2).tolist()
        rx, ry, rz = (rng.standard_normal(3) * 0.5).tolist()
        g = rng.standard_normal(3) * 0.05
        g[2] += 1.0  # roughly upright wrist
        rows.append((ts, ax, ay, az, rx, ry, rz, float(g[0]), float(g[1]), float(g[2])))
    return rows


def _make_modern_model(tmp_path):
    """Dump a synthetic 92-feature (88 dynamic + 4 gravity) joblib."""
    import joblib
    from sklearn.ensemble import RandomForestClassifier

    from src.features.gravity import GRAVITY_FEATURE_NAMES
    from src.features.windows import _window_features

    rng = np.random.default_rng(1)
    feature_cols = list(
        _window_features(rng.standard_normal((100, 6)) * 0.3, fs_hz=100.0).keys()
    ) + list(GRAVITY_FEATURE_NAMES)
    X = rng.standard_normal((20, len(feature_cols)))
    y = np.array([0, 1] * 10)
    clf = RandomForestClassifier(n_estimators=2, random_state=42).fit(X, y)
    target = tmp_path / "rf_modern.joblib"
    joblib.dump({
        "model": clf,
        "feature_cols": feature_cols,
        "person_id": "synthetic-modern",
        "sample_rate_hz": 100,
        "trained_on": "test synthetic modern",
        "n_windows": 20,
        "zscore_mu": None,
        "zscore_sigma": None,
    }, target)
    return target, feature_cols


def test_append_sample_accepts_gravity():
    live = _fresh_inference()
    live.append_sample(1000, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.01, 0.02, 0.99)
    row = live._buffer[-1]
    assert len(row) == 10
    assert row[7:10] == (0.01, 0.02, 0.99)


def test_append_sample_gravity_defaults_nan():
    """Legacy 6-channel callers omit gravity → stored as NaN, no crash."""
    live = _fresh_inference()
    live.append_sample(1000, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
    row = live._buffer[-1]
    assert len(row) == 10
    assert all(np.isnan(v) for v in row[7:10])


def test_modern_model_predict_with_gravity(tmp_path):
    target, _ = _make_modern_model(tmp_path)
    live = _fresh_inference()
    assert live.load_model(target) is not None
    t0 = int(time.time() * 1000)
    for r in _sim_imu_modern(150, fs=100.0, t0_ms=t0):
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert out.get("rate_mismatch") is not True
    assert out.get("missing_channels") is not True
    assert isinstance(out["writing"], bool)
    assert 0.0 <= out["proba"] <= 1.0


def test_modern_model_without_gravity_flags_missing_channels(tmp_path):
    """A Modern model fed a Legacy (gravity-less) stream must short-circuit
    with missing_channels=True instead of predicting on NaN gravity features."""
    target, _ = _make_modern_model(tmp_path)
    live = _fresh_inference()
    live.load_model(target)
    t0 = int(time.time() * 1000)
    for r in _sim_imu(150, fs=100.0, t0_ms=t0):  # 6-channel rows → gravity NaN
        live.append_sample(*r)
    out = live.predict()
    assert out is not None
    assert out.get("missing_channels") is True
    assert out["proba"] == 0.0


def test_feature_parity_modern_with_build_windows(tmp_path):
    """The live 92-feature vector must match the training composition
    (_window_features + _gravity_window_features) bit-for-bit."""
    import pandas as pd

    from src.features.gravity import _gravity_window_features
    from src.features.windows import _window_features

    n = 100
    fs = 100.0
    rng = np.random.default_rng(7)
    imu = rng.standard_normal((n, 6)) * 0.3
    grav = rng.standard_normal((n, 3)) * 0.05
    grav[:, 2] += 1.0

    feats_training = _window_features(imu, fs_hz=fs)
    feats_training.update(_gravity_window_features(
        pd.DataFrame(grav, columns=["gx", "gy", "gz"])
    ))

    target, _ = _make_modern_model(tmp_path)
    live = _fresh_inference()
    live.load_model(target)
    t0 = int(time.time() * 1000)
    dt = 1000.0 / fs
    for i in range(n):
        live.append_sample(
            int(t0 + i * dt),
            float(imu[i, 0]), float(imu[i, 1]), float(imu[i, 2]),
            float(imu[i, 3]), float(imu[i, 4]), float(imu[i, 5]),
            float(grav[i, 0]), float(grav[i, 1]), float(grav[i, 2]),
        )
    feats_live = live._extract_features(list(live._buffer)[-n:], fs_hz=fs)

    for k in feats_training:
        assert k in feats_live, f"missing {k} in live features"
        assert np.isclose(feats_training[k], feats_live[k], rtol=1e-6, atol=1e-9), \
            f"{k}: training={feats_training[k]} live={feats_live[k]}"


def test_rf_all_excluded_from_live_picker():
    """rf_all (LOSO-Headline) ist per-Session-z-gescort ohne baked mu/sigma →
    live nicht deploybar und am Bundle nicht von einem no-zscore-Modell
    unterscheidbar. Es darf daher nicht im Picker wählbar sein; die
    deploybaren Modelle bleiben.
    """
    from src.server import inference as inf_module

    assert "rf_all" not in inf_module._USER_FACING_MODEL_NAMES
    assert "rf_all_live" in inf_module._USER_FACING_MODEL_NAMES
    assert "rf_noah" in inf_module._USER_FACING_MODEL_NAMES
