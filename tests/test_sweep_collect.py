"""Tests fuer sweep_collect: waehlt die accuracy-tragende CSV, nicht csvs[0]."""
import importlib.util
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).parents[1] / "scripts" / "ml" / "sweep_collect.py"
_spec = importlib.util.spec_from_file_location("sweep_collect", _SCRIPT)
sweep_collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep_collect)


def test_picks_accuracy_csv_not_alphabetical_first(tmp_path):
    # rf-hmm-Artefakt: hmm_detail (kein 'accuracy', sortiert alphabetisch VOR
    # dem cv) + cv (mit 'accuracy'). csvs[0] waere das detail -> frueher stiller
    # Skip; jetzt muss das cv gewaehlt werden.
    d = tmp_path / "cv-rf-hmm-legacy"
    d.mkdir()
    pd.DataFrame({"held_out": ["P1"], "hmm_filter_acc": [0.9]}).to_csv(
        d / "hmm_postprocess_detail.csv", index=False)
    pd.DataFrame({"held_out": ["P1", "P2"], "accuracy": [0.9, 0.8],
                  "roc_auc": [0.95, 0.85]}).to_csv(
        d / "hmm_postprocess_legacy_cv.csv", index=False)
    out = sweep_collect.collect(str(tmp_path))
    row = out[out.config == "rf-hmm-legacy"].iloc[0]
    assert row.n_folds == 2          # das cv (2 Folds), nicht das detail (1)
    assert row.acc == 0.85           # mean(0.9, 0.8)


def test_no_accuracy_csv_yields_zero_folds(tmp_path):
    d = tmp_path / "cv-broken"
    d.mkdir()
    pd.DataFrame({"held_out": ["P1"], "foo": [1]}).to_csv(d / "x.csv", index=False)
    out = sweep_collect.collect(str(tmp_path))
    assert out[out.config == "broken"].iloc[0].n_folds == 0
