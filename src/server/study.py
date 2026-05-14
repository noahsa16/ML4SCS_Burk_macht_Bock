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
