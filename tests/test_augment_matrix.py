"""Tests fuer den parallelen Augment-A/B-Matrix-Generator (scripts/ml/augment_matrix.py)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / "scripts" / "ml" / "augment_matrix.py"
_spec = importlib.util.spec_from_file_location("augment_matrix", _SCRIPT)
augment_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(augment_matrix)


def _build(monkeypatch, **env):
    for k in ("SEEDS", "MODEL", "POOL", "WIN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return augment_matrix.build()


def test_two_jobs_per_seed(monkeypatch):
    inc = _build(monkeypatch, SEEDS="42 43 44")["include"]
    assert len(inc) == 6  # 3 Seeds x {aug, no-aug}
    names = {e["name"] for e in inc}
    assert names == {"s42-noaug", "s42-aug", "s43-noaug", "s43-aug",
                     "s44-noaug", "s44-aug"}


def test_aug_flag_only_on_aug_jobs(monkeypatch):
    inc = _build(monkeypatch, SEEDS="42")["include"]
    by = {e["name"]: e["cmd"] for e in inc}
    assert "--augment" in by["s42-aug"]
    assert "--augment" not in by["s42-noaug"]
    # beide tragen denselben Seed
    assert "--seed 42" in by["s42-aug"] and "--seed 42" in by["s42-noaug"]


def test_cmd_carries_model_pool_win(monkeypatch):
    inc = _build(monkeypatch, SEEDS="7", MODEL="tcn", POOL="legacy", WIN="10")["include"]
    cmd = inc[0]["cmd"]
    assert "--model tcn" in cmd and "--pool legacy" in cmd and "--win 10" in cmd
    assert "python -u -m src.training.deep" in cmd  # unbuffered fuer Live-Log


def test_defaults_when_env_empty(monkeypatch):
    inc = _build(monkeypatch)["include"]
    assert len(inc) == 6  # Default 3 Seeds
    assert "--model tcn6" in inc[0]["cmd"]
    assert "--pool modern" in inc[0]["cmd"]


def test_seeds_accept_commas(monkeypatch):
    inc = _build(monkeypatch, SEEDS="1,2")["include"]
    assert {e["name"] for e in inc} == {"s1-noaug", "s1-aug", "s2-noaug", "s2-aug"}
