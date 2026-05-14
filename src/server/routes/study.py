"""FastAPI routes for Study Mode."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from ..config import ROOT
from ..csv_io import _subject_index_for_person_id, write_marker
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
    from fastapi.responses import JSONResponse
    session_info = await _start_session_internal(
        person_id=body.person_id,
        description=body.description or f"study:{protocol.id}",
        force_preflight=body.force_preflight,
    )
    # _start_session_internal returns JSONResponse on preflight blocker/warn
    # or already-active conflict — surface those unchanged.
    if isinstance(session_info, JSONResponse) or "session_id" not in session_info:
        return session_info

    subject_index = _subject_index_for_person_id(body.person_id)
    rt = new_runtime(
        protocol,
        session_info["session_id"],
        started_at_ms=_now_ms(),
        subject_index=subject_index,
    )
    state.study = rt

    return {
        "session_id": session_info["session_id"],
        "protocol": {"id": protocol.id, "name": protocol.name},
        "subject_index": subject_index,
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
