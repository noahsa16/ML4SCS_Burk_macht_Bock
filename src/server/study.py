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
