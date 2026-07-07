"""Tests fuer den testbaren Kern von hmm_hyperparameter_sweep (fit/decode/loso).

``scripts`` ist kein Paket -> Modul per importlib laden. Kein IO/Report/Grid —
nur die reine, leakage-freie Dekodier-Logik.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_S = Path(__file__).parents[1] / "scripts" / "ml" / "hmm_hyperparameter_sweep.py"
_spec = importlib.util.spec_from_file_location("hmm_hyperparameter_sweep", _S)
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)


def _two_person_df():
    # Person A: eher writing, Person B: eher idle; je eine Session, klare Probas.
    rows = []
    for i, (y, p) in enumerate([(1, 0.8), (1, 0.7), (0, 0.4), (1, 0.9)]):
        rows.append({"person_id": "A", "session_id": "sA", "y": y, "proba": p})
    for i, (y, p) in enumerate([(0, 0.2), (0, 0.3), (1, 0.6), (0, 0.1)]):
        rows.append({"person_id": "B", "session_id": "sB", "y": y, "proba": p})
    return pd.DataFrame(rows)


def test_fit_fold_priors_are_train_base_rate():
    df = pd.DataFrame({"session_id": ["s"] * 4, "y": [1, 1, 1, 0]})
    A, priors = sw.fit_fold(df, smoothing=0.0)
    assert priors[1] > priors[0]              # writing-Basisrate hoeher
    assert abs(float(np.sum(priors)) - 1.0) < 1e-9
    assert np.allclose(A.sum(axis=1), 1.0)    # Transitionszeilen normiert


def test_decode_person_modes_return_int_labels():
    A = np.array([[0.9, 0.1], [0.1, 0.9]])
    priors = np.array([0.5, 0.5])
    test_df = pd.DataFrame({"session_id": ["s"] * 5,
                            "proba": [0.1, 0.2, 0.8, 0.9, 0.7]})
    for mode in ["filter", "smoother", "viterbi"]:
        preds = sw.decode_person(test_df, A, priors, 1e-3, 1.0, mode)
        assert preds.shape == (5,)
        assert set(np.unique(preds)) <= {0, 1}


def test_decode_loso_rows_and_metrics():
    res = sw.decode_loso(_two_person_df(), 1.0, 1e-3, 1.0, "filter")
    assert list(res.columns) == ["held_out", "accuracy", "f1"]
    assert set(res["held_out"]) == {"A", "B"}
    assert ((res["accuracy"] >= 0) & (res["accuracy"] <= 1)).all()


def test_decode_loso_holdout_excludes_own_data():
    # Leakage-frei: der Fold fuer A wird mit Fit aus NUR B dekodiert.
    df = _two_person_df()
    res = sw.decode_loso(df, 1.0, 1e-3, 1.0, "filter")
    A_from_B, pri_B = sw.fit_fold(df[df.person_id == "B"], 1.0)
    a_test = df[df.person_id == "A"]
    preds = sw.decode_person(a_test, A_from_B, pri_B, 1e-3, 1.0, "filter")
    manual_acc = float((preds == a_test["y"].to_numpy()).mean())
    got = float(res[res.held_out == "A"]["accuracy"].iloc[0])
    assert abs(got - manual_acc) < 1e-9
