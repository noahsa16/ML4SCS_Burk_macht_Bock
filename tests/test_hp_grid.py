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


import csv

from src.training import events as _events
from src.training.deep.history import epoch_history_sink, tee


def _epoch_ev(fold, epoch, loss=0.5, auc=0.8, vl=0.6, va=0.7):
    return {"type": _events.EPOCH, "fold": fold, "epoch": epoch,
            "loss": loss, "val_auc": auc, "val_loss": vl, "val_acc": va}


def test_history_sink_writes_long_format(tmp_path):
    p = tmp_path / "history_tcn6-g00-s42.csv"
    sink = epoch_history_sink(p, model="tcn6", cfg_id="g00", seed=42, lr=1e-3)
    sink({"type": _events.FOLD_START, "idx": 0, "person": "P01+P02"})
    sink(_epoch_ev(0, 0))
    sink(_epoch_ev(0, 1, loss=0.4))
    sink({"type": _events.FOLD_START, "idx": 1, "person": "P03+P04"})
    sink(_epoch_ev(1, 0))
    sink({"type": _events.RUN_END})
    rows = list(csv.DictReader(p.open()))
    assert len(rows) == 3
    assert list(rows[0]) == ["model", "cfg_id", "seed", "held_out", "epoch",
                             "lr", "train_loss", "val_loss", "val_acc", "val_auc"]
    assert rows[0]["held_out"] == "P01+P02"
    assert rows[2]["held_out"] == "P03+P04"
    assert float(rows[1]["train_loss"]) == 0.4
    assert rows[0]["cfg_id"] == "g00" and rows[0]["seed"] == "42"


def test_history_sink_truncates_on_reopen(tmp_path):
    p = tmp_path / "h.csv"
    s1 = epoch_history_sink(p, "tcn6", "g00", 42, 1e-3)
    s1({"type": _events.FOLD_START, "idx": 0, "person": "P01"})
    s1(_epoch_ev(0, 0))
    s2 = epoch_history_sink(p, "tcn6", "g00", 42, 1e-3)
    s2({"type": _events.FOLD_START, "idx": 0, "person": "P01"})
    s2(_epoch_ev(0, 0))
    assert len(list(csv.DictReader(p.open()))) == 1


def test_tee_calls_all_in_order(tmp_path):
    calls = []
    cb = tee(lambda e: calls.append(("a", e["type"])),
             lambda e: calls.append(("b", e["type"])))
    cb({"type": "x"})
    assert calls == [("a", "x"), ("b", "x")]
