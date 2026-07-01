"""Tests for Sobol-based hyperparameter sampling."""
from src.training.deep.hp_search import sobol_configs, is_at_boundary


def test_sobol_configs_shape_and_ranges():
    cfgs = sobol_configs(16, seed=0)
    assert len(cfgs) == 16
    for c in cfgs:
        assert 1e-4 <= c["lr"] <= 1e-2
        assert 0.0 <= c["dropout"] <= 0.5
        assert c["batch_size"] in (32, 64, 128)
        assert 1e-6 <= c["weight_decay"] <= 1e-2


def test_sobol_deterministic():
    assert sobol_configs(8, seed=1) == sobol_configs(8, seed=1)
    assert sobol_configs(8, seed=1) != sobol_configs(8, seed=2)


def test_is_at_boundary():
    assert is_at_boundary(1e-4, 1e-4, 1e-2, log=True)      # unten am Rand
    assert is_at_boundary(1e-2, 1e-4, 1e-2, log=True)      # oben am Rand
    assert not is_at_boundary(1e-3, 1e-4, 1e-2, log=True)  # Mitte
