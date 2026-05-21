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
