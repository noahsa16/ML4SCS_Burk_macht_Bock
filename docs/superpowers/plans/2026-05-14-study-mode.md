# Study Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a protocol-driven Study Mode to the web dashboard so that during data collection the proband sees the current task + animated timer on-screen and task transitions are written to a per-session marker CSV with the same clock as watch/pen data.

**Architecture:** Server-side state machine ticks alongside the existing 1 s `_status_loop`, broadcasts current task state via the existing WebSocket, and writes markers to `data/raw/markers/{session}_markers.csv` using `server_received_ms`. Frontend reads `s.study.*` from the status payload and renders accordingly — no client-side timer truth. Toggle on the Recording page swaps `/session/start` for `/study/start`; everything downstream is server-driven.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / pytest / vanilla JS modules (DOM API, no innerHTML for user-derived strings) / CSS / Chart.js (existing).

**Spec:** `docs/superpowers/specs/2026-05-14-study-mode-design.md`

---

## File Map

**New files:**
- `src/server/study.py` — Pure-Python protocol loader, scheduler, state machine (no FastAPI imports)
- `src/server/routes/study.py` — APIRouter with `/study/*` endpoints
- `study_protocols/v1.json` — Concrete v1 protocol (3 writing + 2× pause)
- `static/css/study-mode.css` — Study-view styles
- `static/js/pages/recording-study.js` — Study-mode rendering helpers (kept separate from main `recording.js`)
- `tests/test_study_state_machine.py`
- `tests/test_protocol_loader.py`
- `tests/test_study_scheduler.py`
- `tests/test_markers_csv.py`
- `tests/test_study_endpoints.py`
- `tests/test_study_e2e.py`

**Modified files:**
- `src/server/config.py` — Add `MARKERS_DIR`, `MARKER_FIELDNAMES`
- `src/server/csv_io.py` — Add `write_marker()`
- `src/server/state.py` — `SessionState.study: StudyRuntime | None`
- `src/server/models.py` — Add `StudyStartBody`
- `src/server/broadcast.py` — Tick the study state machine in `_status_loop`
- `src/server/status.py` — `_status_payload()` includes `study` field
- `src/server/routes/__init__.py` — Include the new `study` router
- `src/server/routes/sessions.py` — `stop_session` tears down `state.study`, and `/session/start` body extracted into `_start_session_internal` for reuse
- `static/views/recording.html` — Mode toggle, protocol dropdown, study view container
- `static/js/pages/recording.js` — Extend `toggleSession` + `onStatus` to handle study mode; add `setRecMode`
- `static/dashboard.js` — Expose `setRecMode`, `studyCmd` on `window`
- `dashboard.html` — `<link>` the new stylesheet
- `static/css/recording.css` — Style additions for the toggle / dropdown
- `src/merge/merge.py` — Optional asof-attach of markers if file exists
- `src/features/windows.py` — Propagate `task_id` per window
- `tests/test_dashboard_static.py` — Add new CSS/JS paths
- `tests/test_merge.py` — Backwards-compat + new marker-attach regression
- `.gitignore` — Add `data/raw/markers/`, `.superpowers/`

---

# Phase A · Backend foundation (pure Python, no FastAPI)

This phase builds the data layer and protocol logic in isolation so it can be fully tested without spinning up the server.

## Task 1: Marker CSV config + writer

**Files:**
- Modify: `src/server/config.py`
- Modify: `src/server/csv_io.py`
- Test: `tests/test_markers_csv.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_markers_csv.py`:

```python
"""Tests for the marker CSV writer."""
from __future__ import annotations

import csv

from src.server import csv_io
from src.server.config import MARKER_FIELDNAMES


def test_marker_fieldnames_are_stable():
    assert MARKER_FIELDNAMES == [
        "timestamp_ms",
        "event",
        "task_id",
        "task_name",
        "task_index",
        "task_category",
        "protocol_id",
    ]


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
```

- [ ] **Step 2: Run test, expect import failure**

Run: `pytest tests/test_markers_csv.py -v`
Expected: FAIL — `cannot import name 'MARKER_FIELDNAMES'`.

- [ ] **Step 3: Add config constants**

In `src/server/config.py`, append after the `LOGS_DIR.mkdir(...)` line:

```python
DATA_RAW_MARKERS = ROOT / "data" / "raw" / "markers"
DATA_RAW_MARKERS.mkdir(parents=True, exist_ok=True)
MARKERS_DIR = DATA_RAW_MARKERS

MARKER_FIELDNAMES = [
    "timestamp_ms",
    "event",
    "task_id",
    "task_name",
    "task_index",
    "task_category",
    "protocol_id",
]
```

- [ ] **Step 4: Add the writer**

In `src/server/csv_io.py`, update the imports block to include the new names:

```python
from .config import (
    AIRPODS_FIELDNAMES, DATA_RAW_AIRPODS, DATA_RAW_PEN, DATA_RAW_WATCH,
    MARKER_FIELDNAMES, MARKERS_DIR,
    SESSIONS_CSV, SESSIONS_FIELDNAMES, WATCH_FIELDNAMES,
)
```

Append at the bottom of the file:

```python
def write_marker(session_id: str, row: dict) -> None:
    """Append one row to data/raw/markers/{session_id}_markers.csv.

    Creates the file with header on first write. Missing keys become empty
    strings (study_start / study_end legitimately have no task fields).
    """
    path = MARKERS_DIR / f"{session_id}_markers.csv"
    _ensure_csv_header(path, MARKER_FIELDNAMES)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MARKER_FIELDNAMES)
        writer.writerow({k: row.get(k, "") for k in MARKER_FIELDNAMES})
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_markers_csv.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/server/config.py src/server/csv_io.py tests/test_markers_csv.py
git commit -m "feat(study): add marker CSV writer + schema constants"
```

---

## Task 2: Protocol JSON loader with Pydantic models

**Files:**
- Create: `src/server/study.py`
- Test: `tests/test_protocol_loader.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_protocol_loader.py`:

```python
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
```

- [ ] **Step 2: Run test, expect import failure**

Run: `pytest tests/test_protocol_loader.py -v`
Expected: FAIL — `cannot import name 'StudyProtocol'`.

- [ ] **Step 3: Create `src/server/study.py` with Pydantic models**

Create `src/server/study.py`:

```python
"""Study Mode — protocol loader, scheduler, and state machine.

Pure Python, no FastAPI imports — fully unit-testable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


TaskCategory = Literal["writing", "idle"]
ContentType = Literal["text", "list", "image"]
InterleaveMode = Literal["writing_with_pauses", "shuffled"]


class StudyTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    category: TaskCategory
    duration_seconds: int = Field(gt=0)
    instances: int = Field(default=1, ge=1, le=20)
    instruction: str
    content_type: ContentType = "text"
    content: Union[str, list[str], None] = None


class StudyProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    pre_task_seconds: int = Field(default=3, ge=0, le=30)
    randomize: bool = True
    interleave: InterleaveMode = "writing_with_pauses"
    tasks: list[StudyTask] = Field(min_length=1)

    @field_validator("tasks")
    @classmethod
    def unique_task_ids(cls, v: list[StudyTask]) -> list[StudyTask]:
        ids = [t.id for t in v]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate task ids: {ids}")
        return v


def load_protocol(path: Path) -> StudyProtocol:
    """Load and validate a protocol JSON from disk."""
    with open(path) as f:
        payload = json.load(f)
    return StudyProtocol.model_validate(payload)


def list_protocols(directory: Path) -> list[dict]:
    """Return [{id, name}] for every valid protocol JSON in ``directory``."""
    out: list[dict] = []
    if not directory.exists():
        return out
    for p in sorted(directory.glob("*.json")):
        try:
            proto = load_protocol(p)
        except Exception:
            continue
        out.append({"id": proto.id, "name": proto.name})
    return out
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_protocol_loader.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/server/study.py tests/test_protocol_loader.py
git commit -m "feat(study): protocol JSON loader + Pydantic schemas"
```

---

## Task 3: Scheduler — expand, shuffle, interleave

**Files:**
- Modify: `src/server/study.py`
- Test: `tests/test_study_scheduler.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_study_scheduler.py`:

```python
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
    """v1 case: 3 writing + 2× pause → W-P-W-P-W."""
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
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_study_scheduler.py -v`
Expected: FAIL — `cannot import name 'ScheduledSlot'`.

- [ ] **Step 3: Append the scheduler to `src/server/study.py`**

Append at the bottom:

```python
import random
from dataclasses import dataclass


@dataclass
class ScheduledSlot:
    """One slot in the per-session schedule.

    `task_index` is 1-based and sequential across the schedule. Multiple
    slots can share the same `task` when `instances > 1`.
    """
    task_index: int
    task: StudyTask

    @property
    def category(self) -> str:
        return self.task.category


def _expand_instances(tasks: list[StudyTask]) -> list[StudyTask]:
    out: list[StudyTask] = []
    for t in tasks:
        for _ in range(t.instances):
            out.append(t)
    return out


def _interleave_writing_with_pauses(
    writing: list[StudyTask], idle: list[StudyTask],
) -> list[StudyTask]:
    """Weave W and I, attach the longer-group tail at the end."""
    out: list[StudyTask] = []
    n = min(len(writing), len(idle))
    for i in range(n):
        out.append(writing[i])
        out.append(idle[i])
    out.extend(writing[n:])
    out.extend(idle[n:])
    return out


def build_schedule(protocol: StudyProtocol, seed: int) -> list[ScheduledSlot]:
    """Deterministic per-session schedule (seeded shuffle, then interleave)."""
    expanded = _expand_instances(protocol.tasks)
    writing = [t for t in expanded if t.category == "writing"]
    idle = [t for t in expanded if t.category == "idle"]

    rng = random.Random(seed)
    if protocol.randomize:
        rng.shuffle(writing)
        rng.shuffle(idle)

    if protocol.interleave == "writing_with_pauses":
        ordered = _interleave_writing_with_pauses(writing, idle)
    else:
        ordered = writing + idle
        if protocol.randomize:
            rng.shuffle(ordered)

    return [ScheduledSlot(task_index=i + 1, task=t)
            for i, t in enumerate(ordered)]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_study_scheduler.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/server/study.py tests/test_study_scheduler.py
git commit -m "feat(study): protocol scheduler — expand, shuffle, interleave"
```

---

## Task 4: State machine — idle → pre_task → running → done (+ pause/resume/abort)

**Files:**
- Modify: `src/server/study.py`
- Test: `tests/test_study_state_machine.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_study_state_machine.py`:

```python
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
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_study_state_machine.py -v`
Expected: FAIL.

- [ ] **Step 3: Append the state machine to `src/server/study.py`**

Append at the bottom:

```python
class StudyRuntime:
    """In-memory state machine for one study session.

    Time is driven externally — call ``advance_now(now_ms=...)`` once per
    server tick. The runtime never reads the wall clock itself, which
    makes it deterministic and unit-testable.
    """

    def __init__(self, protocol: StudyProtocol, schedule: list[ScheduledSlot],
                 session_id: str, started_at_ms: int) -> None:
        self.protocol = protocol
        self.schedule = schedule
        self.session_id = session_id
        self.started_at_ms = started_at_ms

        self._slot_idx: int = 0
        self._slot_phase: str = "pre_task"
        self._slot_phase_start_ms: int = started_at_ms
        self._paused: bool = False
        self._paused_at_ms: Optional[int] = None
        self._paused_total_ms: int = 0
        self._study_done: bool = False
        self._emitted_study_start: bool = False
        self._emitted_task_start_for: set[int] = set()

    @property
    def current_slot(self) -> Optional[ScheduledSlot]:
        if self._study_done or self._slot_idx >= len(self.schedule):
            return None
        return self.schedule[self._slot_idx]

    def _effective_now(self, now_ms: int) -> int:
        """Remove time spent paused so the per-task timer does not drift."""
        if self._paused and self._paused_at_ms is not None:
            return self._paused_at_ms - self._paused_total_ms
        return now_ms - self._paused_total_ms

    def snapshot(self, now_ms: int) -> dict:
        # Advance internal pointers first so the snapshot is consistent.
        self.advance_now(now_ms=now_ms)
        slot = self.current_slot
        if self._study_done or slot is None:
            return {"active": True, "state": "done", "protocol_id": self.protocol.id}

        eff_now = self._effective_now(now_ms)
        phase_elapsed_ms = max(0, eff_now - self._slot_phase_start_ms)
        if self._paused:
            state = "paused"
        else:
            state = self._slot_phase

        if self._slot_phase == "pre_task":
            duration_ms = self.protocol.pre_task_seconds * 1000
        else:
            duration_ms = slot.task.duration_seconds * 1000

        return {
            "active": True,
            "state": state,
            "task_index": slot.task_index,
            "task_total": len(self.schedule),
            "task": {
                "id": slot.task.id,
                "label": slot.task.label,
                "category": slot.task.category,
                "instruction": slot.task.instruction,
                "content_type": slot.task.content_type,
                "content": slot.task.content,
            },
            "task_remaining_ms": max(0, duration_ms - phase_elapsed_ms),
            "task_duration_ms": duration_ms,
            "protocol_id": self.protocol.id,
        }

    def advance_now(self, now_ms: int, force_next: bool = False) -> list[dict]:
        events: list[dict] = []

        if not self._emitted_study_start:
            events.append(self._mk_event(now_ms, "study_start"))
            self._emitted_study_start = True

        if self._paused and not force_next:
            return events

        eff_now = self._effective_now(now_ms)
        while not self._study_done:
            slot = self.current_slot
            if slot is None:
                self._study_done = True
                events.append(self._mk_event(now_ms, "study_end"))
                break

            if self._slot_phase == "pre_task":
                duration_ms = self.protocol.pre_task_seconds * 1000
                phase_elapsed = eff_now - self._slot_phase_start_ms
                if force_next or phase_elapsed >= duration_ms:
                    self._slot_phase = "running"
                    self._slot_phase_start_ms = (
                        eff_now if force_next
                        else self._slot_phase_start_ms + duration_ms
                    )
                    if slot.task_index not in self._emitted_task_start_for:
                        events.append(self._mk_event(now_ms, "task_start", slot))
                        self._emitted_task_start_for.add(slot.task_index)
                    if force_next:
                        events.append(self._mk_event(now_ms, "task_end", slot))
                        self._slot_idx += 1
                        self._slot_phase = "pre_task"
                        self._slot_phase_start_ms = eff_now
                        force_next = False
                        continue
                else:
                    break
            else:  # running
                duration_ms = slot.task.duration_seconds * 1000
                phase_elapsed = eff_now - self._slot_phase_start_ms
                if force_next or phase_elapsed >= duration_ms:
                    events.append(self._mk_event(now_ms, "task_end", slot))
                    self._slot_idx += 1
                    self._slot_phase = "pre_task"
                    self._slot_phase_start_ms = (
                        eff_now if force_next
                        else self._slot_phase_start_ms + duration_ms
                    )
                    force_next = False
                    continue
                else:
                    break

        return events

    def pause(self, now_ms: int) -> list[dict]:
        if self._paused or self._study_done:
            return []
        self._paused = True
        self._paused_at_ms = now_ms
        slot = self.current_slot
        return [self._mk_event(now_ms, "pause", slot)] if slot else []

    def resume(self, now_ms: int) -> list[dict]:
        if not self._paused or self._paused_at_ms is None:
            return []
        self._paused_total_ms += (now_ms - self._paused_at_ms)
        self._paused = False
        self._paused_at_ms = None
        slot = self.current_slot
        return [self._mk_event(now_ms, "resume", slot)] if slot else []

    def abort(self, now_ms: int) -> list[dict]:
        events: list[dict] = []
        slot = self.current_slot
        if slot is not None and self._slot_phase == "running":
            events.append(self._mk_event(now_ms, "task_end", slot))
        events.append(self._mk_event(now_ms, "abort", slot))
        events.append(self._mk_event(now_ms, "study_end"))
        self._study_done = True
        return events

    def force_next(self, now_ms: int) -> list[dict]:
        return self.advance_now(now_ms=now_ms, force_next=True)

    def _mk_event(self, now_ms: int, event: str,
                  slot: Optional[ScheduledSlot] = None) -> dict:
        row = {
            "timestamp_ms": now_ms,
            "event": event,
            "protocol_id": self.protocol.id,
        }
        if slot is not None:
            row.update({
                "task_id": slot.task.id,
                "task_name": slot.task.label,
                "task_index": slot.task_index,
                "task_category": slot.task.category,
            })
        return row


def new_runtime(protocol: StudyProtocol, session_id: str,
                started_at_ms: int, seed: Optional[int] = None) -> StudyRuntime:
    """Build a StudyRuntime with a deterministic schedule.

    Seed defaults to a stable hash of session_id (reproducible per subject).
    """
    if seed is None:
        seed = abs(hash(session_id))
    schedule = build_schedule(protocol, seed=seed)
    return StudyRuntime(protocol, schedule, session_id, started_at_ms)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_study_state_machine.py -v`
Expected: 8 passed. If an edge case fails, fix the state-machine logic before continuing — do not move past this task with red tests.

- [ ] **Step 5: Commit**

```bash
git add src/server/study.py tests/test_study_state_machine.py
git commit -m "feat(study): state machine — pre_task/running/paused/done"
```

---

# Phase B · FastAPI integration

## Task 5: v1 protocol JSON file

**Files:**
- Create: `study_protocols/v1.json`

- [ ] **Step 1: Create the directory and file**

```bash
mkdir -p study_protocols
```

Create `study_protocols/v1.json`:

```json
{
  "id": "v1",
  "name": "ML4SCS Study Protocol v1",
  "pre_task_seconds": 3,
  "randomize": true,
  "interleave": "writing_with_pauses",
  "tasks": [
    {
      "id": "abschreiben",
      "label": "Text abschreiben",
      "category": "writing",
      "duration_seconds": 240,
      "instances": 1,
      "instruction": "Schreibe den folgenden Text auf Papier ab.",
      "content_type": "text",
      "content": "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat."
    },
    {
      "id": "math",
      "label": "Mathe-Aufgaben",
      "category": "writing",
      "duration_seconds": 240,
      "instances": 1,
      "instruction": "Bearbeite die Aufgaben in deinem üblichen Tempo.",
      "content_type": "list",
      "content": [
        "17 × 14 = ?",
        "Vereinfache: (3x + 5)(x − 2)",
        "Berechne: ∫ x² dx von 0 bis 3",
        "Faktorisiere: x² − 9x + 20",
        "Löse: 2x² − 7x + 3 = 0"
      ]
    },
    {
      "id": "free_writing",
      "label": "Freies Schreiben",
      "category": "writing",
      "duration_seconds": 240,
      "instances": 1,
      "instruction": "Schreibe einen frei gewählten Text — z. B. ein kurzer Erlebnisbericht.",
      "content_type": "text",
      "content": "Schreibe einfach drauf los — kein Thema vorgegeben."
    },
    {
      "id": "pause",
      "label": "Pause",
      "category": "idle",
      "duration_seconds": 90,
      "instances": 2,
      "instruction": "Lege den Stift weg. Mach was du willst — strecken, trinken, kurz reden. Hauptsache: du schreibst nicht.",
      "content_type": "text",
      "content": "Pause. Stift kann auf dem Tisch liegen bleiben."
    }
  ]
}
```

- [ ] **Step 2: Verify it loads**

Run:

```bash
python -c "from pathlib import Path; from src.server.study import load_protocol; p = load_protocol(Path('study_protocols/v1.json')); print(p.id, len(p.tasks), 'tasks')"
```

Expected output: `v1 4 tasks`.

- [ ] **Step 3: Commit**

```bash
git add study_protocols/v1.json
git commit -m "feat(study): v1 protocol — 3 writing tasks + 2× pause (~15 min)"
```

---

## Task 6: SessionState.study + status payload

**Files:**
- Modify: `src/server/state.py`
- Modify: `src/server/status.py`
- Modify: `src/server/models.py`

- [ ] **Step 1: Add the `study` attribute to `SessionState`**

In `src/server/state.py`, inside `SessionState.__init__`, just before the `self.event_log = …` line, insert:

```python
        # Study Mode runtime — set by /study/start, cleared on session stop
        # or /study/abort. None means "free recording mode".
        self.study = None  # Optional[StudyRuntime]
```

- [ ] **Step 2: Add `StudyStartBody` to `src/server/models.py`**

Append at the bottom of `src/server/models.py`:

```python
class StudyStartBody(BaseModel):
    protocol_id: str = "v1"
    person_id: str = "unknown"
    description: str = ""
    force_preflight: bool = False

    @field_validator("person_id", mode="before")
    @classmethod
    def normalize_person_id(cls, v: object) -> str:
        s = str(v).strip() if v is not None else ""
        return s or "unknown"

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: object) -> str:
        return str(v).strip() if v is not None else ""
```

- [ ] **Step 3: Inject `study` into `_status_payload`**

Open `src/server/status.py` and locate the `_status_payload(...)` function. Just before the return-dict expression, insert:

```python
    # Always include `study` so the frontend doesn't have to branch on
    # absence on every WS tick. Inactive → {"active": False}.
    import time as _time
    if state.study is not None:
        _study_payload = state.study.snapshot(now_ms=int(_time.time() * 1000))
    else:
        _study_payload = {"active": False}
```

Then add a `"study": _study_payload,` key to the returned dict, somewhere near the bottom alongside the other top-level fields.

- [ ] **Step 4: Smoke-test the import path**

Run:

```bash
python -c "from src.server.status import _status_payload; print(_status_payload(pen_samples=0, last_pen_dot=None)['study'])"
```

Expected: `{'active': False}`.

- [ ] **Step 5: Commit**

```bash
git add src/server/state.py src/server/status.py src/server/models.py
git commit -m "feat(study): SessionState.study + status payload field"
```

---

## Task 7: Tick the state machine in `_status_loop`

**Files:**
- Modify: `src/server/broadcast.py`

- [ ] **Step 1: Add the tick call**

In `src/server/broadcast.py`, find the `_status_loop` function. After the rate updates and the pen-dot logging, but **before** the `await _broadcast(_status_payload(...))` line, insert:

```python
        # Tick the study state machine if active. Emitted marker events are
        # persisted to the per-session markers CSV with the same server clock
        # used by watch / pen CSVs (server_received_ms == int(time.time()*1000)).
        if state.active and state.study is not None:
            try:
                from .csv_io import write_marker
                _study_now_ms = int(time.time() * 1000)
                for ev in state.study.advance_now(now_ms=_study_now_ms):
                    write_marker(state.active.session_id, ev)
            except Exception:
                log.exception("study tick failed")
```

- [ ] **Step 2: Syntax-check the module**

Run: `python -c "from src.server.broadcast import _status_loop; print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add src/server/broadcast.py
git commit -m "feat(study): tick state machine in _status_loop, persist markers"
```

---

## Task 8: `/study/*` routes + session-start refactor

**Files:**
- Modify: `src/server/routes/sessions.py` (extract `_start_session_internal`)
- Create: `src/server/routes/study.py`
- Modify: `src/server/routes/__init__.py`
- Test: `tests/test_study_endpoints.py` (new)

- [ ] **Step 1: Extract `_start_session_internal` in `sessions.py`**

Open `src/server/routes/sessions.py`. Find the `POST /session/start` handler (a function decorated with `@router.post("/session/start")`). Move its body verbatim into a new helper `async def _start_session_internal(person_id, description, force_preflight)` defined just above the handler. Replace the handler body with a one-line delegation:

```python
async def _start_session_internal(
    person_id: str, description: str, force_preflight: bool
) -> dict:
    # [MOVE the prior body of session_start() here, verbatim.
    #  Read the three values from the parameters above instead of from a body
    #  Pydantic instance — replace any `body.person_id` / `body.description` /
    #  `body.force_preflight` references with the bare parameter names.]
    ...


@router.post("/session/start")
async def session_start(body: SessionStartBody):
    return await _start_session_internal(
        person_id=body.person_id,
        description=body.description,
        force_preflight=body.force_preflight,
    )
```

Run the existing endpoint suite to confirm the refactor preserves behavior:

```bash
pytest tests/test_endpoints.py -v
```

Expected: same passes as before the refactor (no regressions).

- [ ] **Step 2: Tear down `state.study` in `POST /session/stop`**

In the existing `POST /session/stop` handler (same file), near the top after the active-session check, add:

```python
    # If a study was running on this session, write a final abort marker so
    # downstream analysis knows the schedule didn't complete naturally.
    if state.study is not None:
        from time import time as _t
        from ..csv_io import write_marker as _wm
        for ev in state.study.abort(now_ms=int(_t() * 1000)):
            _wm(state.active.session_id, ev)
        state.study = None
```

- [ ] **Step 3: Write the failing endpoint test**

Create `tests/test_study_endpoints.py`:

```python
"""FastAPI TestClient smokes for /study/*."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", tmp_path / "markers")
    (tmp_path / "markers").mkdir()
    from server import app
    return TestClient(app)


def test_list_protocols_includes_v1(client):
    r = client.get("/study/protocols")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert "v1" in ids


def test_start_study_returns_session_and_schedule(client):
    r = client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST",
        "description": "endpoint smoke", "force_preflight": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "session_id" in body
    assert body["protocol"]["id"] == "v1"
    assert isinstance(body["schedule"], list)
    assert len(body["schedule"]) == 5  # 3 writing + 2× pause
    client.post("/session/stop")


def test_pause_resume_abort_round_trip(client):
    client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST",
        "description": "x", "force_preflight": True,
    })
    assert client.post("/study/pause").status_code == 200
    assert client.post("/study/pause").status_code == 200
    assert client.post("/study/next").status_code == 200
    assert client.post("/study/abort").status_code == 200
    client.post("/session/stop")


def test_pause_when_inactive_returns_409(client):
    r = client.post("/study/pause")
    assert r.status_code == 409
```

- [ ] **Step 4: Run, expect 404 (route not registered yet)**

Run: `pytest tests/test_study_endpoints.py -v`
Expected: FAIL — `/study/protocols` returns 404.

- [ ] **Step 5: Create the router**

Create `src/server/routes/study.py`:

```python
"""FastAPI routes for Study Mode."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from ..config import ROOT
from ..csv_io import write_marker
from ..models import StudyStartBody
from ..state import state
from ..study import load_protocol, list_protocols, new_runtime

router = APIRouter()

PROTOCOLS_DIR = ROOT / "study_protocols"


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.get("/study/protocols")
def get_protocols() -> list[dict]:
    return list_protocols(PROTOCOLS_DIR)


@router.post("/study/start")
async def start_study(body: StudyStartBody) -> dict:
    proto_path = PROTOCOLS_DIR / f"{body.protocol_id}.json"
    if not proto_path.exists():
        raise HTTPException(404, f"protocol {body.protocol_id!r} not found")
    protocol = load_protocol(proto_path)

    # Reuse the existing session-start path so preflight / session_id allocation
    # / pen-logger bootstrapping behave identically to /session/start.
    from .sessions import _start_session_internal
    session_info = await _start_session_internal(
        person_id=body.person_id,
        description=body.description or f"study:{protocol.id}",
        force_preflight=body.force_preflight,
    )
    if "session_id" not in session_info:
        return session_info  # surface preflight blocker/warning unchanged

    rt = new_runtime(protocol, session_info["session_id"], started_at_ms=_now_ms())
    state.study = rt

    return {
        "session_id": session_info["session_id"],
        "protocol": {"id": protocol.id, "name": protocol.name},
        "schedule": [
            {"task_index": s.task_index, "task_id": s.task.id,
             "label": s.task.label, "category": s.task.category,
             "duration_seconds": s.task.duration_seconds}
            for s in rt.schedule
        ],
    }


@router.post("/study/next")
def next_task() -> dict:
    if state.study is None or state.active is None:
        raise HTTPException(409, "no study running")
    events = state.study.force_next(now_ms=_now_ms())
    for ev in events:
        write_marker(state.active.session_id, ev)
    return {"ok": True, "events": [e["event"] for e in events]}


@router.post("/study/pause")
def pause_or_resume() -> dict:
    if state.study is None or state.active is None:
        raise HTTPException(409, "no study running")
    now = _now_ms()
    if state.study._paused:
        events = state.study.resume(now_ms=now)
        action = "resume"
    else:
        events = state.study.pause(now_ms=now)
        action = "pause"
    for ev in events:
        write_marker(state.active.session_id, ev)
    return {"ok": True, "action": action}


@router.post("/study/abort")
def abort_study() -> dict:
    if state.study is None or state.active is None:
        raise HTTPException(409, "no study running")
    events = state.study.abort(now_ms=_now_ms())
    for ev in events:
        write_marker(state.active.session_id, ev)
    state.study = None
    return {"ok": True}
```

- [ ] **Step 6: Register the router**

Edit `src/server/routes/__init__.py`:

```python
from . import airpods, dashboard, pen, sessions, study, watch, ws
from ._helpers import _new_command_id, _session_preflight_payload

router = APIRouter()
for _mod in (dashboard, sessions, pen, watch, airpods, study, ws):
    router.include_router(_mod.router)
```

- [ ] **Step 7: Run endpoint tests**

Run: `pytest tests/test_study_endpoints.py tests/test_endpoints.py -v`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/server/routes/study.py src/server/routes/__init__.py \
        src/server/routes/sessions.py tests/test_study_endpoints.py
git commit -m "feat(study): /study/{start,next,pause,abort,protocols} endpoints"
```

---

# Phase C · Frontend (DOM API, no innerHTML for user-derived strings)

## Task 9: Mode toggle UI + protocol dropdown

**Files:**
- Modify: `static/views/recording.html`
- Modify: `static/css/recording.css`
- Modify: `tests/test_dashboard_static.py`

- [ ] **Step 1: Insert the toggle row + protocol field**

In `static/views/recording.html`, find the existing controls stripe:

```html
      <div class="rec-console-controls">
        <label class="rec-field">
          <span class="rec-field-label">person</span>
```

Just before `<div class="rec-console-controls">`, insert:

```html
      <!-- Mode toggle: free recording vs. guided study ─────────────── -->
      <div class="rec-mode-toggle" role="radiogroup" aria-label="Recording mode">
        <button type="button" class="rec-mode-opt is-active" data-mode="free"
                onclick="setRecMode('free')" aria-pressed="true">free recording</button>
        <button type="button" class="rec-mode-opt" data-mode="study"
                onclick="setRecMode('study')" aria-pressed="false">study mode</button>
      </div>

```

Inside `rec-console-controls`, after the description `<label>` and before the START button, insert the protocol picker (hidden by default — JS shows it in study mode):

```html
        <label class="rec-field" id="protocolField" style="display:none">
          <span class="rec-field-label">protocol</span>
          <select class="rec-field-input" id="protocolSelect"></select>
        </label>
```

After the closing `</div>` of `rec-shell`, insert the study view container (a sibling of `rec-shell`):

```html
<!-- Study Mode rendering surface — populated by recording-study.js -->
<section class="rec-study-view" id="rec-study-view" style="display:none">
  <div class="rec-study-stage" id="recStudyStage">
    <!-- contents built by JS via DOM API based on s.study.state -->
  </div>
</section>
```

- [ ] **Step 2: Style the toggle**

Append to `static/css/recording.css`:

```css
/* ════════════════════════════════════════════════════════════
   Study Mode — toggle row
   ════════════════════════════════════════════════════════════ */
.rec-mode-toggle {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 6px;
  background: oklch(0.93 0.012 80);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: lowercase;
  margin-bottom: 12px;
}
.rec-mode-opt {
  appearance: none;
  border: 0;
  background: transparent;
  padding: 6px 12px;
  border-radius: 4px;
  color: oklch(0.45 0.018 58);
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.rec-mode-opt.is-active {
  background: oklch(0.22 0.025 55);
  color: oklch(0.97 0.008 80);
}
.rec-mode-opt:hover:not(.is-active) { color: oklch(0.22 0.025 55); }
```

- [ ] **Step 3: Add the new CSS / JS paths to the 404-trap test**

In `tests/test_dashboard_static.py`, add to the parametrise list:

```python
    "static/css/study-mode.css",
    "static/js/pages/recording-study.js",
```

The CSS / JS files don't exist yet — Tasks 11 and 13 create them. The test will fail until then, which is fine because Step 4 of this task is "skip the smoke until Task 13".

- [ ] **Step 4: Commit**

```bash
git add static/views/recording.html static/css/recording.css tests/test_dashboard_static.py
git commit -m "feat(study): mode toggle row + protocol dropdown in Recording view"
```

---

## Task 10: `setRecMode` + study-aware `toggleSession`

**Files:**
- Modify: `static/js/pages/recording.js`
- Modify: `static/dashboard.js`

- [ ] **Step 1: Add mode + protocol helpers to recording.js**

In `static/js/pages/recording.js`, append after the existing imports section (after the `import { renderState } from '/static/js/core/states.js';` line):

```javascript
// ════════════════════════════════════════════════════════════
//  STUDY MODE — toggle + protocol picker
// ════════════════════════════════════════════════════════════
let _recMode = 'free';
let _protocolsLoaded = false;

export function setRecMode(mode) {
  _recMode = (mode === 'study') ? 'study' : 'free';
  document.querySelectorAll('.rec-mode-opt').forEach((b) => {
    const isActive = b.dataset.mode === _recMode;
    b.classList.toggle('is-active', isActive);
    b.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
  const protoField = document.getElementById('protocolField');
  if (protoField) protoField.style.display = (_recMode === 'study') ? '' : 'none';
  const btnLabel = document.querySelector('#sessionBtn .rec-action-btn-label');
  if (btnLabel && !S.sessionActive) {
    btnLabel.textContent = (_recMode === 'study') ? 'START STUDY' : 'START';
  }
  if (_recMode === 'study') _ensureProtocolsLoaded();
}

async function _ensureProtocolsLoaded() {
  if (_protocolsLoaded) return;
  const list = await api('/study/protocols');
  const sel = document.getElementById('protocolSelect');
  if (!sel || !Array.isArray(list)) return;
  // Populate via DOM API — no innerHTML of user-derived strings.
  sel.replaceChildren();
  for (const p of list) {
    const opt = document.createElement('option');
    opt.value = String(p.id);
    opt.textContent = String(p.name);
    sel.appendChild(opt);
  }
  _protocolsLoaded = true;
}
```

- [ ] **Step 2: Branch `toggleSession()` on mode**

Replace the entire existing `toggleSession()` function with:

```javascript
export async function toggleSession() {
  if (S.sessionActive) {
    const res = await api('/session/stop', 'POST');
    toast('Session stopped');
    if (res?.command_id) console.info('Stop command_id', res.command_id);
    S.chartMax = 0;
    return;
  }

  const pid = document.getElementById('personId').value.trim() || 'unknown';
  const description = document.getElementById('sessionDescription').value.trim();
  const preflight = await runStartPreflight();
  if (!preflight.canStart) return;

  if (_recMode === 'study') {
    const protocolId = document.getElementById('protocolSelect')?.value || 'v1';
    const res = await api('/study/start', 'POST', {
      protocol_id: protocolId,
      person_id: pid,
      description,
      force_preflight: preflight.force,
    });
    if (res?.preflight && !res.session_id) {
      showPreflightResult(res.preflight);
      return;
    }
    if (res?.session_id) {
      const n = res.schedule?.length ?? 0;
      toast(`Study ${res.session_id} started (${n} slots)`);
    }
    return;
  }

  // free mode (legacy path)
  const res = await api('/session/start', 'POST', {
    person_id: pid,
    description,
    force_preflight: preflight.force,
  });
  if (res?.preflight && !res.session_id) {
    showPreflightResult(res.preflight);
    return;
  }
  if (res?.session_id) toast(`Recording session ${res.session_id} started`);
}
```

- [ ] **Step 3: Expose `setRecMode` on `window`**

In `static/dashboard.js`, find the `Object.assign(window, { ... })` block at the bottom and add `setRecMode` to the list. The import for `setRecMode` comes from the same module that already exports `toggleSession` (i.e., `recording.js`), so adjust the existing destructured import accordingly.

- [ ] **Step 4: Smoke-test in the browser**

```bash
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000`. Click `study mode`: protocol dropdown appears with `ML4SCS Study Protocol v1`, START label changes to `START STUDY`. Click back to `free recording`: dropdown hides, label reverts.

- [ ] **Step 5: Commit**

```bash
git add static/js/pages/recording.js static/dashboard.js
git commit -m "feat(study): mode-switch in toggleSession + protocol picker"
```

---

## Task 11: Study view renderer (DOM API only)

**Files:**
- Create: `static/js/pages/recording-study.js`
- Modify: `static/js/pages/recording.js`

- [ ] **Step 1: Create the renderer module — DOM-API style, no innerHTML for user content**

Create `static/js/pages/recording-study.js`:

```javascript
// ════════════════════════════════════════════════════════════
//  RECORDING — Study Mode renderer
//  Driven entirely by `s.study` from the WS status payload.
//  All user-derived strings (task label, instruction, content) are
//  inserted via textContent — never innerHTML — to avoid XSS even
//  though protocol JSON is repo-controlled.
// ════════════════════════════════════════════════════════════

import { api } from '/static/js/core/api.js';

function _fmtClock(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function _el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = String(text);
  return e;
}

function _renderContent(task) {
  // Returns a single DOM element representing the task content.
  if (!task) return _el('div');
  if (task.content_type === 'list' && Array.isArray(task.content)) {
    const ol = _el('ol', 'study-content-list');
    for (const item of task.content) {
      ol.appendChild(_el('li', null, String(item)));
    }
    return ol;
  }
  return _el('div', 'study-content-text', String(task.content ?? ''));
}

function _buildPreTask(s) {
  const root = _el('div', 'study-pre-task');
  root.appendChild(_el('div', 'study-eyebrow',
    `/ task ${s.task_index} of ${s.task_total} · gleich beginnt`));
  root.appendChild(_el('div', 'study-title-big', s.task.label));
  root.appendChild(_el('div', 'study-instruction', s.task.instruction));
  root.appendChild(_el('div', 'study-timer-big', _fmtClock(s.task_remaining_ms)));
  root.appendChild(_el('div', 'study-hint',
    `starts in ${_fmtClock(s.task_remaining_ms)} · ready your pen`));
  return root;
}

function _buildRunning(s, paused) {
  const root = _el('div', `study-running${paused ? ' is-paused' : ''}`);
  const topbar = _el('div', 'study-topbar');
  const left = _el('div', 'study-topbar-left');
  left.appendChild(_el('span', 'study-eyebrow',
    `/ task ${s.task_index}/${s.task_total}`));
  left.appendChild(_el('span', 'study-topbar-title', s.task.label));
  topbar.appendChild(left);

  const right = _el('div', 'study-topbar-right');
  const progressOuter = _el('div', 'study-progress');
  const progressFill = _el('div', 'study-progress-fill');
  const pct = (1 - (s.task_remaining_ms / Math.max(1, s.task_duration_ms))) * 100;
  progressFill.style.width = `${pct.toFixed(1)}%`;
  progressOuter.appendChild(progressFill);
  right.appendChild(progressOuter);
  right.appendChild(_el('div', 'study-timer-small', _fmtClock(s.task_remaining_ms)));
  topbar.appendChild(right);
  root.appendChild(topbar);

  const content = _el('div', 'study-content-area');
  content.appendChild(_el('div', 'study-instruction-small', s.task.instruction));
  content.appendChild(_renderContent(s.task));
  root.appendChild(content);

  if (paused) {
    root.appendChild(_el('div', 'study-paused-overlay', 'Paused — VL override'));
  }
  return root;
}

function _buildDone() {
  const root = _el('div', 'study-done');
  root.appendChild(_el('div', 'study-done-glyph', '✓'));
  root.appendChild(_el('div', 'study-done-title', 'Studie abgeschlossen'));
  root.appendChild(_el('div', 'study-done-hint',
    'Die Aufnahme läuft weiter — Versuchsleiter kann jetzt stoppen.'));
  return root;
}

function _buildVLPanel() {
  const panel = _el('div', 'study-vl-panel');
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', 'Experimenter controls');

  const mk = (label, action, title, danger) => {
    const b = _el('button', `study-vl-btn${danger ? ' study-vl-btn--danger' : ''}`, label);
    b.type = 'button';
    b.title = title;
    b.addEventListener('click', () => studyCmd(action));
    return b;
  };

  panel.appendChild(mk('⏸', 'pause', 'Pause / resume (Space)', false));
  panel.appendChild(mk('⏭', 'next',  'Next task (→)', false));
  panel.appendChild(mk('✕', 'abort', 'Abort (Esc)', true));
  return panel;
}

export function renderStudyView(s) {
  const wrap = document.getElementById('rec-study-view');
  const stage = document.getElementById('recStudyStage');
  if (!wrap || !stage) return;

  if (!s || !s.active) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = '';

  stage.replaceChildren();  // clear previous frame
  if (s.state === 'pre_task')      stage.appendChild(_buildPreTask(s));
  else if (s.state === 'running')  stage.appendChild(_buildRunning(s, false));
  else if (s.state === 'paused')   stage.appendChild(_buildRunning(s, true));
  else if (s.state === 'done')     stage.appendChild(_buildDone());

  if (s.state !== 'done') stage.appendChild(_buildVLPanel());
}

export async function studyCmd(cmd) {
  const endpoint = cmd === 'pause' ? '/study/pause'
                 : cmd === 'next'  ? '/study/next'
                 : cmd === 'abort' ? '/study/abort'
                 : null;
  if (!endpoint) return;
  await api(endpoint, 'POST');
}

// Keyboard shortcuts — only fire while study view is visible.
function _isStudyActive() {
  const wrap = document.getElementById('rec-study-view');
  return wrap && wrap.style.display !== 'none';
}

function _onKey(e) {
  if (!_isStudyActive()) return;
  if (e.target.matches('input, textarea, select')) return;
  if (e.key === ' ')             { e.preventDefault(); studyCmd('pause'); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); studyCmd('next'); }
  else if (e.key === 'Escape')     { e.preventDefault(); studyCmd('abort'); }
}

if (typeof window !== 'undefined' && !window.__studyKeyboardWired) {
  window.addEventListener('keydown', _onKey);
  window.__studyKeyboardWired = true;
}
```

- [ ] **Step 2: Wire `renderStudyView` into `recording.js#onStatus`**

In `static/js/pages/recording.js`, add the import near the top:

```javascript
import { renderStudyView } from '/static/js/pages/recording-study.js';
```

At the end of `onStatus(s)`, append:

```javascript
  // Render study view (no-op when s.study is absent or inactive).
  renderStudyView(s.study);
  // Hide regular live-streams while a study runs to give the proband-facing
  // surface the full page.
  const streamsSec = document.getElementById('rec-sec-streams');
  if (streamsSec) streamsSec.style.display = s.study?.active ? 'none' : '';
```

- [ ] **Step 3: Expose `studyCmd` on `window` (so the topbar etc. can call it if ever needed)**

In `static/dashboard.js`, at the top with the other page-module imports:

```javascript
import { studyCmd } from '/static/js/pages/recording-study.js';
```

Add `studyCmd` to the existing `Object.assign(window, { ... })` block.

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/recording-study.js static/js/pages/recording.js static/dashboard.js
git commit -m "feat(study): proband-view renderer (DOM API, textContent only)"
```

---

## Task 12: study-mode.css

**Files:**
- Create: `static/css/study-mode.css`
- Modify: `dashboard.html`

- [ ] **Step 1: Create the stylesheet**

Create `static/css/study-mode.css`:

```css
/* ════════════════════════════════════════════════════════════
   Study Mode — proband-facing view
   Editorial language matching base.css + recording.css
   ════════════════════════════════════════════════════════════ */

.rec-study-view {
  margin-top: 24px;
}

.rec-study-stage {
  position: relative;
  background: oklch(0.97 0.008 80);
  border: 1px solid oklch(0.88 0.012 80);
  border-radius: 12px;
  min-height: 440px;
  overflow: hidden;
}

/* ── Pre-task screen ─────────────────────────────────────── */
.study-pre-task {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 440px;
  padding: 40px;
  position: relative;
  text-align: center;
}
.study-pre-task::before {
  content: '/';
  position: absolute;
  top: -50px; right: -30px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 320px;
  color: rgba(0,0,0,0.04);
  font-weight: 700;
  line-height: 1;
  pointer-events: none;
}
.study-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: oklch(0.45 0.018 58);
  letter-spacing: 0.2em;
  text-transform: lowercase;
  margin-bottom: 12px;
}
.study-title-big {
  font-family: 'Inter', sans-serif;
  font-size: 56px;
  font-weight: 600;
  line-height: 1.05;
  color: oklch(0.2 0.025 55);
  margin-bottom: 24px;
}
.study-instruction {
  font-family: 'Inter', sans-serif;
  font-size: 15px;
  color: oklch(0.45 0.018 58);
  margin-bottom: 32px;
  max-width: 540px;
  line-height: 1.45;
}
.study-timer-big {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 96px;
  font-weight: 300;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  color: oklch(0.2 0.025 55);
  /* Transition smooths the visual shrink as new frames replace this element.
     A proper FLIP animation between pre_task → running can be added later. */
  transition: font-size 320ms cubic-bezier(0.4, 0, 0.2, 1);
}
.study-hint {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: oklch(0.55 0.018 58);
  margin-top: 16px;
}

/* ── Running view (timer in topbar) ──────────────────────── */
.study-running {
  display: flex;
  flex-direction: column;
  min-height: 440px;
  position: relative;
}
.study-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 28px;
  border-bottom: 1px solid oklch(0.88 0.012 80);
  background: oklch(0.93 0.012 80);
  font-family: 'IBM Plex Mono', monospace;
  flex-shrink: 0;
}
.study-topbar-left { display: flex; gap: 10px; align-items: baseline; }
.study-topbar-title { font-size: 14px; font-weight: 600; color: oklch(0.2 0.025 55); }
.study-topbar-right { display: flex; align-items: center; gap: 14px; }
.study-progress {
  width: 110px;
  height: 4px;
  background: oklch(0.88 0.012 80);
  border-radius: 2px;
  overflow: hidden;
}
.study-progress-fill {
  height: 100%;
  background: oklch(0.595 0.165 43);
  transition: width 400ms linear;
}
.study-timer-small {
  font-size: 22px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  color: oklch(0.2 0.025 55);
}
.study-content-area {
  flex: 1;
  padding: 36px 44px;
  font-family: 'Inter', sans-serif;
  position: relative;
}
.study-content-area::before {
  content: '/';
  position: absolute;
  top: -40px; right: -20px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 260px;
  color: rgba(0,0,0,0.03);
  font-weight: 700;
  line-height: 1;
  pointer-events: none;
}
.study-instruction-small {
  font-size: 13px;
  color: oklch(0.55 0.018 58);
  margin-bottom: 20px;
  font-family: 'IBM Plex Mono', monospace;
}
.study-content-text {
  font-size: 22px;
  line-height: 1.7;
  color: oklch(0.2 0.025 55);
  max-width: 780px;
}
.study-content-list {
  font-size: 22px;
  line-height: 1.85;
  color: oklch(0.2 0.025 55);
  padding-left: 1.5em;
}
.study-content-list li { margin-bottom: 12px; }

/* ── Paused state ────────────────────────────────────────── */
.study-running.is-paused .study-timer-small {
  animation: study-pulse 1.2s ease-in-out infinite;
}
.study-paused-overlay {
  position: absolute;
  inset: 0;
  background: oklch(0.97 0.008 80 / 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 18px;
  color: oklch(0.595 0.165 43);
  text-transform: lowercase;
  letter-spacing: 0.1em;
}
@keyframes study-pulse {
  0%, 100% { color: oklch(0.2 0.025 55); }
  50%       { color: oklch(0.595 0.165 43); }
}

/* ── Done screen ─────────────────────────────────────────── */
.study-done {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 440px;
  text-align: center;
  font-family: 'Inter', sans-serif;
}
.study-done-glyph { font-size: 96px; color: oklch(0.580 0.130 148); margin-bottom: 16px; }
.study-done-title { font-size: 32px; font-weight: 600; color: oklch(0.2 0.025 55); margin-bottom: 12px; }
.study-done-hint  { font-size: 14px; color: oklch(0.45 0.018 58); }

/* ── VL override panel ───────────────────────────────────── */
.study-vl-panel {
  position: absolute;
  bottom: 16px;
  right: 16px;
  display: flex;
  gap: 6px;
  padding: 6px;
  background: oklch(0.97 0.008 80);
  border: 1px solid oklch(0.85 0.012 80);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.study-vl-btn {
  appearance: none;
  border: 0;
  background: transparent;
  width: 32px;
  height: 32px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
  color: oklch(0.35 0.018 58);
  transition: background 120ms ease;
}
.study-vl-btn:hover { background: oklch(0.92 0.012 80); }
.study-vl-btn--danger { color: oklch(0.55 0.18 25); }
.study-vl-btn--danger:hover { background: oklch(0.95 0.04 25); }
```

- [ ] **Step 2: Link the stylesheet from `dashboard.html`**

Open `dashboard.html`. In the `<head>` section, find the line that loads `static/css/recording.css` (or the cluster of `<link rel="stylesheet">` tags). Add immediately after it:

```html
<link rel="stylesheet" href="/static/css/study-mode.css">
```

- [ ] **Step 3: Run the static-asset test**

Run: `pytest tests/test_dashboard_static.py -v`
Expected: all paths reachable (including the new CSS and the new JS).

- [ ] **Step 4: Commit**

```bash
git add static/css/study-mode.css dashboard.html
git commit -m "feat(study): editorial styles for proband view + VL panel"
```

---

# Phase D · ML pipeline integration (light)

## Task 13: Optional asof-attach of markers in merge.py

**Files:**
- Modify: `src/merge/merge.py`
- Modify: `tests/test_merge.py`

- [ ] **Step 1: Write the failing regression test**

In `tests/test_merge.py`, add a new test at the bottom. Keep all existing tests as they are.

```python
def test_merge_attaches_task_id_when_markers_exist(tmp_path, monkeypatch):
    """If data/raw/markers/{session}_markers.csv exists, merge attaches
    task_id + task_category to each watch sample in the active interval."""
    import csv
    import pandas as pd

    from src.merge import merge as merge_mod

    # Layout: redirect both raw + processed paths into tmp_path.
    sid = "S777"
    raw_watch = tmp_path / "raw" / "watch"
    raw_pen   = tmp_path / "raw" / "pen"
    raw_mk    = tmp_path / "raw" / "markers"
    proc      = tmp_path / "processed"
    for d in (raw_watch, raw_pen, raw_mk, proc):
        d.mkdir(parents=True)
    monkeypatch.setattr(merge_mod, "DATA_RAW_WATCH", raw_watch, raising=False)
    monkeypatch.setattr(merge_mod, "DATA_RAW_PEN",   raw_pen,   raising=False)
    monkeypatch.setattr(merge_mod, "DATA_PROCESSED", proc,      raising=False)
    # The marker lookup uses Path(__file__).parents[2] / "data" / "raw" / "markers";
    # bend it to point at our tmp dir for this test.
    monkeypatch.setattr(merge_mod, "_MARKERS_DIR_OVERRIDE", raw_mk, raising=False)

    # 1 s of watch samples at 50 Hz starting at local_ts_ms = 1_000_000
    watch_rows = []
    for i in range(50):
        watch_rows.append({
            "local_ts": "x", "local_ts_ms": 1_000_000 + i * 20,
            "session_id": sid, "sequence": i, "sample_rate_hz": 50,
            "watch_sent_at": "", "phone_received_at": "",
            "server_received_ms": 1_000_000 + i * 20, "source": "test",
            "ts": i * 20, "ax": 0.1, "ay": 0.1, "az": 0.1,
            "rx": 0.0, "ry": 0.0, "rz": 0.0,
        })
    watch_df = pd.DataFrame(watch_rows)
    watch_df.to_csv(raw_watch / f"{sid}_watch.csv", index=False)

    # Pen with one PEN_DOWN early
    pen_df = pd.DataFrame([{
        "local_ts": "x", "local_ts_ms": 1_000_050, "timestamp": 0,
        "x": 10, "y": 10, "pressure": 1, "dot_type": "PEN_DOWN",
        "tilt_x": 0, "tilt_y": 0, "section": 0, "owner": 0, "note": 0, "page": 1,
    }])
    pen_df.to_csv(raw_pen / f"{sid}_pen.csv", index=False)

    # Markers: task_start at sample 0, task_end at sample 25.
    with open(raw_mk / f"{sid}_markers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp_ms", "event", "task_id", "task_name",
            "task_index", "task_category", "protocol_id",
        ])
        w.writeheader()
        w.writerow({"timestamp_ms": 1_000_000, "event": "task_start",
                    "task_id": "abschreiben", "task_name": "Text",
                    "task_index": 1, "task_category": "writing",
                    "protocol_id": "v1"})
        w.writerow({"timestamp_ms": 1_000_500, "event": "task_end",
                    "task_id": "abschreiben", "task_name": "Text",
                    "task_index": 1, "task_category": "writing",
                    "protocol_id": "v1"})

    merged = merge_mod.merge_watch_pen(sid)
    assert "task_id" in merged.columns
    # First 25 samples cover [1_000_000, 1_000_500) → task active.
    assert merged.iloc[0]["task_id"] == "abschreiben"
    assert merged.iloc[24]["task_id"] == "abschreiben"
    # Sample 25 onward: NaN (task ended).
    assert pd.isna(merged.iloc[25]["task_id"])


def test_merge_no_markers_keeps_columns_absent(tmp_path, monkeypatch):
    """Backwards-compat: sessions without a markers CSV merge unchanged."""
    import pandas as pd
    from src.merge import merge as merge_mod

    sid = "S778"
    raw_watch = tmp_path / "raw" / "watch"
    raw_pen   = tmp_path / "raw" / "pen"
    raw_mk    = tmp_path / "raw" / "markers"
    proc      = tmp_path / "processed"
    for d in (raw_watch, raw_pen, raw_mk, proc):
        d.mkdir(parents=True)
    monkeypatch.setattr(merge_mod, "DATA_RAW_WATCH", raw_watch, raising=False)
    monkeypatch.setattr(merge_mod, "DATA_RAW_PEN",   raw_pen,   raising=False)
    monkeypatch.setattr(merge_mod, "DATA_PROCESSED", proc,      raising=False)
    monkeypatch.setattr(merge_mod, "_MARKERS_DIR_OVERRIDE", raw_mk, raising=False)

    # Minimal watch + pen, no markers file.
    pd.DataFrame([{
        "local_ts": "x", "local_ts_ms": 1_000_000, "session_id": sid,
        "sequence": 0, "sample_rate_hz": 50, "watch_sent_at": "",
        "phone_received_at": "", "server_received_ms": 1_000_000,
        "source": "test", "ts": 0, "ax": 0.1, "ay": 0.1, "az": 0.1,
        "rx": 0, "ry": 0, "rz": 0,
    }]).to_csv(raw_watch / f"{sid}_watch.csv", index=False)
    pd.DataFrame([{
        "local_ts": "x", "local_ts_ms": 1_000_000, "timestamp": 0,
        "x": -1, "y": -1, "pressure": 0, "dot_type": "PEN_HOVER",
        "tilt_x": 0, "tilt_y": 0, "section": 0, "owner": 0, "note": 0, "page": 1,
    }]).to_csv(raw_pen / f"{sid}_pen.csv", index=False)

    merged = merge_mod.merge_watch_pen(sid)
    # Either: column absent, or all-NaN. Both are valid backward-compat.
    if "task_id" in merged.columns:
        assert merged["task_id"].isna().all()
```

- [ ] **Step 2: Extend `merge_watch_pen`**

In `src/merge/merge.py`, near the top of the module, add the marker dir resolver. If the file already has `DATA_PROCESSED` / `DATA_RAW_*` constants at the top, place this with them:

```python
from pathlib import Path as _Path

# Override hook for tests; production resolves to data/raw/markers.
_MARKERS_DIR_OVERRIDE: _Path | None = None


def _markers_dir() -> _Path:
    if _MARKERS_DIR_OVERRIDE is not None:
        return _MARKERS_DIR_OVERRIDE
    return _Path(__file__).parents[2] / "data" / "raw" / "markers"
```

In the `merge_watch_pen(session_id, ...)` function, just before the final `return merged` line, add:

```python
    # Attach task markers if a markers CSV exists for this session.
    # Sessions captured before Study Mode get no task_id columns — downstream
    # code treats absent columns as NaN.
    markers_path = _markers_dir() / f"{session_id}_markers.csv"
    if markers_path.exists():
        import pandas as _pd
        markers = _pd.read_csv(markers_path)
        boundaries = markers[markers["event"].isin(
            ["task_start", "task_end", "abort", "study_end"]
        )].copy()
        boundaries["timestamp_ms"] = boundaries["timestamp_ms"].astype("int64")
        boundaries = boundaries.sort_values("timestamp_ms").reset_index(drop=True)

        intervals: list[dict] = []
        active: dict | None = None
        for _, row in boundaries.iterrows():
            if row["event"] == "task_start":
                active = {
                    "start": int(row["timestamp_ms"]),
                    "task_id": row.get("task_id", ""),
                    "task_category": row.get("task_category", ""),
                }
            elif row["event"] in ("task_end", "abort", "study_end") and active is not None:
                active["end"] = int(row["timestamp_ms"])
                intervals.append(active)
                active = None

        merged["task_id"] = _pd.NA
        merged["task_category"] = _pd.NA
        for iv in intervals:
            mask = (merged["local_ts_ms"] >= iv["start"]) & (merged["local_ts_ms"] < iv["end"])
            merged.loc[mask, "task_id"] = iv["task_id"]
            merged.loc[mask, "task_category"] = iv["task_category"]
```

- [ ] **Step 3: Run all merge tests**

Run: `pytest tests/test_merge.py -v`
Expected: all prior tests pass + 2 new tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/merge/merge.py tests/test_merge.py
git commit -m "feat(merge): asof-attach task markers when markers CSV present"
```

---

## Task 14: Window-level task_id propagation in features

**Files:**
- Modify: `src/features/windows.py`

- [ ] **Step 1: Add window-level mode aggregation**

In `src/features/windows.py`, locate `build_windows()`. Inside the per-window loop where features and the label are added to the `row` dict, append (still inside the loop body):

```python
        # Task metadata propagated from merged CSV if present.
        # Use the mode of task_id within the window; ties resolve to first.
        if "task_id" in window.columns:
            tid_series = window["task_id"].dropna()
            if not tid_series.empty:
                row["task_id"] = tid_series.mode().iat[0]
                if "task_category" in window.columns:
                    cat_series = window["task_category"].dropna()
                    if not cat_series.empty:
                        row["task_category"] = cat_series.mode().iat[0]
```

If `window` is the per-window slice — confirm by reading the surrounding code; the variable name may differ (e.g., `chunk`). Adapt the variable name accordingly. Do not introduce `task_id` into the row when `window["task_id"]` is entirely NaN — leaving the key absent keeps backward-compat for legacy sessions.

- [ ] **Step 2: Smoke-check with an existing session**

Run:

```bash
python -m src.features S029
```

Then:

```bash
head -1 data/processed/S029_windows.csv | tr ',' '\n' | grep task_id || echo "no task_id column (expected for S029)"
```

Expected: `no task_id column (expected for S029)`. S029 was captured before Study Mode existed; the column legitimately doesn't appear.

- [ ] **Step 3: Commit**

```bash
git add src/features/windows.py
git commit -m "feat(features): propagate task_id per window when markers present"
```

---

# Phase E · Final wiring + smoke

## Task 15: End-to-end smoke test + gitignore

**Files:**
- Create: `tests/test_study_e2e.py`
- Modify: `.gitignore`

- [ ] **Step 1: Update `.gitignore`**

Open `.gitignore` and append:

```
data/raw/markers/
.superpowers/
```

- [ ] **Step 2: Write the smoke test**

Create `tests/test_study_e2e.py`:

```python
"""End-to-end: /study/start writes markers, status payload exposes state."""
from __future__ import annotations

import csv

from fastapi.testclient import TestClient


def test_full_study_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.server.csv_io.MARKERS_DIR", tmp_path / "markers")
    (tmp_path / "markers").mkdir()
    from server import app
    client = TestClient(app)

    r = client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST",
        "description": "e2e", "force_preflight": True,
    })
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    # Force several transitions
    client.post("/study/next")
    client.post("/study/next")
    client.post("/study/abort")
    client.post("/session/stop")

    markers_path = tmp_path / "markers" / f"{sid}_markers.csv"
    assert markers_path.exists(), "markers CSV should be written"
    events = [r["event"] for r in csv.DictReader(markers_path.open())]
    for required in ("study_start", "task_start", "task_end", "abort", "study_end"):
        assert required in events, f"missing {required!r} in {events}"
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -q`
Expected: all green.

- [ ] **Step 4: Manual UI verification**

```bash
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000`:

1. Switch to study mode → protocol dropdown shows `ML4SCS Study Protocol v1`, START label says `START STUDY`.
2. Click START STUDY. The proband view appears with task 1's pre-task screen (centered title + large countdown).
3. After 3 s, pre-task transitions to running (timer is now top-right, task content fills the page).
4. Press `Space` → "Paused — VL override" overlay appears, timer pulses orange.
5. Press `Space` again → resumes.
6. Press `→` → advances to next task (back to pre-task screen for slot 2).
7. Press `Esc` → aborts. The view reverts to the regular free-recording surface (chart + pen canvas visible again).
8. Click STOP to end the session.
9. Inspect `data/raw/markers/{session}_markers.csv` → should contain `study_start`, `task_start`/`task_end` pairs, `pause`/`resume`, `abort`, `study_end` with monotonic `timestamp_ms` values.

- [ ] **Step 5: Commit**

```bash
git add tests/test_study_e2e.py .gitignore
git commit -m "test(study): end-to-end smoke + ignore markers & brainstorm dirs"
```

---

# Self-review against the spec

**Spec coverage:**
- ✅ Section 3 (architecture, server-side state machine) — Phases A + B
- ✅ Section 4.1–4.3 (server module, state, routes) — Tasks 1–8
- ✅ Section 4.4 (status payload `study` field) — Task 6
- ✅ Section 5.1 (toggle pattern) — Tasks 9, 10
- ✅ Section 5.2 (study view sub-states) — Task 11
- ✅ Section 5.3 (animation) — Task 12 (CSS `transition` between layouts; a more precise FLIP animation can be layered on later in `recording-study.js` between `replaceChildren` calls if visual polish requires it)
- ✅ Section 5.4 (VL panel + keyboard shortcuts) — Task 11
- ✅ Section 6 (protocol JSON, randomization) — Tasks 2, 3, 5
- ✅ Section 7 (marker CSV format) — Task 1
- ✅ Section 8 (ML pipeline light) — Tasks 13, 14
- ✅ Section 9 (testing) — embedded in every backend task plus Task 15 e2e

**Placeholder scan:** No "TBD" / "TODO" remain.

**Type consistency:** `StudyTask`, `StudyProtocol`, `StudyRuntime`, `ScheduledSlot`, `build_schedule`, `new_runtime`, `load_protocol`, `list_protocols`, `write_marker`, `MARKERS_DIR`, `MARKER_FIELDNAMES`, `setRecMode`, `studyCmd`, `renderStudyView` — names referenced consistently across tasks.
