"""Tests for _subject_index_for_person_id auto-counter from sessions.csv."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.server.csv_io import _subject_index_for_person_id
from src.server.config import SESSIONS_FIELDNAMES


def _write_sessions_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SESSIONS_FIELDNAMES})


def _make_markers(markers_dir: Path, session_ids: list[str]) -> None:
    markers_dir.mkdir(exist_ok=True)
    for sid in session_ids:
        (markers_dir / f"{sid}_markers.csv").write_text("timestamp_ms,event\n")


def test_first_person_gets_index_1(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    markers.mkdir()
    _write_sessions_csv(sessions, [])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("Alice") == 1


def test_returning_person_keeps_index(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Alice", "description": "real"},
        {"session_id": "S002", "person_id": "Bob", "description": "real"},
        {"session_id": "S003", "person_id": "Alice", "description": "real"},
    ])
    _make_markers(markers, ["S001", "S002", "S003"])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("Alice") == 1
    assert _subject_index_for_person_id("Bob") == 2


def test_new_person_gets_next_index(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Alice", "description": "real"},
        {"session_id": "S002", "person_id": "Bob", "description": "real"},
    ])
    _make_markers(markers, ["S001", "S002"])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("Carol") == 3


def test_order_is_first_appearance_not_alphabetical(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Zach", "description": "real"},
        {"session_id": "S002", "person_id": "Alice", "description": "real"},
    ])
    _make_markers(markers, ["S001", "S002"])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("Zach") == 1
    assert _subject_index_for_person_id("Alice") == 2


def test_missing_csv_returns_1(tmp_path, monkeypatch):
    """If sessions.csv doesn't exist yet, first person is subject 1."""
    sessions = tmp_path / "sessions.csv"  # doesn't exist
    markers = tmp_path / "markers"
    markers.mkdir()
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("Alice") == 1


def test_free_recording_sessions_do_not_count(tmp_path, monkeypatch):
    """Sessions without a markers CSV are skipped — they were free recording."""
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    markers.mkdir()
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "FreeRecGuy", "description": "free"},
        {"session_id": "S002", "person_id": "StudyPerson", "description": "study"},
    ])
    # Only S002 has a markers file
    (markers / "S002_markers.csv").write_text("timestamp_ms,event\n")
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    # StudyPerson is the first counted subject
    assert _subject_index_for_person_id("StudyPerson") == 1
    # FreeRecGuy doesn't count — if they later do a study session, they'd be #2
    assert _subject_index_for_person_id("FreeRecGuy") == 2


def test_test_prefixed_sessions_do_not_count(tmp_path, monkeypatch):
    """Sessions whose description starts with [TEST] are skipped."""
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    markers.mkdir()
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Dev", "description": "[TEST] smoke"},
        {"session_id": "S002", "person_id": "RealSubject", "description": "real"},
    ])
    (markers / "S001_markers.csv").write_text("timestamp_ms,event\n")
    (markers / "S002_markers.csv").write_text("timestamp_ms,event\n")
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("RealSubject") == 1
    # Dev gets index 2 only if they later run a non-test study session
    assert _subject_index_for_person_id("Dev") == 2


def test_test_prefix_case_insensitive(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    markers = tmp_path / "markers"
    markers.mkdir()
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Dev", "description": "[test] x"},
    ])
    (markers / "S001_markers.csv").write_text("timestamp_ms,event\n")
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", markers)
    assert _subject_index_for_person_id("Dev") == 1  # next available, not counted
