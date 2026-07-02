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
    for k in ("MODELS", "POOL", "WIN", "N_TRIALS", "SEED", "TRIALS", "CUSTOM"):
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


def test_matrix_trials_filter(monkeypatch):
    """TRIALS-Indizes begrenzen die Sobol-Punkte -- fuer Nachzuegler-Runs
    (Run-Abbruch) ohne Voll-Redispatch."""
    inc = _build(monkeypatch, MODELS="cnn", N_TRIALS="4", TRIALS="1,3")
    assert {e["name"] for e in inc} == {"cnn-t1", "cnn-t3"}


def test_matrix_seed_suffix_keeps_artifact_names_unique(monkeypatch):
    """SEED != 42 haengt -s{seed} an den Namen (Artefakt-Kollision zwischen
    Varianz-Runs) und traegt --seed im Kommando; Default 42 bleibt bit-identisch."""
    inc = _build(monkeypatch, MODELS="cnn", N_TRIALS="2", SEED="43")
    assert {e["name"] for e in inc} == {"cnn-t0-s43", "cnn-t1-s43"}
    assert all("--seed 43" in e["cmd"] for e in inc)
    inc42 = _build(monkeypatch, MODELS="cnn", N_TRIALS="2")
    assert {e["name"] for e in inc42} == {"cnn-t0", "cnn-t1"}


def test_matrix_custom_entries(monkeypatch):
    """CUSTOM-JSON haengt gezielte Configs an (z. B. Boundary-Probe
    tcn6@256) -- gleiche Trial-Runner-Form inkl. Fairness-Cap."""
    custom = ('[{"model": "tcn6", "name": "tcn6-b256-s43", "lr": 0.002107, '
              '"dropout": 0.049, "batch_size": 256, "weight_decay": 0.00013926, '
              '"seed": 43}]')
    inc = _build(monkeypatch, MODELS="none", CUSTOM=custom)
    assert len(inc) == 1
    e = inc[0]
    assert e["name"] == "tcn6-b256-s43"
    assert "--model tcn6" in e["cmd"]
    assert "--batch-size 256" in e["cmd"]
    assert "--seed 43" in e["cmd"]
    assert "--max-epochs 120" in e["cmd"]


def test_matrix_models_none_without_custom_fails(monkeypatch):
    """Leere Matrix wuerde den Workflow kryptisch scheitern lassen --
    lieber klare Fehlermeldung im prepare-Job."""
    import pytest
    with pytest.raises(SystemExit):
        _build(monkeypatch, MODELS="none")


def test_matrix_emits_trial_runner(monkeypatch):
    inc = _build(monkeypatch, MODELS="cnn", N_TRIALS="2", POOL="legacy", WIN="5")
    assert all("--mode trial" in e["cmd"] for e in inc)
    assert all("deep_hp_study.py" in e["cmd"] for e in inc)
    # --name traegt model+trial, --hp-dir zeigt in den pool-Ordner
    assert any("--name cnn-t0" in e["cmd"] for e in inc)
    assert all("--hp-dir models/hp/legacy" in e["cmd"] for e in inc)
    assert all(f in e["cmd"] for e in inc
               for f in ("--lr", "--dropout", "--batch-size", "--weight-decay",
                         "--max-epochs 120"))
