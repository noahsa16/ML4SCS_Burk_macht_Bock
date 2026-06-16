"""Tests for the protocol scheduler."""
from __future__ import annotations

from src.server.study import (
    StudyProtocol,
    StudyTask,
    ScheduledSlot,
    build_schedule,
    balanced_latin_square,
)


def _is_latin_square(rows: list[list[int]], n: int) -> bool:
    """Every row and every column is a permutation of 0..n-1."""
    full = set(range(n))
    if any(set(r) != full for r in rows):
        return False
    for col in range(n):
        if {r[col] for r in rows} != full:
            return False
    return True


def _adjacent_pairs(rows: list[list[int]]) -> list[tuple[int, int]]:
    return [(r[i], r[i + 1]) for r in rows for i in range(len(r) - 1)]


def test_balanced_latin_square_even_n_has_n_rows_and_is_valid():
    rows = balanced_latin_square(6)
    assert len(rows) == 6
    assert _is_latin_square(rows, 6)


def test_balanced_latin_square_even_n_is_carryover_balanced():
    # Williams design: each ordered adjacent pair (a->b, a!=b) appears
    # exactly once across all rows. n*(n-1) pairs over n rows of (n-1) each.
    rows = balanced_latin_square(6)
    pairs = _adjacent_pairs(rows)
    assert len(pairs) == 6 * 5
    assert len(set(pairs)) == 6 * 5  # all distinct -> each ordered pair once


def test_balanced_latin_square_odd_n_doubles_rows_and_balances_positions():
    rows = balanced_latin_square(3)
    assert len(rows) == 6  # odd n -> 2n rows (square + reversed)
    # each treatment appears in each position exactly twice across the 6 rows
    for col in range(3):
        counts = sorted([r[col] for r in rows])
        assert counts == [0, 0, 1, 1, 2, 2]


def _nwriting(n_writing: int, n_idle: int, interleave="latin_square"):
    tasks = [
        StudyTask(id=f"w{i}", label=f"W{i}", category="writing",
                  duration_seconds=10, instruction="i")
        for i in range(n_writing)
    ] + [
        StudyTask(id=f"n{i}", label=f"N{i}", category="idle",
                  duration_seconds=5, instruction="i")
        for i in range(n_idle)
    ]
    return StudyProtocol(id="t", name="t", pre_task_seconds=3,
                         randomize=True, interleave=interleave, tasks=tasks)


def test_latin_square_scales_to_six_writing_tasks():
    # v2 shape: 6 writing tasks now get a real balanced square (not the
    # seeded-random fallback). Across 6 subjects each writing task appears
    # in each writing-position exactly once.
    p = _nwriting(6, 6)
    positions = [[] for _ in range(6)]
    for si in range(1, 7):
        ids = [s.task.id for s in build_schedule(p, seed=0, subject_index=si)
               if s.category == "writing"]
        assert len(ids) == 6
        for j, tid in enumerate(ids):
            positions[j].append(tid)
    expected = sorted(f"w{i}" for i in range(6))
    for pos in positions:
        assert sorted(pos) == expected


def test_latin_square_balances_idle_tasks_too():
    # The hard negatives (idle class) are also counterbalanced, so each
    # idle task appears in each idle-position exactly once across subjects.
    p = _nwriting(6, 6)
    positions = [[] for _ in range(6)]
    for si in range(1, 7):
        ids = [s.task.id for s in build_schedule(p, seed=0, subject_index=si)
               if s.category == "idle"]
        for j, tid in enumerate(ids):
            positions[j].append(tid)
    expected = sorted(f"n{i}" for i in range(6))
    for pos in positions:
        assert sorted(pos) == expected


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


def test_latin_square_cycles_after_6_subjects():
    p = StudyProtocol(
        id="t", name="t", pre_task_seconds=3,
        randomize=True, interleave="latin_square",
        tasks=[
            StudyTask(id="a", label="A", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="b", label="B", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="c", label="C", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="pause", label="P", category="idle", duration_seconds=5, instances=2, instruction="i"),
        ],
    )
    ids_1 = [s.task.id for s in build_schedule(p, seed=0, subject_index=1) if s.category == "writing"]
    ids_7 = [s.task.id for s in build_schedule(p, seed=0, subject_index=7) if s.category == "writing"]
    assert ids_1 == ids_7


def test_latin_square_balanced_across_6_subjects():
    """Each task appears in each position exactly twice across 6 subjects."""
    p = StudyProtocol(
        id="t", name="t", pre_task_seconds=3,
        randomize=True, interleave="latin_square",
        tasks=[
            StudyTask(id="a", label="A", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="b", label="B", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="c", label="C", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="pause", label="P", category="idle", duration_seconds=5, instances=2, instruction="i"),
        ],
    )
    positions = [[], [], []]
    for i in range(1, 7):
        ids = [s.task.id for s in build_schedule(p, seed=0, subject_index=i) if s.category == "writing"]
        for j, tid in enumerate(ids):
            positions[j].append(tid)
    for pos in positions:
        assert sorted(pos) == ["a", "a", "b", "b", "c", "c"]


def test_duration_jitter_preserves_total_and_bounds():
    p = StudyProtocol(
        id="t", name="t", pre_task_seconds=5,
        randomize=False, interleave="latin_square",
        duration_jitter_pct=0.15,
        tasks=[
            StudyTask(id="a", label="A", category="writing", duration_seconds=240, instruction="i"),
            StudyTask(id="b", label="B", category="writing", duration_seconds=240, instruction="i"),
            StudyTask(id="c", label="C", category="writing", duration_seconds=240, instruction="i"),
            StudyTask(id="pause", label="P", category="idle", duration_seconds=90, instances=2, instruction="i"),
        ],
    )
    # Try several seeds — sum must hold for all, durations must stay in bounds, idle untouched.
    saw_variation = False
    for seed in range(20):
        sched = build_schedule(p, seed=seed, subject_index=1)
        writing = [s for s in sched if s.category == "writing"]
        idle = [s for s in sched if s.category == "idle"]
        assert sum(s.effective_duration_seconds for s in writing) == 240 * 3
        for s in writing:
            assert abs(s.effective_duration_seconds - 240) <= 240 * 0.15 + 1
        for s in idle:
            assert s.effective_duration_seconds == s.task.duration_seconds
        if any(s.effective_duration_seconds != 240 for s in writing):
            saw_variation = True
    assert saw_variation, "Jitter never produced a different duration — RNG dead?"


def test_zero_jitter_is_noop():
    p = StudyProtocol(
        id="t", name="t", pre_task_seconds=5,
        randomize=False, interleave="latin_square",
        duration_jitter_pct=0.0,
        tasks=[
            StudyTask(id="a", label="A", category="writing", duration_seconds=240, instruction="i"),
            StudyTask(id="b", label="B", category="writing", duration_seconds=240, instruction="i"),
            StudyTask(id="c", label="C", category="writing", duration_seconds=240, instruction="i"),
            StudyTask(id="pause", label="P", category="idle", duration_seconds=90, instances=2, instruction="i"),
        ],
    )
    sched = build_schedule(p, seed=0, subject_index=1)
    for s in sched:
        assert s.effective_duration_seconds == s.task.duration_seconds


def test_latin_square_without_subject_index_falls_back_to_random():
    """If subject_index is None and interleave='latin_square', behave like writing_with_pauses (graceful degrade)."""
    p = StudyProtocol(
        id="t", name="t", pre_task_seconds=3,
        randomize=True, interleave="latin_square",
        tasks=[
            StudyTask(id="a", label="A", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="b", label="B", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="c", label="C", category="writing", duration_seconds=10, instruction="i"),
            StudyTask(id="pause", label="P", category="idle", duration_seconds=5, instances=2, instruction="i"),
        ],
    )
    schedule = build_schedule(p, seed=0)
    assert len(schedule) == 5
