# tests/test_deep_hp_study.py
import importlib.util
from pathlib import Path
import numpy as np, pandas as pd

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
