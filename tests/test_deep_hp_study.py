# tests/test_deep_hp_study.py
import importlib.util
from pathlib import Path
import numpy as np, pandas as pd, pytest

_S = Path(__file__).parents[1] / "scripts" / "ml" / "deep_hp_study.py"
_spec = importlib.util.spec_from_file_location("deep_hp_study", _S)
study = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(study)

def _trial(model, lr, dropout, batch, wd, acc, auc=0.9, best_epoch=10):
    return {"model": model, "lr": lr, "dropout": dropout, "batch_size": batch,
            "weight_decay": wd, "accuracy": acc, "roc_auc": auc, "best_epoch": best_epoch}

def test_winners_picks_best_per_model():
    df = pd.DataFrame([
        _trial("cnn", 1e-3, 0.3, 64, 1e-5, 0.80),
        _trial("cnn", 3e-4, 0.2, 32, 1e-4, 0.87),   # cnn-Sieger
        _trial("tcn", 1e-3, 0.2, 64, 1e-5, 0.90),
    ])
    w = study.winners(df)
    assert set(w["model"]) == {"cnn", "tcn"}
    assert w[w.model == "cnn"]["accuracy"].iloc[0] == 0.87
    assert w[w.model == "cnn"]["lr"].iloc[0] == 3e-4

def test_boundary_warnings_flags_edge():
    w = pd.DataFrame([_trial("lstm", 1e-4, 0.5, 128, 1e-2, 0.8)])  # alle am Rand
    msgs = study.boundary_warnings(w)
    assert any("lstm" in m and "lr" in m for m in msgs)

def test_infeasible_count():
    df = pd.DataFrame([_trial("cnn", 1e-3, 0.3, 64, 1e-5, np.nan),
                       _trial("cnn", 1e-3, 0.3, 64, 1e-5, 0.8)])
    assert study.infeasible_count(df) == 1

def test_winner_fold_cv_seed_averages():
    import pandas as pd
    s1 = pd.DataFrame({"held_out": ["P1", "P2"], "accuracy": [0.8, 0.6], "roc_auc": [0.9, 0.7]})
    s2 = pd.DataFrame({"held_out": ["P1", "P2"], "accuracy": [0.9, 0.7], "roc_auc": [0.95, 0.75]})
    out = study.winner_fold_cv([s1, s2])
    assert set(out["held_out"]) == {"P1", "P2"}
    p1 = out[out.held_out == "P1"].iloc[0]
    assert p1.accuracy == pytest.approx(0.85) and p1.roc_auc == pytest.approx(0.925)   # (0.8+0.9)/2, (0.9+0.95)/2


def test_run_trial_writes_summary_row(tmp_path, monkeypatch):
    import pandas as pd
    # _train_trial mocken: liefert einen 2-Fold-Frame
    fake = pd.DataFrame({"held_out": ["P1", "P2"], "accuracy": [0.8, 0.9],
                         "roc_auc": [0.9, 0.95], "best_epoch": [10, 12]})
    monkeypatch.setattr(study, "_train_trial", lambda *a, **k: fake)
    cfg = {"lr": 1e-3, "dropout": 0.2, "batch_size": 64, "weight_decay": 1e-5}
    study.run_trial("cnn", cfg, 42, "legacy", 5, "cnn-t0", str(tmp_path))
    out = pd.read_csv(tmp_path / "trial_cnn-t0.csv")
    assert len(out) == 1
    assert out["model"].iloc[0] == "cnn"
    assert out["lr"].iloc[0] == 1e-3 and out["batch_size"].iloc[0] == 64
    assert abs(out["accuracy"].iloc[0] - 0.85) < 1e-9   # mean(0.8, 0.9)


def test_run_collect_reads_trials_and_reports(tmp_path, monkeypatch):
    import pandas as pd
    # zwei Such-Trials fuer cnn als CSVs ablegen
    hp = tmp_path / "hp"; hp.mkdir()
    pd.DataFrame([{"model": "cnn", "lr": 1e-3, "dropout": 0.2, "batch_size": 64,
                   "weight_decay": 1e-5, "seed": 42, "accuracy": 0.80,
                   "roc_auc": 0.90, "best_epoch": 10}]).to_csv(hp / "trial_cnn-t0.csv", index=False)
    pd.DataFrame([{"model": "cnn", "lr": 3e-4, "dropout": 0.3, "batch_size": 32,
                   "weight_decay": 1e-4, "seed": 42, "accuracy": 0.87,
                   "roc_auc": 0.93, "best_epoch": 12}]).to_csv(hp / "trial_cnn-t1.csv", index=False)
    # Varianz-Training + Ausgaben in tmp umlenken
    fake = pd.DataFrame({"held_out": ["P1", "P2"], "accuracy": [0.86, 0.88],
                         "roc_auc": [0.94, 0.95], "best_epoch": [11, 11]})
    monkeypatch.setattr(study, "_train_trial", lambda *a, **k: fake)
    monkeypatch.setattr(study, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(study, "REPORT", tmp_path / "deep_hp_study.md")
    study.run_collect(str(hp), "legacy", 5, [42, 43])
    won = pd.read_csv(tmp_path / "deep_hp_winners_legacy.csv")
    assert won["accuracy"].iloc[0] == 0.87            # der bessere Trial gewinnt
    assert (tmp_path / "deep_hp_winner_cnn_legacy_cv.csv").exists()
    assert (tmp_path / "deep_hp_study.md").exists()


def test_run_collect_empty_dir_raises(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        study.run_collect(str(tmp_path), "legacy", 5, [42])


def test_trial_mode_rejects_wrong_max_epochs(monkeypatch):
    import pytest, sys
    monkeypatch.setattr(sys, "argv", [
        "deep_hp_study.py", "--mode", "trial", "--model", "cnn", "--name", "x",
        "--lr", "1e-3", "--dropout", "0.2", "--batch-size", "64",
        "--weight-decay", "1e-5", "--max-epochs", "60"])
    with pytest.raises(SystemExit):
        study.main()
