"""Tests fuer src/evaluation/fusion_utils.py — die geteilte, reine Fusions-Kernlogik.

Kein Training/OOF-Erzeugung — nur die reinen Funktionen (Normalisierung,
N-Wege-Alignment, per-Fold-Metriken, Proba-Mittel).
"""
import numpy as np
import pandas as pd

from src.evaluation import fusion_utils as fu


def test_normalise_oof_picks_columns():
    df = pd.DataFrame({"session_id": ["S1"], "t_center_ms": [0.0],
                       "held_out": ["P1"], "label": [1], "proba_cal": [0.7]})
    out = fu.normalise_oof(df)
    assert list(out.columns) == ["session_id", "t_center_ms", "person_id", "y", "proba"]
    assert out["person_id"].iloc[0] == "P1" and out["proba"].iloc[0] == 0.7


def test_mean_proba_equal_weight():
    a = np.array([0.2, 0.8])
    b = np.array([0.4, 0.6])
    np.testing.assert_allclose(fu.mean_proba([a, b]), [0.3, 0.7])
    # drei Arme mitteln
    c = np.array([0.6, 0.4])
    np.testing.assert_allclose(fu.mean_proba([a, b, c]), [0.4, 0.6])


def test_per_fold_metrics_shape_and_values():
    df = pd.DataFrame({
        "person_id": ["P1", "P1", "P2", "P2"],
        "y": [1, 0, 1, 0], "proba": [0.9, 0.2, 0.8, 0.6],
    })
    cv = fu.per_fold_metrics(df, "proba")
    assert list(cv.columns) == ["held_out", "accuracy", "roc_auc"]
    assert cv[cv.held_out == "P1"]["accuracy"].iloc[0] == 1.0   # [1,0]==[1,0]
    assert cv[cv.held_out == "P2"]["accuracy"].iloc[0] == 0.5   # [1,1] vs [1,0]


def test_per_fold_metrics_single_class_auc_nan():
    df = pd.DataFrame({"person_id": ["P1", "P1"], "y": [1, 1], "proba": [0.9, 0.8]})
    cv = fu.per_fold_metrics(df, "proba")
    assert np.isnan(cv["roc_auc"].iloc[0])
    assert cv["accuracy"].iloc[0] == 1.0


def test_paired_metric_on_common_folds():
    a = pd.DataFrame({"held_out": ["P1", "P2", "P3"], "accuracy": [0.9, 0.8, 0.85]})
    b = pd.DataFrame({"held_out": ["P1", "P2", "P3"], "accuracy": [0.8, 0.75, 0.80]})
    res = fu.paired_metric(a, b, "accuracy")
    assert {"median_diff", "p_value", "significant"} <= set(res)
    assert res["median_diff"] > 0          # a durchgehend > b


def test_residual_corr_identical_is_one():
    y = np.array([0, 1, 0, 1, 0, 1])
    p = np.array([0.1, 0.9, 0.2, 0.8, 0.1, 0.9])
    aligned = pd.DataFrame({"y": y, "a_proba": p, "b_proba": p})
    # identische Probas -> identische Residuen -> r=1
    assert abs(fu.residual_corr(aligned, ["a", "b"]) - 1.0) < 1e-9


def test_residual_corr_matches_pearson_and_below_one():
    # Bei Probas in [0,1] ist das Residuen-Vorzeichen klassen-gelockt (y=0 -> >=0,
    # y=1 -> <=0), also sind zwei Modelle stets positiv korreliert. Distinkte
    # Probas -> 0<r<1 (nicht degeneriert). Prueft Uebereinstimmung mit pearsonr.
    from scipy.stats import pearsonr
    y = np.array([0, 1, 0, 1, 0, 1])
    ap = np.array([0.1, 0.9, 0.2, 0.8, 0.1, 0.9])
    bp = np.array([0.3, 0.9, 0.1, 0.6, 0.2, 0.95])
    aligned = pd.DataFrame({"y": y, "a_proba": ap, "b_proba": bp})
    expected = pearsonr(ap - y, bp - y)[0]
    r = fu.residual_corr(aligned, ["a", "b"])
    assert abs(r - expected) < 1e-12
    assert r < 1.0


def test_align_frames_nearest_n_way():
    # drei Arme, jeweils leicht versetzte Gitter -> nearest-Match je Session
    base = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [0.0, 5000.0, 10000.0],
                         "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.2, 0.8, 0.6]})
    m2 = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [100.0, 5100.0, 10100.0],
                       "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.3, 0.9, 0.55]})
    m3 = pd.DataFrame({"session_id": ["S1"] * 3, "t_center_ms": [50.0, 5050.0, 10050.0],
                       "person_id": ["P1"] * 3, "label": [0, 1, 1], "proba": [0.1, 0.7, 0.65]})
    aligned = fu.align_frames({"rf": base, "tcn6": m2, "inception": m3})
    assert len(aligned) == 3
    assert set(aligned.columns) >= {"session_id", "t_center_ms", "person_id", "y",
                                    "rf_proba", "tcn6_proba", "inception_proba"}
    s = aligned.sort_values("t_center_ms")
    assert s["rf_proba"].tolist() == [0.2, 0.8, 0.6]
    assert s["tcn6_proba"].tolist() == [0.3, 0.9, 0.55]
    assert s["inception_proba"].tolist() == [0.1, 0.7, 0.65]
    # y + person_id kommen vom ersten (Basis-)Frame
    assert s["y"].tolist() == [0, 1, 1]
