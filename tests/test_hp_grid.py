"""Grid-Search-Engine: grid_configs, GridSpec, Runner, Collect."""
from pathlib import Path

import pytest

from src.training.deep.hp_search import grid_configs, sobol_configs

GRID = {
    "lr": [3e-4, 1e-3],
    "dropout": [0.05, 0.2, 0.4],
    "batch_size": [64],
    "weight_decay": [1e-5, 1e-3],
}


def test_grid_configs_full_cartesian_product():
    cfgs = grid_configs(GRID)
    assert len(cfgs) == 2 * 3 * 1 * 2
    assert len({tuple(sorted(c.items())) for c in cfgs}) == len(cfgs)


def test_grid_configs_canonical_order_and_shape():
    cfgs = grid_configs(GRID)
    assert cfgs[0] == {"lr": 3e-4, "dropout": 0.05,
                       "batch_size": 64, "weight_decay": 1e-5}
    assert cfgs[1] == {"lr": 3e-4, "dropout": 0.05,
                       "batch_size": 64, "weight_decay": 1e-3}
    assert cfgs[-1] == {"lr": 1e-3, "dropout": 0.4,
                        "batch_size": 64, "weight_decay": 1e-3}
    assert set(cfgs[0]) == set(sobol_configs(1)[0])


def test_grid_configs_deterministic():
    assert grid_configs(GRID) == grid_configs(GRID)
