"""
Alle FastAPI-Endpunkte als APIRouter.

Wird in server.py in die App eingebunden. Die Route-Handler selbst
sind möglichst dünn — die eigentliche Logik steckt in den anderen Modulen.
"""

import csv
import dataclasses
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

log = logging.getLogger("server.routes")
from fastapi.responses import FileResponse, JSONResponse

from .broadcast import _broadcast
from pydantic import ValidationError

from .models import AirPodsEnvelope, SessionStartBody, WatchEnvelope
from .config import (
    DASHBOARD_HTML, DATA_RAW_AIRPODS, DATA_RAW_WATCH, SESSIONS_CSV,
    SESSIONS_FIELDNAMES, WATCH_FIELDNAMES,
)
from .csv_io import (
    _airpods_sample_count, _ensure_csv_header, _next_session_id,
    _pen_sample_count, _read_session_rows, _update_session_row,
    close_airpods_writer, close_watch_writer, get_airpods_writer,
    get_watch_writer,
)
from .pen_proc import _start_pen, _stop_pen
from .quality import (
    _session_quality, _session_validation,
    _session_report, _session_report_markdown,
)
from fastapi.responses import Response
from .state import ActiveSession, state
from .status import _status_payload
from .utils import _now_ms, _round_or_none, _safe_file_id, _utc_iso_from_ms

router = APIRouter()


def _new_command_id(command: str, session_id: str | None = None) -> str:
    scope = _safe_file_id(session_id or "manual")
    return f"{command}-{scope}-{uuid.uuid4().hex[:8]}"


def _session_preflight_payload() -> dict:
    status = _status_payload()
    blockers = []
    warnings = []

    if not status.get("watch_bridge_connected"):
        blockers.append({
            "code": "iphone_bridge_missing",
            "message": "iPhone bridge WebSocket is not connected.",
        })
    if not status.get("watch_polling"):
        blockers.append({
            "code": "watch_not_polling",
            "message": "Apple Watch has not polled the iPhone bridge recently.",
        })
    if not status.get("pen_connected"):
        warnings.append({
            "code": "pen_disconnected",
            "message": "Smart Pen logger is not connected; the session can start, but pen data will be missing.",
        })

    compact_status = {
        "session_active": status.get("session_active"),
        "watch_bridge_connected": status.get("watch_bridge_connected"),
        "watch_polling": status.get("watch_polling"),
        "watch_poll_age_ms": status.get("watch_poll_age_ms"),
        "watch_reachable": status.get("watch_reachable"),
        "watch_running": status.get("watch_running"),
        "watch_command": status.get("watch_command"),
        "iphone_connected": status.get("watch_bridge_connected"),
        "pen_connected": status.get("pen_connected"),
        "pen_pid": status.get("pen_pid"),
        "connected_clients": status.get("connected_clients"),
    }
    return {
        "ok": not blockers and not warnings,
        "can_start": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "status": compact_status,
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/")
async def dashboard():
    # no-store verhindert, dass der Browser die Dashboard-HTML cached.
    # CSS/Markup-Änderungen erscheinen damit beim nächsten normalen Reload,
    # ohne dass wir ständig Cache-Buster ans <script src> hängen müssen.
    return FileResponse(
        DASHBOARD_HTML,
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


# ── Watch-Heartbeat und Status ────────────────────────────────────────────────

@router.get("/watch/ping")
async def watch_ping(request: Request):
    """
    Leichtgewichtiger Endpunkt, den die Watch alle 2 s abfragt.
    Kein CSV-Lesen — nur In-Memory-State zurückgeben.
    """
    state.last_watch_status_time = time.time()
    return {
        "session_active": state.active is not None,
        "session_id": state.active.session_id if state.active else None,
        "person_id": state.active.person_id if state.active else None,
        "description": state.active.description if state.active else None,
    }


@router.get("/status")
async def get_status(request: Request):
    return _status_payload()


@router.get("/session/preflight")
async def session_preflight():
    return _session_preflight_payload()


@router.get("/debug/package")
async def debug_package():
    status = _status_payload()
    return {
        "version": "debug_package_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preflight": _session_preflight_payload(),
        "status": status,
        "active_session": dataclasses.asdict(state.active) if state.active else None,
        "watch_command": state.watch_command,
        "connected_clients": list(state.ws_client_meta.values()),
        "recent_events": list(state.event_log)[-200:],
        "recent_samples": list(state.sample_log)[-200:],
        "recent_sessions": list(reversed(_read_session_rows()))[:20],
    }


# ── Sessions ──────────────────────────────────────────────────────────────────

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


# ── Pen-Steuerung ─────────────────────────────────────────────────────────────

@router.post("/pen/connect")
async def pen_connect():
    if state.pen_proc and state.pen_proc.returncode is None:
        return JSONResponse({"error": "Pen already running"}, status_code=409)
    session_id = state.active.session_id if state.active else "unsessioned"
    result = await _start_pen(session_id)
    if "ok" in result:
        return result
    return JSONResponse({"error": result["error"]}, status_code=500)


@router.post("/pen/disconnect")
async def pen_disconnect():
    await _stop_pen()
    return {"ok": True}


# ── Watch-Befehle ─────────────────────────────────────────────────────────────

@router.post("/watch/start")
async def watch_cmd_start():
    sid = state.active.session_id if state.active else None
    pid = state.active.person_id if state.active else "manual"
    command_id = _new_command_id("start", sid)
    state.watch_command = {
        "command": "start",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual start command broadcast",
        "session_id": sid,
        "command_id": command_id,
    }
    state.append_event("watch", "info", "Manual start command broadcast", {
        "session_id": sid,
        "command_id": command_id,
    })
    await _broadcast({
        "type": "start",
        "session_id": sid,
        "person_id": pid,
        "command_id": command_id,
    })
    return {"ok": True, "command_id": command_id}


@router.post("/watch/stop")
async def watch_cmd_stop():
    sid = state.active.session_id if state.active else None
    command_id = _new_command_id("stop", sid)
    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual stop command broadcast",
        "session_id": sid,
        "command_id": command_id,
    }
    state.append_event("watch", "info", "Manual stop command broadcast", {
        "session_id": sid,
        "command_id": command_id,
    })
    await _broadcast({"type": "stop", "session_id": sid, "command_id": command_id})
    return {"ok": True, "command_id": command_id}


# ── Watch-Daten empfangen ─────────────────────────────────────────────────────

@router.post("/watch")
async def receive_watch(request: Request):
    """
    Empfängt einen Batch von IMU-Samples von der Watch (via iPhone-Bridge oder direkt).
    Unterstützt sowohl das Envelope-Format {samples: [...], ...} als auch rohe Listen.
    """
    try:
        raw = await request.json()
    except (json.JSONDecodeError, ValueError):
        state.append_event("watch", "error", "Invalid JSON payload")
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    try:
        envelope = WatchEnvelope.model_validate(raw)
    except ValidationError as exc:
        state.append_event("watch", "error", "Watch payload validation failed")
        return JSONResponse({"error": "Invalid watch payload", "detail": exc.errors()}, status_code=422)

    session_id = (
        state.active.session_id if state.active
        else (envelope.sessionId or "unsessioned")
    )
    session_id = _safe_file_id(session_id)
    csv_path = DATA_RAW_WATCH / f"{session_id}_watch.csv"

    server_received_ms = _now_ms()
    local_ts = _utc_iso_from_ms(server_received_ms)
    state.last_watch_time = time.time()
    state.watch_config_rate_hz = envelope.sampleRateHz or state.watch_config_rate_hz

    # Sequenzlücken erkennen und zählen
    seq = envelope.sequence
    if seq is not None:
        if (
            state.watch_sequence_last is not None
            and seq > state.watch_sequence_last + 1
        ):
            gap = seq - state.watch_sequence_last - 1
            state.watch_sequence_gaps += gap
            state.append_event("watch", "warn", "Watch sequence gap detected", {
                "expected": state.watch_sequence_last + 1,
                "received": seq,
                "gap": gap,
            })
        state.watch_sequence_last = seq

    watch_sent_at = envelope.watchSentAt
    phone_received_at = envelope.phoneReceivedAt
    state.watch_phone_latency_ms = (
        phone_received_at - watch_sent_at
        if phone_received_at is not None and watch_sent_at is not None
        else None
    )
    state.watch_server_latency_ms = (
        server_received_ms - phone_received_at
        if phone_received_at is not None
        else None
    )

    valid_count = 0
    first_ts = None
    last_ts = None
    last_sample = None

    w = get_watch_writer(csv_path)
    for s in envelope.samples:
        if s.ts is not None:
            first_ts = s.ts if first_ts is None else first_ts
            last_ts = s.ts

        w.writerow({
            "local_ts":           local_ts,
            "local_ts_ms":        server_received_ms,
            "session_id":         session_id,
            "sequence":           envelope.sequence,
            "sample_rate_hz":     envelope.sampleRateHz,
            "watch_sent_at":      envelope.watchSentAt,
            "phone_received_at":  envelope.phoneReceivedAt,
            "server_received_ms": server_received_ms,
            "source":             envelope.source,
            "ts":  s.ts,
            "ax":  s.ax,
            "ay":  s.ay,
            "az":  s.az,
            "rx":  s.rx,
            "ry":  s.ry,
            "rz":  s.rz,
        })
        valid_count += 1

        acc_mag = (
            math.sqrt(s.ax * s.ax + s.ay * s.ay + s.az * s.az)
            if None not in (s.ax, s.ay, s.az) else None
        )
        gyro_mag = (
            math.sqrt(s.rx * s.rx + s.ry * s.ry + s.rz * s.rz)
            if None not in (s.rx, s.ry, s.rz) else None
        )
        if acc_mag is not None:
            state.chart_window_acc_mags.append(acc_mag)
        if gyro_mag is not None:
            state.chart_window_gyro_mags.append(gyro_mag)

        last_sample = {
            "session_id": session_id,
            "sequence": seq,
            "ts": s.ts,
            "ax": _round_or_none(s.ax),
            "ay": _round_or_none(s.ay),
            "az": _round_or_none(s.az),
            "rx": _round_or_none(s.rx),
            "ry": _round_or_none(s.ry),
            "rz": _round_or_none(s.rz),
            "acc_mag": _round_or_none(acc_mag),
            "gyro_mag": _round_or_none(gyro_mag),
            "server_received_ms": server_received_ms,
        }
        state.append_sample("watch", last_sample)

    # Batch-Samplerate aus internen Watch-Timestamps berechnen
    if first_ts is not None and last_ts is not None and valid_count > 1 and last_ts > first_ts:
        state.watch_batch_rate_hz = (valid_count - 1) * 1000 / (last_ts - first_ts)
    if last_ts is not None:
        state.watch_clock_skew_ms = server_received_ms - last_ts

    state.watch_total_sample_count += valid_count
    if last_sample:
        state.last_watch_sample = last_sample
    state.last_watch_packet = {
        "session_id": session_id,
        "sequence": seq,
        "samples": valid_count,
        "source": envelope.source,
        "sample_rate_hz": state.watch_config_rate_hz,
        "server_received_ms": server_received_ms,
        "watch_sent_at": watch_sent_at,
        "phone_received_at": phone_received_at,
    }

    if state.active:
        state.watch_sample_count += valid_count

    return {
        "ok": True,
        "samples": valid_count,
        "session_active": state.active is not None,
        "session_id": state.active.session_id if state.active else None,
    }


# ── AirPods-Befehle ───────────────────────────────────────────────────────────

@router.post("/airpods/start")
async def airpods_cmd_start():
    sid = state.active.session_id if state.active else None
    pid = state.active.person_id if state.active else "manual"
    command_id = _new_command_id("airpods_start", sid)
    state.airpods_command = {
        "command": "start",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual AirPods start command broadcast",
        "session_id": sid,
        "command_id": command_id,
    }
    state.append_event("airpods", "info", "Manual AirPods start command broadcast", {
        "session_id": sid,
        "command_id": command_id,
    })
    await _broadcast({
        "type": "airpods_start",
        "session_id": sid,
        "person_id": pid,
        "command_id": command_id,
    })
    return {"ok": True, "command_id": command_id}


@router.post("/airpods/stop")
async def airpods_cmd_stop():
    sid = state.active.session_id if state.active else None
    command_id = _new_command_id("airpods_stop", sid)
    state.airpods_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual AirPods stop command broadcast",
        "session_id": sid,
        "command_id": command_id,
    }
    state.append_event("airpods", "info", "Manual AirPods stop command broadcast", {
        "session_id": sid,
        "command_id": command_id,
    })
    await _broadcast({"type": "airpods_stop", "session_id": sid, "command_id": command_id})
    return {"ok": True, "command_id": command_id}


@router.get("/airpods/ping")
async def airpods_ping():
    """Lightweight liveness/control endpoint analogous to /watch/ping."""
    return {
        "session_active": state.active is not None,
        "session_id": state.active.session_id if state.active else None,
        "person_id": state.active.person_id if state.active else None,
        "description": state.active.description if state.active else None,
    }


# ── AirPods-Daten empfangen ───────────────────────────────────────────────────

@router.post("/airpods")
async def receive_airpods(request: Request):
    """
    Empfängt einen Batch von Head-Motion-Samples (CMHeadphoneMotionManager,
    typischerweise 25 Hz) von der iPhone-Bridge.
    Akzeptiert sowohl `{samples: [...]}` als auch eine rohe Liste.
    """
    try:
        raw = await request.json()
    except (json.JSONDecodeError, ValueError):
        state.append_event("airpods", "error", "Invalid JSON payload")
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    try:
        envelope = AirPodsEnvelope.model_validate(raw)
    except ValidationError as exc:
        state.append_event("airpods", "error", "AirPods payload validation failed")
        return JSONResponse({"error": "Invalid AirPods payload", "detail": exc.errors()}, status_code=422)

    session_id = (
        state.active.session_id if state.active
        else (envelope.sessionId or "unsessioned")
    )
    session_id = _safe_file_id(session_id)
    csv_path = DATA_RAW_AIRPODS / f"{session_id}_airpods.csv"

    server_received_ms = _now_ms()
    local_ts = _utc_iso_from_ms(server_received_ms)
    state.last_airpods_time = time.time()
    state.airpods_config_rate_hz = envelope.sampleRateHz or state.airpods_config_rate_hz

    seq = envelope.sequence
    if seq is not None:
        if (
            state.airpods_sequence_last is not None
            and seq > state.airpods_sequence_last + 1
        ):
            gap = seq - state.airpods_sequence_last - 1
            state.airpods_sequence_gaps += gap
            state.append_event("airpods", "warn", "AirPods sequence gap detected", {
                "expected": state.airpods_sequence_last + 1,
                "received": seq,
                "gap": gap,
            })
        state.airpods_sequence_last = seq

    sent_at = envelope.airpodsSentAt
    phone_received_at = envelope.phoneReceivedAt
    state.airpods_phone_latency_ms = (
        phone_received_at - sent_at
        if phone_received_at is not None and sent_at is not None
        else None
    )
    state.airpods_server_latency_ms = (
        server_received_ms - phone_received_at
        if phone_received_at is not None
        else None
    )

    valid_count = 0
    first_ts = None
    last_ts = None
    last_sample = None

    w = get_airpods_writer(csv_path)
    for s in envelope.samples:
        if s.ts is not None:
            first_ts = s.ts if first_ts is None else first_ts
            last_ts = s.ts

        w.writerow({
            "local_ts":           local_ts,
            "local_ts_ms":        server_received_ms,
            "session_id":         session_id,
            "sequence":           envelope.sequence,
            "sample_rate_hz":     envelope.sampleRateHz,
            "airpods_sent_at":    envelope.airpodsSentAt,
            "phone_received_at":  envelope.phoneReceivedAt,
            "server_received_ms": server_received_ms,
            "source":             envelope.source,
            "ts": s.ts,
            "ax": s.ax, "ay": s.ay, "az": s.az,
            "rx": s.rx, "ry": s.ry, "rz": s.rz,
            "qw": s.qw, "qx": s.qx, "qy": s.qy, "qz": s.qz,
            "gx": s.gx, "gy": s.gy, "gz": s.gz,
        })
        valid_count += 1

        acc_mag = (
            math.sqrt(s.ax * s.ax + s.ay * s.ay + s.az * s.az)
            if None not in (s.ax, s.ay, s.az) else None
        )
        gyro_mag = (
            math.sqrt(s.rx * s.rx + s.ry * s.ry + s.rz * s.rz)
            if None not in (s.rx, s.ry, s.rz) else None
        )

        last_sample = {
            "session_id": session_id,
            "sequence": seq,
            "ts": s.ts,
            "ax": _round_or_none(s.ax),
            "ay": _round_or_none(s.ay),
            "az": _round_or_none(s.az),
            "rx": _round_or_none(s.rx),
            "ry": _round_or_none(s.ry),
            "rz": _round_or_none(s.rz),
            "qw": _round_or_none(s.qw),
            "qx": _round_or_none(s.qx),
            "qy": _round_or_none(s.qy),
            "qz": _round_or_none(s.qz),
            "acc_mag": _round_or_none(acc_mag),
            "gyro_mag": _round_or_none(gyro_mag),
            "server_received_ms": server_received_ms,
        }
        state.append_sample("airpods", last_sample)

    if first_ts is not None and last_ts is not None and valid_count > 1 and last_ts > first_ts:
        state.airpods_batch_rate_hz = (valid_count - 1) * 1000 / (last_ts - first_ts)
    if last_ts is not None:
        state.airpods_clock_skew_ms = server_received_ms - last_ts

    state.airpods_total_sample_count += valid_count
    if last_sample:
        state.last_airpods_sample = last_sample
    state.last_airpods_packet = {
        "session_id": session_id,
        "sequence": seq,
        "samples": valid_count,
        "source": envelope.source,
        "sample_rate_hz": state.airpods_config_rate_hz,
        "server_received_ms": server_received_ms,
        "airpods_sent_at": sent_at,
        "phone_received_at": phone_received_at,
    }

    if state.active:
        state.airpods_sample_count += valid_count

    return {
        "ok": True,
        "samples": valid_count,
        "session_active": state.active is not None,
        "session_id": state.active.session_id if state.active else None,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

def _handle_ws_client_message(ws_id: int, text: str) -> None:
    """
    Verarbeitet eine eingehende WS-Nachricht. Unterstützte Typen:
      - 'hello': Client identifiziert sich (dashboard, iphone, watch_bridge)
      - 'watch_ack': Watch bestätigt einen Befehl
      - 'phone_status': iPhone-Bridge meldet Watch-Erreichbarkeit
    """
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return
    if not isinstance(msg, dict):
        return

    msg_type = msg.get("type")
    if msg_type == "hello":
        client = str(msg.get("client") or "unknown")
        state.ws_client_meta.setdefault(ws_id, {})["client"] = client
        state.ws_client_meta[ws_id]["last_seen_ms"] = _now_ms()
        if client in {"iphone", "watch_bridge"}:
            state.append_event("phone", "info", "iPhone bridge WebSocket connected")
        return

    state.ws_client_meta.setdefault(ws_id, {})["last_seen_ms"] = _now_ms()

    if msg_type == "watch_ack":
        ok = bool(msg.get("ok"))
        command_id = msg.get("command_id")
        state.watch_command = {
            "command": msg.get("command"),
            "ok": ok,
            "at": _now_ms(),
            "detail": msg.get("detail") or ("Watch acknowledged command" if ok else "Watch command failed"),
            "session_id": msg.get("session_id"),
            "command_id": command_id,
            "reply": msg.get("reply"),
        }
        state.append_event("watch", "info" if ok else "error", state.watch_command["detail"], {
            "command": msg.get("command"),
            "session_id": msg.get("session_id"),
            "command_id": command_id,
        })
    elif msg_type == "phone_status":
        state.ws_client_meta.setdefault(ws_id, {})["phone_status"] = msg


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_id = id(websocket)
    peer = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
    state.ws_clients.add(websocket)
    state.ws_client_meta[ws_id] = {
        "client": "unknown",
        "connected_at_ms": _now_ms(),
        "last_seen_ms": _now_ms(),
        "peer": peer,
    }
    log.info("WS accepted ws_id=%s peer=%s", ws_id, peer)
    close_reason = "unknown"
    try:
        while True:
            text = await websocket.receive_text()
            _handle_ws_client_message(ws_id, text)
    except WebSocketDisconnect as e:
        close_reason = f"disconnect code={e.code}"
    except Exception:
        close_reason = "exception"
        log.exception("WS handler exception ws_id=%s peer=%s", ws_id, peer)
    finally:
        meta = state.ws_client_meta.pop(ws_id, {})
        client = meta.get("client", "unknown")
        connected_ms = _now_ms() - int(meta.get("connected_at_ms") or _now_ms())
        log.info("WS closed ws_id=%s peer=%s client=%s lived_ms=%s reason=%s",
                 ws_id, peer, client, connected_ms, close_reason)
        if client in {"iphone", "watch_bridge"}:
            state.append_event(
                "phone", "warn",
                f"iPhone bridge WebSocket disconnected ({close_reason}, lived {connected_ms} ms)",
            )
        state.ws_clients.discard(websocket)
