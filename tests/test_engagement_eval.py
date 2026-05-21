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


def _timeline_two_blocks():
    """Zwei Blöcke: writing [1000,2000), idle [2000,3000)."""
    return pd.DataFrame({
        "task_index": [1, 2],
        "task_id": ["abschreiben", "pause"],
        "task_name": ["Text", "Pause"],
        "task_category": ["writing", "idle"],
        "start_ms": [1000.0, 2000.0],
        "end_ms": [2000.0, 3000.0],
    })


def test_assign_tasks_maps_windows_into_blocks():
    # Fenster bei 1500 (Block 1), 2500 (Block 2), 3500 (Übergang/außerhalb)
    oof = _oof("S001", "P01", [1500.0, 2500.0, 3500.0], [1, 0, 1],
               [0.9, 0.1, 0.5])

    out = eng.assign_tasks(oof, _timeline_two_blocks())

    assert out["task_index"].tolist()[:2] == [1.0, 2.0]
    assert pd.isna(out["task_index"].iloc[2])  # Fenster außerhalb → NaN
    assert out["task_category"].tolist()[:2] == ["writing", "idle"]


def test_engagement_per_task_aggregates_per_block():
    # Block 1 (writing): 4 Fenster, alle label 1, proba 0.9 → 100/100
    # Block 2 (idle):    4 Fenster, alle label 0, proba 0.1 → 0/0
    oof = _oof("S001", "P01",
               [1200.0, 1400.0, 1600.0, 1800.0,
                2200.0, 2400.0, 2600.0, 2800.0],
               [1, 1, 1, 1, 0, 0, 0, 0],
               [0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1])

    out = eng.engagement_per_task(
        oof, timeline_loader=lambda s: _timeline_two_blocks())

    assert len(out) == 2
    assert list(out.columns) == [
        "session_id", "person_id", "task_index", "task_id", "task_name",
        "task_category", "n_windows", "true_pct", "pred_pct", "error_pp"]
    w = out[out["task_category"] == "writing"].iloc[0]
    assert w["true_pct"] == pytest.approx(100.0)
    assert w["pred_pct"] == pytest.approx(100.0)
    assert w["error_pp"] == pytest.approx(0.0)
    assert w["n_windows"] == 4
    idle = out[out["task_category"] == "idle"].iloc[0]
    assert idle["true_pct"] == pytest.approx(0.0)


def test_engagement_per_task_skips_session_without_markers():
    oof = _oof("S001", "P01", [1500.0, 2500.0], [1, 0], [0.9, 0.1])

    out = eng.engagement_per_task(
        oof, timeline_loader=lambda s: pd.DataFrame(columns=eng.TIMELINE_COLS))

    assert out.empty
    assert list(out.columns) == [
        "session_id", "person_id", "task_index", "task_id", "task_name",
        "task_category", "n_windows", "true_pct", "pred_pct", "error_pp"]


def test_plot_engagement_heatmap_writes_file(tmp_path):
    eng_df = pd.DataFrame({
        "session_id": ["S001", "S001", "S002", "S002"],
        "person_id": ["P01", "P01", "P02", "P02"],
        "task_index": [1, 2, 1, 2],
        "task_id": ["abschreiben", "pause", "abschreiben", "pause"],
        "task_name": ["Text", "Pause", "Text", "Pause"],
        "task_category": ["writing", "idle", "writing", "idle"],
        "n_windows": [100, 80, 100, 80],
        "true_pct": [72.0, 4.0, 65.0, 6.0],
        "pred_pct": [70.0, 5.0, 71.0, 8.0],
        "error_pp": [-2.0, 1.0, 6.0, 2.0],
    })
    out = tmp_path / "engagement_heatmap.png"

    eng.plot_engagement_heatmap(eng_df, out)

    assert out.exists()
    # Why: out.exists() allein wäre auch bei einer leeren/degenerierten
    # Figur grün — die Größenschwelle belegt, dass real gerendert wurde.
    assert out.stat().st_size > 5_000
