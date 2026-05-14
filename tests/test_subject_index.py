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


def test_first_person_gets_index_1(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    _write_sessions_csv(sessions, [])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    assert _subject_index_for_person_id("Alice") == 1


def test_returning_person_keeps_index(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Alice"},
        {"session_id": "S002", "person_id": "Bob"},
        {"session_id": "S003", "person_id": "Alice"},
    ])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    assert _subject_index_for_person_id("Alice") == 1
    assert _subject_index_for_person_id("Bob") == 2


def test_new_person_gets_next_index(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Alice"},
        {"session_id": "S002", "person_id": "Bob"},
    ])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    assert _subject_index_for_person_id("Carol") == 3


def test_order_is_first_appearance_not_alphabetical(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions.csv"
    _write_sessions_csv(sessions, [
        {"session_id": "S001", "person_id": "Zach"},
        {"session_id": "S002", "person_id": "Alice"},
    ])
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    assert _subject_index_for_person_id("Zach") == 1
    assert _subject_index_for_person_id("Alice") == 2


def test_missing_csv_returns_1(tmp_path, monkeypatch):
    """If sessions.csv doesn't exist yet, first person is subject 1."""
    sessions = tmp_path / "sessions.csv"  # doesn't exist
    monkeypatch.setattr("src.server.csv_io.SESSIONS_CSV", sessions)
    assert _subject_index_for_person_id("Alice") == 1
