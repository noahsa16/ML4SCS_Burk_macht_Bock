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


import json

from pydantic import ValidationError

from src.training.deep.grid import GridSpec, load_grid_spec

VALID = {
    "model": "tcn6", "pool": "legacy", "win": 5, "folds": 5,
    "seeds": [42, 43, 44], "max_epochs": 120, "patience": 8,
    "grid": {"lr": [3e-4, 1e-3, 3e-3], "dropout": [0.05, 0.2, 0.4],
             "batch_size": [64, 128], "weight_decay": [1e-5, 1e-3]},
}


def test_grid_spec_valid_roundtrip(tmp_path):
    p = tmp_path / "tcn6.json"
    p.write_text(json.dumps(VALID))
    spec = load_grid_spec(p)
    assert spec.model == "tcn6" and spec.folds == 5
    assert spec.grid.lr == [3e-4, 1e-3, 3e-3]


def test_grid_spec_rejects_unknown_field():
    with pytest.raises(ValidationError):
        GridSpec(**{**VALID, "learning_rate_extra": 1})


def test_grid_spec_rejects_unknown_model():
    with pytest.raises(ValidationError):
        GridSpec(**{**VALID, "model": "resnet50"})


def test_grid_spec_rejects_empty_grid_axis():
    bad = {**VALID, "grid": {**VALID["grid"], "lr": []}}
    with pytest.raises(ValidationError):
        GridSpec(**bad)


def test_grid_spec_rejects_out_of_range():
    bad = {**VALID, "grid": {**VALID["grid"], "dropout": [1.5]}}
    with pytest.raises(ValidationError):
        GridSpec(**bad)
    with pytest.raises(ValidationError):
        GridSpec(**{**VALID, "pool": "mixed"})


def test_all_canonical_configs_load_and_share_grid():
    """Fairness-Invariante: identische Default-Grids in allen 13 Dateien."""
    cfg_dir = Path(__file__).parents[1] / "configs" / "hp"
    paths = sorted(cfg_dir.glob("*.json"))
    assert len(paths) == 13
    specs = [load_grid_spec(p) for p in paths]
    assert {s.model for s in specs} == {p.stem for p in paths}
    ref = specs[0]
    for s in specs[1:]:
        assert s.grid == ref.grid
        assert (s.seeds, s.max_epochs, s.patience, s.folds, s.pool, s.win) == \
               (ref.seeds, ref.max_epochs, ref.patience, ref.folds, ref.pool, ref.win)


import pandas as pd

from src.training.deep import grid as grid_mod
from src.training.deep.grid import run_grid, trial_name

SMALL = {
    "model": "tcn", "pool": "legacy", "win": 5, "folds": 3,
    "seeds": [42, 43], "max_epochs": 2, "patience": 1,
    "grid": {"lr": [1e-3], "dropout": [0.1, 0.2],
             "batch_size": [64], "weight_decay": [0.0]},
}


def _fake_loso(model_name, window_sec, **kw):
    if kw.get("on_event"):
        kw["on_event"]({"type": "fold_start", "idx": 0, "person": "P01+P02"})
        kw["on_event"]({"type": "epoch", "fold": 0, "epoch": 0, "loss": 0.5,
                        "val_auc": 0.8, "val_loss": 0.6, "val_acc": 0.7})
    return pd.DataFrame([
        {"held_out": "P01+P02", "accuracy": 0.9, "roc_auc": 0.95, "best_epoch": 1},
        {"held_out": "P03+P04", "accuracy": 0.8, "roc_auc": 0.90, "best_epoch": 2},
    ])


@pytest.fixture()
def small_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(grid_mod, "train_deep_loso", _fake_loso)
    monkeypatch.setattr(grid_mod, "ROOT", tmp_path)
    p = tmp_path / "configs" / "smoke.json"
    p.parent.mkdir()
    p.write_text(json.dumps(SMALL))
    return p


def test_run_grid_writes_trials_history_and_meta(small_cfg, tmp_path):
    outdir = run_grid(small_cfg)
    assert outdir == tmp_path / "models" / "hp_grid" / "legacy" / "smoke"
    trials = sorted(f.name for f in outdir.glob("trial_*.csv"))
    assert trials == [f"trial_{trial_name('tcn', i, s)}.csv"
                      for i in (0, 1) for s in (42, 43)]
    row = pd.read_csv(outdir / "trial_tcn-g00-s42.csv").iloc[0]
    assert row["cfg_id"] == "g00" and row["seed"] == 42
    assert row["accuracy"] == pytest.approx(0.85)
    assert row["dropout"] == 0.1
    meta = json.loads((outdir / "run_meta.json").read_text())
    assert meta["config"] == SMALL and meta["n_configs"] == 2
    assert (outdir / "history_tcn-g00-s42.csv").exists()


def test_run_grid_resume_skips_existing(small_cfg):
    ran = []
    outdir = run_grid(small_cfg, after_trial=lambda d: ran.append(1))
    assert len(ran) == 4
    ran.clear()
    run_grid(small_cfg, after_trial=lambda d: ran.append(1))
    assert ran == []                                  # alles uebersprungen


def test_run_grid_freeze_mismatch_aborts(small_cfg, tmp_path):
    run_grid(small_cfg)
    changed = {**SMALL, "grid": {**SMALL["grid"], "lr": [3e-3]}}
    small_cfg.write_text(json.dumps(changed))
    with pytest.raises(SystemExit, match="run_meta"):
        run_grid(small_cfg)


def test_run_grid_closes_sink_per_trial_and_crash_leaves_no_trial_csv(
        small_cfg, monkeypatch, tmp_path):
    closed = []
    real_sink = grid_mod.epoch_history_sink

    def spying_sink(*a, **kw):
        s = real_sink(*a, **kw)
        orig_close = s.close
        def _close():
            closed.append(1)
            orig_close()
        s.close = _close
        return s

    monkeypatch.setattr(grid_mod, "epoch_history_sink", spying_sink)
    run_grid(small_cfg)
    assert len(closed) == 4                    # 2 Configs x 2 Seeds, je genau 1 close

    closed.clear()
    outdir2 = tmp_path / "models" / "hp_grid" / "legacy" / "smoke2"
    cfg2 = small_cfg.parent / "smoke2.json"
    cfg2.write_text(small_cfg.read_text())

    def crashing_loso(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(grid_mod, "train_deep_loso", crashing_loso)
    with pytest.raises(RuntimeError):
        run_grid(cfg2)
    assert closed == [1]                       # Sink trotz Crash geschlossen
    assert not list(outdir2.glob("trial_*.csv"))  # kein Partial-Trial -> Resume faehrt neu
