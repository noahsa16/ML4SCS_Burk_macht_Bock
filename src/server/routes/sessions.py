"""Session-Lifecycle und -Quality (start, stop, list, quality, validation, report)."""

import csv
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from ..broadcast import _broadcast
from ..config import (
    DATA_RAW_AIRPODS, DATA_RAW_WATCH, SESSIONS_CSV, SESSIONS_FIELDNAMES,
)
from ..csv_io import (
    _ensure_csv_header, _next_session_id, _pen_sample_count,
    _read_session_rows, _update_session_row,
    close_airpods_writer, close_watch_writer,
)
from ..models import SessionStartBody
from ..pen_proc import _start_pen, _stop_pen
from ..quality import (
    _session_quality, _session_validation,
    _session_report, _session_report_markdown,
)
from ..state import ActiveSession, state
from ..utils import _now_ms
from ._helpers import _new_command_id, _session_preflight_payload

router = APIRouter()


@router.get("/sessions")
async def get_sessions():
    return list(reversed(_read_session_rows()))


@router.get("/sessions/quality")
async def get_session_quality():
    rows = _read_session_rows()
    reports = [_session_quality(row) for row in rows]
    def _summary_for(key: str) -> dict[str, int]:
        return {
            "ok": sum(1 for r in reports if r.get(key, {}).get("status") == "ok"),
            "warn": sum(1 for r in reports if r.get(key, {}).get("status") == "warn"),
            "bad": sum(1 for r in reports if r.get(key, {}).get("status") == "bad"),
        }
    ml_summary = _summary_for("ml_readiness")
    recording_summary = _summary_for("recording_health")
    summary = {
        "total": len(reports),
        # Backward-compatible aliases for older dashboard code: ML readiness.
        "ok": ml_summary["ok"],
        "warn": ml_summary["warn"],
        "bad": ml_summary["bad"],
        "ml_readiness": ml_summary,
        "recording_health": recording_summary,
    }
    return {
        "summary": summary,
        "sessions": list(reversed(reports)),
    }


@router.get("/sessions/{session_id}/validation")
async def get_session_validation(session_id: str):
    result = _session_validation(session_id)
    if any(issue["code"].endswith("missing_or_unreadable") for issue in result["issues"]):
        return JSONResponse(result, status_code=404)
    return result


@router.get("/sessions/{session_id}/report")
async def get_session_report(session_id: str, format: str = "json"):
    """Pro-Session-Report — JSON oder Markdown.

    `?format=md` liefert Markdown als Download (`session_<id>_report.md`).
    """
    rows = _read_session_rows()
    row = next((r for r in rows if r.get("session_id") == session_id), None)
    if row is None:
        return JSONResponse({"error": f"Session {session_id} not found"}, status_code=404)
    report = _session_report(row)
    if format.lower() in ("md", "markdown"):
        body = _session_report_markdown(report)
        filename = f"session_{session_id}_report.md"
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return report


@router.post("/session/start")
async def session_start(body: SessionStartBody = SessionStartBody()):
    if state.active:
        return JSONResponse({"error": "Session already active"}, status_code=409)

    person_id = body.person_id
    description = body.description
    force_preflight = body.force_preflight
    preflight = _session_preflight_payload()
    if preflight["blockers"]:
        return JSONResponse({
            "error": "Preflight blocked session start",
            "preflight": preflight,
        }, status_code=428)
    if preflight["warnings"] and not force_preflight:
        return JSONResponse({
            "error": "Preflight warning",
            "preflight": preflight,
        }, status_code=428)

    session_id = _next_session_id()
    start_time = datetime.now(timezone.utc).isoformat()
    command_id = _new_command_id("start", session_id)

    state.reset_for_session()
    state.active = ActiveSession(
        session_id=session_id,
        person_id=person_id,
        description=description,
        start_time=start_time,
    )
    state.watch_command = {
        "command": "start",
        "ok": None,
        "at": _now_ms(),
        "detail": "Start command broadcast to iPhone bridge",
        "session_id": session_id,
        "command_id": command_id,
    }

    _ensure_csv_header(SESSIONS_CSV, SESSIONS_FIELDNAMES)
    with open(SESSIONS_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow({
            "session_id": session_id,
            "person_id": person_id,
            "description": description,
            "start_time": start_time,
            "end_time": "",
            "pen_samples": 0,
            "watch_samples": 0,
            "airpods_samples": 0,
            "status": "active",
        })

    # Falls der Pen noch mit "unsessioned" läuft, neu starten unter der richtigen Session-ID
    if state.pen_proc and state.pen_proc.returncode is None and state.pen_session_id == "unsessioned":
        await _stop_pen()
        await _start_pen(session_id)

    state.append_event("session", "info", f"Session {session_id} started", {
        "person_id": person_id,
        "description": description,
        "command_id": command_id,
    })
    await _broadcast({
        "type": "start",
        "session_id": session_id,
        "person_id": person_id,
        "description": description,
        "command_id": command_id,
    })
    return {
        "session_id": session_id,
        "person_id": person_id,
        "description": description,
        "command_id": command_id,
        "preflight": preflight,
    }


@router.post("/session/stop")
async def session_stop():
    if not state.active:
        return JSONResponse({"error": "No active session"}, status_code=409)

    session_id = state.active.session_id
    end_time = datetime.now(timezone.utc).isoformat()
    command_id = _new_command_id("stop", session_id)

    # Session sofort deaktivieren, damit die Watch beim nächsten Poll aufhört zu senden
    state.active = None

    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Stop command broadcast to iPhone bridge",
        "session_id": session_id,
        "command_id": command_id,
    }
    state.append_event("session", "info", f"Stop requested for {session_id}", {
        "session_id": session_id,
        "command_id": command_id,
    })
    await _broadcast({"type": "stop", "session_id": session_id, "command_id": command_id})

    await _stop_pen()
    close_watch_writer(DATA_RAW_WATCH / f"{session_id}_watch.csv")
    close_airpods_writer(DATA_RAW_AIRPODS / f"{session_id}_airpods.csv")

    pen_samples = _pen_sample_count(session_id)
    watch_samples = state.watch_sample_count
    airpods_samples = state.airpods_sample_count

    _update_session_row(session_id, {
        "end_time": end_time,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
        "status": "completed",
    })

    state.append_event("session", "info", f"Session {session_id} finalized", {
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
    })
    return {
        "session_id": session_id,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
        "command_id": command_id,
    }
