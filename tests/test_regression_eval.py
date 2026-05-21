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
    assert out["pred_pct"].iat[0] == pytest.approx(100.0)
    assert out["pred_pct_proba"].iat[0] == pytest.approx(80.0)
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
    # 2 Skalen × 2 Rollen (headline/diagnostic) = 4 Zeilen
    assert len(df) == 4
    assert set(df["scale"]) == {"60s", "session"}
    assert set(df["truth"]) == {"closed", "pen"}
    # role-Spalte kennzeichnet Headline- vs. Diagnose-Aussage explizit
    assert "role" in df.columns
    assert set(df["role"]) == {"headline", "diagnostic"}
    # closed ↔ headline, pen ↔ diagnostic — Paarung muss konsistent sein
    assert set(df.loc[df["role"] == "headline", "truth"]) == {"closed"}
    assert set(df.loc[df["role"] == "diagnostic", "truth"]) == {"pen"}
    assert (tmp_path / "figures" / "regression_calibration.png").exists()
    assert (tmp_path / "figures" / "regression_scatter.png").exists()
    assert "metrics" in result and "aggregates" in result


def test_aggregate_two_sessions_independent_anchors():
    s1 = _oof_one_session(120, [0.8] * 120, [1] * 120,
                          session="S001", person="P01")
    s2 = _oof_one_session(120, [0.2] * 120, [0] * 120,
                          session="S002", person="P02")
    # S002 läuft zeitlich versetzt — anderer Anker als S001
    s2 = s2.assign(t_center_ms=s2["t_center_ms"] + 1_000_000.0)
    oof = pd.concat([s1, s2], ignore_index=True)

    out = reg.aggregate(oof, scale_sec=None,
                        merged_loader=lambda s: pd.DataFrame())

    assert len(out) == 2
    by_session = out.set_index("session_id")
    assert by_session.loc["S001", "pred_pct"] == pytest.approx(100.0)
    assert by_session.loc["S002", "pred_pct"] == pytest.approx(0.0)
    assert by_session.loc["S001", "person_id"] == "P01"
    assert by_session.loc["S002", "person_id"] == "P02"


def test_aggregate_binary_estimator_differs_from_proba_mean():
    # 60 Fenster bei proba 0.9, 40 bei proba 0.1
    oof = _oof_one_session(100, [0.9] * 60 + [0.1] * 40, [1] * 100)
    out = reg.aggregate(oof, scale_sec=None,
                        merged_loader=lambda s: pd.DataFrame())
    # binär: 60 von 100 Fenstern über 0.5 → 60.0 %
    assert out["pred_pct"].iat[0] == pytest.approx(60.0)
    # proba-Mittel: (60*0.9 + 40*0.1) / 100 = 0.58 → 58.0 %
    assert out["pred_pct_proba"].iat[0] == pytest.approx(58.0)


def test_aggregate_block_zero_includes_pre_window_pen_samples():
    """Block 0 muss merged-Samples VOR dem ersten t_center_ms mitzählen,
    sonst frisst der Window-Center-Inset den Anfang.

    Regression-Guard für den ``lo = -np.inf``-Sonderfall in ``_pen_pct``:
    das erste Fenster-Zentrum liegt ~0.5 s nach dem ersten merged-Sample.
    Ohne den -inf-Trick würde Block 0 erst ab ``block_start`` (== erstes
    t_center_ms) zählen und die frühen Pen-Samples still verlieren.
    """
    # OOF: 60 Fenster, erstes Zentrum bei t=500ms, Stride 500ms.
    oof = _oof_one_session(60, [0.5] * 60, [1] * 60)

    # merged: 1500 Samples @ 50 Hz = 30 s, Start bei t=0ms — also 500 ms
    # VOR dem ersten Fenster-Zentrum. Asymmetrie: die ersten 25 Samples
    # (t=0..480ms, = 500ms @ 50Hz) sind idle, alles danach writing.
    merged = pd.DataFrame({
        "local_ts_ms": np.arange(1500, dtype=float) * 20.0,
        "label_writing": [0] * 25 + [1] * 1475,
    })

    out = reg.aggregate(oof, scale_sec=10.0, merged_loader=lambda s: merged)

    # Block 0 = [-inf, 10500ms) wegen lo=-inf → umfasst t=0..10480ms,
    # das sind 525 Samples: 25 idle + 500 writing = 500/525 ≈ 95.2 %.
    # Erwartung 95.0 ± 0.5 deckt diesen Wert ab. WICHTIG: NICHT 100 % —
    # wäre der -inf-Trick weg, zählte Block 0 erst ab block_start=500ms,
    # die 25 idle-Samples fielen raus → 500/500 = 100 % und der Test bräche.
    assert out["truth_pen_pct"].iat[0] == pytest.approx(95.0, abs=0.5)
