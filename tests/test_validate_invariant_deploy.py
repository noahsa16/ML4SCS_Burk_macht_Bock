import numpy as np
from scripts.ml.validate_invariant_deploy import invariant_features


def test_features_unchanged_by_constant_gravity_offset():
    # The (b) claim: invariant features are identical under a constant offset.
    rng = np.random.default_rng(0)
    user = 0.1 * rng.standard_normal((100, 3))
    raw = user + np.array([0.3, -0.5, 0.8])  # constant gravity vector
    cols = ["ax_std", "ax_range", "ax_zcr", "ax_jerk_std", "corr_ax_ay", "ay_band_3_8"]
    fu = invariant_features(user, 50.0, cols)
    fr = invariant_features(raw, 50.0, cols)
    assert np.allclose(fu, fr, atol=1e-9)
