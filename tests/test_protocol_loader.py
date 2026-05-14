"""Tests for protocol JSON loading + validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.server.study import (
    StudyProtocol,
    StudyTask,
    load_protocol,
    list_protocols,
)


def _write_proto(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _ok_task(**overrides):
    base = {
        "id": "t1", "label": "T1", "category": "writing",
        "duration_seconds": 10, "instruction": "do",
        "content_type": "text", "content": "x",
    }
    base.update(overrides)
    return base


def _ok_protocol(**overrides):
    base = {
        "id": "tiny", "name": "Tiny",
        "pre_task_seconds": 3, "randomize": False,
        "interleave": "writing_with_pauses",
        "tasks": [_ok_task()],
    }
    base.update(overrides)
    return base


def test_minimal_valid_protocol(tmp_path):
    p = _write_proto(tmp_path / "tiny.json", _ok_protocol())
    proto = load_protocol(p)
    assert proto.id == "tiny"
    assert proto.tasks[0].instances == 1
    assert proto.tasks[0].duration_seconds == 10


def test_rejects_unknown_category(tmp_path):
    p = _write_proto(tmp_path / "bad.json",
                     _ok_protocol(tasks=[_ok_task(category="snacking")]))
    with pytest.raises(Exception):
        load_protocol(p)


def test_rejects_negative_duration(tmp_path):
    p = _write_proto(tmp_path / "neg.json",
                     _ok_protocol(tasks=[_ok_task(duration_seconds=-1)]))
    with pytest.raises(Exception):
        load_protocol(p)


def test_rejects_duplicate_task_ids(tmp_path):
    p = _write_proto(tmp_path / "dup.json", _ok_protocol(tasks=[
        _ok_task(id="a"), _ok_task(id="a"),
    ]))
    with pytest.raises(Exception):
        load_protocol(p)


def test_list_protocols_returns_id_and_name(tmp_path):
    _write_proto(tmp_path / "a.json",
                 _ok_protocol(id="a", name="Alpha"))
    items = list_protocols(tmp_path)
    assert {"id": "a", "name": "Alpha"} in items
