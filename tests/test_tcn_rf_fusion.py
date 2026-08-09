"""Tests fuer die reine Kernlogik von tcn_rf_fusion (align/per-fold/ensemble).

``scripts`` ist kein Paket -> Modul per importlib ueber den Pfad laden.
Kein Training/OOF-Erzeugung hier (das ist Plumbing) — nur die testbaren Funktionen.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_S = Path(__file__).parents[1] / "scripts" / "ml" / "tcn_rf_fusion.py"
_spec = importlib.util.spec_from_file_location("tcn_rf_fusion", _S)
fus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fus)


def _oof(proba_name, label_name, person_name, session, ts, y, p):
    return pd.DataFrame({
        "session_id": session, "t_center_ms": ts,
        person_name: ["P1"] * len(ts), label_name: y, proba_name: p,
    }).rename(columns={person_name: person_name})


def test_normalise_oof_picks_columns():
    df = pd.DataFrame({"session_id": ["S1"], "t_center_ms": [0.0],
                       "held_out": ["P1"], "label": [1], "proba_cal": [0.7]})
    out = fus._normalise_oof(df)
    assert list(out.columns) == ["session_id", "t_center_ms", "person_id", "y", "proba"]
    assert out["person_id"].iloc[0] == "P1" and out["proba"].iloc[0] == 0.7


def test_align_oofs_nearest_by_session():
    # RF-Gitter bei 0/5000/10000 ms, Deep leicht versetzt bei 100/5100/10100
    rf = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [0.0, 5000.0, 10000.0],
                       "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.2, 0.8, 0.6]})
    deep = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [100.0, 5100.0, 10100.0],
                         "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.3, 0.9, 0.55]})
    a = fus.align_oofs(rf, deep)
    assert len(a) == 3
    # generische Deep-Spalte (nicht mehr tcn6-spezifisch) -> beliebiges Deep-Modell
    assert set(a.columns) >= {"session_id", "t_center_ms", "person_id", "y",
                              "rf_proba", "deep_proba"}
    assert "tcn6_proba" not in a.columns
    # jedes RF-Fenster paart mit dem naechsten Deep-Fenster
    assert a.sort_values("t_center_ms")["deep_proba"].tolist() == [0.3, 0.9, 0.55]
    assert a.sort_values("t_center_ms")["rf_proba"].tolist() == [0.2, 0.8, 0.6]


def test_deep_cache_path_is_model_parametric():
    # Blocker B: der OOF-Cache-Pfad folgt dem Modellnamen, nicht hartem tcn6
    assert fus._deep_cache_path("tcn6").name == "tcn6_oof_legacy.csv"
    assert fus._deep_cache_path("inception").name == "inception_oof_legacy.csv"
    assert fus._deep_cache_path("tcn_bigru").name == "tcn_bigru_oof_legacy.csv"


def test_output_paths_are_model_parametric():
    # Blocker B: cv-CSV + Report-Namen folgen dem Modell -> kein Clobbern zwischen Laeufen
    cv_inc, rep_inc = fus._output_paths("inception")
    cv_tcn, rep_tcn = fus._output_paths("tcn6")
    assert cv_inc.name == "inception_rf_fusion_cv.csv"
    assert rep_inc.name == "inception_rf_fusion.md"
    assert cv_tcn != cv_inc and rep_tcn != rep_inc


def test_build_parser_accepts_model_flag():
    # Blocker B: --model waehlbar, Default bleibt tcn6 (Rueckwaerts-Kompatibilitaet)
    ns = fus._build_parser().parse_args(["--model", "inception"])
    assert ns.model == "inception"
    assert fus._build_parser().parse_args([]).model == "tcn6"


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
    rf = np.array([0.2, 0.8])
    tcn6 = np.array([0.4, 0.6])
    np.testing.assert_allclose(fus.ensemble_proba(rf, tcn6), [0.3, 0.7])
    np.testing.assert_allclose(fus.ensemble_proba(rf, tcn6, w=1.0), rf)
