"""Smoke tests für die Engagement-Auswertung (Schreibzeit-Anteil/Task).

Trainings-frei: OOF-CSV und markers.csv werden als synthetische
Fixtures gemockt.
"""

import numpy as np
import pandas as pd
import pytest

from src.evaluation import engagement as eng


def _write_markers(path, rows):
    """Synthetische markers.csv. rows: Liste von Tupeln
    (timestamp_ms, event, task_id, task_name, task_index, task_category).
    """
    pd.DataFrame(
        rows,
        columns=["timestamp_ms", "event", "task_id", "task_name",
                 "task_index", "task_category"],
    ).assign(protocol_id="v1").to_csv(path, index=False)


def _oof(session, person, t_center_ms, label, proba_cal):
    """Synthetische OOF-Zeilen für eine Session."""
    return pd.DataFrame({
        "session_id": session,
        "person_id": person,
        "t_center_ms": np.asarray(t_center_ms, dtype=float),
        "label": np.asarray(label, dtype=int),
        "proba_raw": np.asarray(proba_cal, dtype=float),
        "proba_cal": np.asarray(proba_cal, dtype=float),
    })


def test_task_timeline_pairs_start_and_end(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)
    _write_markers(tmp_path / "S001_markers.csv", [
        (1000, "study_start", "", "", "", ""),
        (1100, "task_start", "abschreiben", "Text", 1, "writing"),
        (5100, "task_end",   "abschreiben", "Text", 1, "writing"),
        (5200, "task_start", "pause", "Pause", 2, "idle"),
        (7200, "task_end",   "pause", "Pause", 2, "idle"),
        (7300, "study_end",  "", "", "", ""),
    ])

    tl = eng.task_timeline("S001")

    assert list(tl["task_index"]) == [1, 2]
    assert list(tl["task_id"]) == ["abschreiben", "pause"]
    assert list(tl["task_category"]) == ["writing", "idle"]
    assert tl.loc[0, "start_ms"] == 1100.0
    assert tl.loc[0, "end_ms"] == 5100.0


def test_task_timeline_drops_unpaired_start(tmp_path, monkeypatch):
    # abgebrochene Session: task_start ohne task_end
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)
    _write_markers(tmp_path / "S002_markers.csv", [
        (1000, "study_start", "", "", "", ""),
        (1100, "task_start", "math", "Mathe", 1, "writing"),
        (3000, "abort", "", "", "", ""),
    ])

    tl = eng.task_timeline("S002")

    assert tl.empty
    assert list(tl.columns) == eng.TIMELINE_COLS


def test_task_timeline_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)

    tl = eng.task_timeline("S999")

    assert tl.empty
    assert list(tl.columns) == eng.TIMELINE_COLS
