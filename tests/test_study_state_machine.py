"""Tests for the study state machine — deterministic with externally driven clock."""
from __future__ import annotations

from src.server.study import (
    StudyProtocol,
    StudyTask,
    new_runtime,
)


def _proto():
    return StudyProtocol(
        id="t", name="t", pre_task_seconds=2, randomize=False,
        interleave="writing_with_pauses",
        tasks=[
            StudyTask(id="w1", label="W1", category="writing",
                      duration_seconds=5, instruction="i"),
            StudyTask(id="pause", label="P", category="idle",
                      duration_seconds=3, instances=1, instruction="i"),
        ],
    )


def test_runtime_starts_in_pre_task_for_first_slot():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    snap = rt.snapshot(now_ms=1000)
    assert snap["state"] == "pre_task"
    assert snap["task_index"] == 1
    assert snap["task"]["id"] == "w1"


def test_pre_task_to_running_after_pre_seconds():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    snap = rt.snapshot(now_ms=3000)
    assert snap["state"] == "running"


def test_running_to_next_pre_task_after_duration():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    snap = rt.snapshot(now_ms=8000)
    assert snap["state"] == "pre_task"
    assert snap["task_index"] == 2


def test_done_after_last_slot():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    snap = rt.snapshot(now_ms=13_000)
    assert snap["state"] == "done"


def test_pause_freezes_timer():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    # Drive to running first
    rt.snapshot(now_ms=3000)
    rt.pause(now_ms=4000)
    snap = rt.snapshot(now_ms=9000)
    assert snap["state"] == "paused"


def test_force_next_advances_slot():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    rt.snapshot(now_ms=3000)  # running
    rt.force_next(now_ms=4000)
    snap = rt.snapshot(now_ms=4000)
    assert snap["task_index"] == 2


def test_advance_emits_study_start_and_task_start():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    events = rt.advance_now(now_ms=3000)
    kinds = [e["event"] for e in events]
    assert "study_start" in kinds
    assert "task_start" in kinds


def test_abort_emits_study_end():
    rt = new_runtime(_proto(), session_id="S001", started_at_ms=1000)
    rt.snapshot(now_ms=3000)
    events = rt.abort(now_ms=4000)
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "study_end"
    assert "abort" in kinds
