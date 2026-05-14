"""Tests for the marker CSV writer."""
from __future__ import annotations

import csv

from src.server import csv_io


def test_write_marker_creates_file_with_header(tmp_path, monkeypatch):
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", tmp_path)
    csv_io.write_marker(
        "S999",
        {
            "timestamp_ms": 1715600070123,
            "event": "task_start",
            "task_id": "math",
            "task_name": "Mathe-Aufgaben",
            "task_index": 1,
            "task_category": "writing",
            "protocol_id": "v1",
        },
    )
    path = tmp_path / "S999_markers.csv"
    assert path.exists()
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 1
    assert rows[0]["event"] == "task_start"
    assert rows[0]["task_id"] == "math"


def test_write_marker_appends_to_existing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", tmp_path)
    for i, event in enumerate(["task_start", "task_end"]):
        csv_io.write_marker(
            "S999",
            {
                "timestamp_ms": 1715600070123 + i * 1000,
                "event": event,
                "task_id": "math",
                "task_name": "Mathe-Aufgaben",
                "task_index": 1,
                "task_category": "writing",
                "protocol_id": "v1",
            },
        )
    rows = list(csv.DictReader((tmp_path / "S999_markers.csv").open()))
    assert [r["event"] for r in rows] == ["task_start", "task_end"]


def test_write_marker_partial_keys_for_study_boundary(tmp_path, monkeypatch):
    """study_start / study_end have no task — task fields stay empty."""
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", tmp_path)
    csv_io.write_marker(
        "S999",
        {
            "timestamp_ms": 1715600070123,
            "event": "study_start",
            "protocol_id": "v1",
        },
    )
    row = next(csv.DictReader((tmp_path / "S999_markers.csv").open()))
    assert row["event"] == "study_start"
    assert row["task_id"] == ""
    assert row["task_index"] == ""
