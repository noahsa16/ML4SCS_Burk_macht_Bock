"""Tests fuer den Deep-HP-Studien-Matrix-Builder (scripts/ml/deep_hp_matrix.py).

``scripts`` ist kein Paket -> Modul per importlib ueber den Pfad laden
(analog test_sweep_matrix.py / test_deep_hp_study.py).
"""
import importlib.util
from pathlib import Path

_S = Path(__file__).parents[1] / "scripts" / "ml" / "deep_hp_matrix.py"
_spec = importlib.util.spec_from_file_location("deep_hp_matrix", _S)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _build(monkeypatch, **env):
    for k in ("MODELS", "POOL", "WIN", "N_TRIALS", "SEED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return m.build()["include"]


def test_matrix_expands_models_x_trials(monkeypatch):
    inc = _build(monkeypatch, MODELS="cnn,tcn", N_TRIALS="4", POOL="legacy", WIN="5")
    assert len(inc) == 8  # 2 Modelle x 4 Trials
    assert all("--lr" in e["cmd"] and "--pool legacy" in e["cmd"] for e in inc)
    assert all("--win 5" in e["cmd"] for e in inc)


def test_matrix_names_unique(monkeypatch):
    inc = _build(monkeypatch, MODELS="cnn", N_TRIALS="4")
    assert len({e["name"] for e in inc}) == 4
