import numpy as np
from src.features.gravity_highpass import GravityHighPass


def test_removes_constant_gravity():
    rng = np.random.default_rng(0)
    n = 500
    gravity = np.array([0.0, 0.0, 1.0])
    dynamic = 0.05 * rng.standard_normal((n, 3))
    raw = gravity + dynamic
    user = GravityHighPass(alpha=0.9).process(raw)
    # after warmup the constant gravity component is gone -> mean ~0
    assert np.allclose(user[100:].mean(axis=0), 0.0, atol=0.02)


def test_state_continuity_matches_whole_pass():
    rng = np.random.default_rng(1)
    raw = np.array([0.0, 0.0, 1.0]) + 0.1 * rng.standard_normal((200, 3))
    whole = GravityHighPass(0.9).process(raw)

    hp = GravityHighPass(0.9)
    first = hp.process(raw[:120])
    saved = hp.state
    resumed = GravityHighPass(0.9)
    resumed.restore(saved)
    second = resumed.process(raw[120:])

    assert np.allclose(np.vstack([first, second]), whole)
