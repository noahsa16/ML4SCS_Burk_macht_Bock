"""Smoke tests für die Schreib-Prozent-Regression (Stufe 2).

Trainings-frei: OOF-CSV und merged.csv werden als synthetische Fixtures
gemockt — Stufe 2 trainiert per Design kein Modell.
"""

import numpy as np
import pandas as pd
import pytest

from src.evaluation import regression as reg


def _write_merged(path, n, writing_mask):
    """Synthetisches merged.csv: n Samples @ 50 Hz, label_writing aus mask."""
    pd.DataFrame(
        {
            "local_ts_ms": np.arange(n, dtype=float) * 20.0,
            "label_writing": np.asarray(writing_mask, dtype=int),
        }
    ).to_csv(path, index=False)


def test_pen_truth_per_session_reads_writing_fraction(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "DATA_PROC", tmp_path)
    # 100 Samples, erste 60 schreibend
    _write_merged(tmp_path / "S001_merged.csv", 100, [1] * 60 + [0] * 40)

    out = reg.pen_truth_per_session("S001")

    assert list(out.columns) == ["local_ts_ms", "label_writing"]
    assert len(out) == 100
    assert out["label_writing"].mean() == pytest.approx(0.60)


def _oof_one_session(n_windows, proba_cal, label, session="S001", person="P01"):
    """Synthetische OOF-Zeilen: 1 Fenster / 0.5 s, t_center_ms ab 500 ms."""
    return pd.DataFrame(
        {
            "session_id": session,
            "person_id": person,
            "t_center_ms": 500.0 + np.arange(n_windows) * 500.0,
            "label": np.asarray(label, dtype=int),
            "proba_raw": np.asarray(proba_cal, dtype=float),
            "proba_cal": np.asarray(proba_cal, dtype=float),
        }
    )


def test_aggregate_whole_session_one_block_per_session():
    # 120 Fenster (= 60 s @ 0.5 s Stride), halb schreibend
    oof = _oof_one_session(120, [0.8] * 120, [1] * 60 + [0] * 60)
    out = reg.aggregate(oof, scale_sec=None, merged_loader=lambda s: pd.DataFrame())

    assert len(out) == 1
    assert out["session_id"].iat[0] == "S001"
    assert out["pred_pct"].iat[0] == pytest.approx(80.0)
    assert out["truth_closed_pct"].iat[0] == pytest.approx(50.0)
    assert out["n_windows"].iat[0] == 120


def test_aggregate_fixed_scale_splits_into_blocks():
    # 240 Fenster = 120 s; bei 60-s-Blöcken → 2 Blöcke à 120 Fenster
    oof = _oof_one_session(240, [0.5] * 240, [1] * 240)
    out = reg.aggregate(oof, scale_sec=60.0, merged_loader=lambda s: pd.DataFrame())

    assert len(out) == 2
    assert list(out["n_windows"]) == [120, 120]


def test_aggregate_pen_pct_from_merged_loader():
    oof = _oof_one_session(120, [0.9] * 120, [1] * 120)
    # merged: 3000 Samples @ 50 Hz = 60 s, 30 s schreibend
    merged = pd.DataFrame(
        {
            "local_ts_ms": np.arange(3000, dtype=float) * 20.0,
            "label_writing": [1] * 1500 + [0] * 1500,
        }
    )
    out = reg.aggregate(oof, scale_sec=None, merged_loader=lambda s: merged)

    assert out["truth_pen_pct"].iat[0] == pytest.approx(50.0)


def test_regression_metrics_known_error():
    # pred immer 10 pp über der Wahrheit → MAE=RMSE=Bias=10
    agg = pd.DataFrame(
        {
            "pred_pct": [60.0, 30.0, 90.0],
            "truth_closed_pct": [50.0, 20.0, 80.0],
            "truth_pen_pct": [40.0, 10.0, 70.0],
        }
    )
    m = reg.regression_metrics(agg)

    assert m["closed"]["mae"] == pytest.approx(10.0)
    assert m["closed"]["rmse"] == pytest.approx(10.0)
    assert m["closed"]["bias"] == pytest.approx(10.0)
    # pred liegt 20 pp über der rohen Pen-Wahrheit → positiver Bias
    assert m["pen"]["bias"] == pytest.approx(20.0)
    assert m["closed"]["n"] == 3


def test_regression_metrics_ignores_nan_truth():
    agg = pd.DataFrame(
        {
            "pred_pct": [60.0, 30.0],
            "truth_closed_pct": [50.0, 20.0],
            "truth_pen_pct": [40.0, float("nan")],
        }
    )
    m = reg.regression_metrics(agg)

    assert m["pen"]["n"] == 1
    assert m["pen"]["bias"] == pytest.approx(20.0)


def test_evaluate_writes_metrics_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "DATA_PROC", tmp_path)
    monkeypatch.setattr(reg, "FIG_DIR", tmp_path / "figures")
    _write_merged(tmp_path / "S001_merged.csv", 6000, [1] * 3000 + [0] * 3000)

    oof = _oof_one_session(240, [0.6] * 240, [1] * 120 + [0] * 120)
    oof_path = tmp_path / "loso_oof.csv"
    oof.to_csv(oof_path, index=False)
    out_csv = tmp_path / "regression_metrics.csv"

    result = reg.evaluate(oof_path=oof_path, scales=(60.0, None),
                          out_csv=out_csv)

    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    # 2 Skalen × 2 Wahrheiten = 4 Zeilen
    assert len(df) == 4
    assert set(df["scale"]) == {"60s", "session"}
    assert set(df["truth"]) == {"closed", "pen"}
    assert (tmp_path / "figures" / "regression_calibration.png").exists()
    assert (tmp_path / "figures" / "regression_scatter.png").exists()
    assert "metrics" in result and "aggregates" in result
