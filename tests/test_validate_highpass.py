# tests/test_validate_highpass.py
import numpy as np
from scripts.ml.validate_highpass import highpass_feature_agreement


def test_agreement_high_for_synthetic_useraccel():
    # synthetic: true userAccel is mean-zero dynamic; raw = userAccel + constant gravity
    rng = np.random.default_rng(0)
    n, fs = 600, 50.0
    true_user = np.column_stack([
        0.1 * np.sin(2 * np.pi * 4 * np.arange(n) / fs),
        0.1 * rng.standard_normal(n),
        0.1 * np.cos(2 * np.pi * 3 * np.arange(n) / fs),
    ])
    raw = true_user + np.array([0.0, 0.0, 1.0])
    cols = ["ax_std", "ay_std", "az_std", "ax_jerk_std"]
    out = highpass_feature_agreement(true_user, raw, fs, cols, alpha=0.9)
    # dynamic, mean-invariant features should agree well after high-pass
    assert out["corr"] > 0.95
    assert out["max_abs"] < 0.05
