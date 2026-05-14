"""Tests for the protocol scheduler."""
from __future__ import annotations

from src.server.study import (
    StudyProtocol,
    StudyTask,
    ScheduledSlot,
    build_schedule,
)


def _proto(tasks, interleave="writing_with_pauses", randomize=True):
    return StudyProtocol(
        id="t", name="t", pre_task_seconds=3,
        randomize=randomize, interleave=interleave,
        tasks=tasks,
    )


def test_schedule_expands_instances():
    p = _proto([
        StudyTask(id="w", label="W", category="writing",
                  duration_seconds=10, instances=1, instruction="i"),
        StudyTask(id="pause", label="P", category="idle",
                  duration_seconds=5, instances=2, instruction="i"),
    ])
    schedule = build_schedule(p, seed=0)
    assert len(schedule) == 3
    cats = [s.category for s in schedule]
    assert cats.count("writing") == 1
    assert cats.count("idle") == 2


def test_writing_with_pauses_alternates_for_v1_shape():
    """v1 case: 3 writing + 2x pause -> W-P-W-P-W."""
    p = _proto([
        StudyTask(id="abschreiben", label="A", category="writing",
                  duration_seconds=240, instruction="i"),
        StudyTask(id="math", label="M", category="writing",
                  duration_seconds=240, instruction="i"),
        StudyTask(id="free", label="F", category="writing",
                  duration_seconds=240, instruction="i"),
        StudyTask(id="pause", label="P", category="idle",
                  duration_seconds=90, instances=2, instruction="i"),
    ])
    schedule = build_schedule(p, seed=42)
    cats = [s.category for s in schedule]
    assert cats == ["writing", "idle", "writing", "idle", "writing"]


def test_seed_reproducibility():
    p = _proto([
        StudyTask(id=f"w{i}", label=f"W{i}", category="writing",
                  duration_seconds=10, instruction="i")
        for i in range(5)
    ])
    a = [s.task.id for s in build_schedule(p, seed=123)]
    b = [s.task.id for s in build_schedule(p, seed=123)]
    c = [s.task.id for s in build_schedule(p, seed=999)]
    assert a == b
    assert a != c


def test_no_randomize_preserves_order():
    p = _proto(
        [
            StudyTask(id="a", label="A", category="writing",
                      duration_seconds=10, instruction="i"),
            StudyTask(id="b", label="B", category="writing",
                      duration_seconds=10, instruction="i"),
            StudyTask(id="c", label="C", category="writing",
                      duration_seconds=10, instruction="i"),
        ],
        randomize=False,
    )
    ids = [s.task.id for s in build_schedule(p, seed=0)]
    assert ids == ["a", "b", "c"]


def test_task_index_is_1_based_and_sequential():
    p = _proto([
        StudyTask(id="w", label="W", category="writing",
                  duration_seconds=10, instances=2, instruction="i"),
    ], randomize=False)
    schedule = build_schedule(p, seed=0)
    assert [s.task_index for s in schedule] == [1, 2]
