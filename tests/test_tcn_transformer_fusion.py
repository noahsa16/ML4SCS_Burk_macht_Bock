"""Tests fuer die reine Kernlogik von tcn_transformer_fusion (align/per-fold/ensemble).

``scripts`` ist kein Paket -> Modul per importlib ueber den Pfad laden.
Kein Training/OOF-Erzeugung hier (das ist Plumbing) — nur die testbaren Funktionen.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_S = Path(__file__).parents[1] / "scripts" / "ml" / "tcn_transformer_fusion.py"
_spec = importlib.util.spec_from_file_location("tcn_transformer_fusion", _S)
fus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fus)


def test_normalise_oof_picks_columns():
    df = pd.DataFrame({"session_id": ["S1"], "t_center_ms": [0.0],
                       "held_out": ["P1"], "label": [1], "proba_cal": [0.7]})
    out = fus._normalise_oof(df)
    assert list(out.columns) == ["session_id", "t_center_ms", "person_id", "y", "proba"]
    assert out["person_id"].iloc[0] == "P1" and out["proba"].iloc[0] == 0.7


def test_align_oofs_nearest_by_session():
    # TCN6-Gitter bei 0/5000/10000 ms, Transformer-P5 leicht versetzt bei 100/5100/10100
    tcn6 = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [0.0, 5000.0, 10000.0],
                        "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.2, 0.8, 0.6]})
    tp5 = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [100.0, 5100.0, 10100.0],
                       "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.3, 0.9, 0.55]})
    a = fus.align_oofs(tcn6, tp5)
    assert len(a) == 3
    assert set(a.columns) >= {"session_id", "t_center_ms", "person_id", "y",
                              "tcn6_proba", "tp5_proba"}
    # jedes TCN6-Fenster paart mit dem naechsten Transformer-P5-Fenster
    assert a.sort_values("t_center_ms")["tp5_proba"].tolist() == [0.3, 0.9, 0.55]
    assert a.sort_values("t_center_ms")["tcn6_proba"].tolist() == [0.2, 0.8, 0.6]


def test_per_fold_metrics_shape_and_values():
    df = pd.DataFrame({
        "person_id": ["P1", "P1", "P2", "P2"],
        "y": [1, 0, 1, 0], "p": [0.9, 0.2, 0.8, 0.6],
    })
    cv = fus.per_fold_metrics(df.rename(columns={"p": "proba"}), "proba")
    assert list(cv.columns) == ["held_out", "accuracy", "roc_auc"]
    assert set(cv["held_out"]) == {"P1", "P2"}
    # P1: preds [1,0] == y [1,0] -> acc 1.0 ; P2: preds [1,1] vs [1,0] -> acc 0.5
    assert cv[cv.held_out == "P1"]["accuracy"].iloc[0] == 1.0
    assert cv[cv.held_out == "P2"]["accuracy"].iloc[0] == 0.5


def test_per_fold_metrics_single_class_auc_nan():
    df = pd.DataFrame({"person_id": ["P1", "P1"], "y": [1, 1], "proba": [0.9, 0.8]})
    cv = fus.per_fold_metrics(df, "proba")
    assert np.isnan(cv["roc_auc"].iloc[0])           # einklassig -> AUC nan
    assert cv["accuracy"].iloc[0] == 1.0


def test_ensemble_proba_mean():
    tcn6 = np.array([0.2, 0.8])
    tp5 = np.array([0.4, 0.6])
    np.testing.assert_allclose(fus.ensemble_proba(tcn6, tp5), [0.3, 0.7])
    np.testing.assert_allclose(fus.ensemble_proba(tcn6, tp5, w=1.0), tcn6)
