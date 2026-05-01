"""
Alle FastAPI-Endpunkte als APIRouter.

Wird in server.py in die App eingebunden. Die Route-Handler selbst
sind möglichst dünn — die eigentliche Logik steckt in den anderen Modulen.
"""

import csv
import json
import math
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from .broadcast import _broadcast
from .config import (
    DASHBOARD_HTML, DATA_RAW_WATCH, SESSIONS_CSV, SESSIONS_FIELDNAMES,
    WATCH_FIELDNAMES,
)
from .csv_io import (
    _ensure_csv_header, _next_session_id, _pen_sample_count,
    _read_session_rows, _update_session_row,
)
from .pen_proc import _start_pen, _stop_pen
from .quality import _session_quality, _session_validation
from .state import state
from .status import _status_payload
from .utils import _as_float, _as_int, _now_ms, _round_or_none, _safe_file_id, _utc_iso_from_ms

router = APIRouter()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/")
async def dashboard():
    return FileResponse(DASHBOARD_HTML)


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
        "session_id": state.active["session_id"] if state.active else None,
        "person_id": state.active["person_id"] if state.active else None,
        "description": state.active.get("description") if state.active else None,
    }


@router.get("/status")
async def get_status(request: Request):
    if request.headers.get("x-focustrack-client") == "watch_direct":
        state.last_watch_status_time = time.time()
    return _status_payload()


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


@router.post("/session/start")
async def session_start(request: Request):
    if state.active:
        return JSONResponse({"error": "Session already active"}, status_code=409)

    try:
        body = await request.json()
    except Exception:
        body = {}
    person_id = str(body.get("person_id", "unknown")).strip() or "unknown"
    description = str(body.get("description", "")).strip()
    session_id = _next_session_id()
    start_time = datetime.now(timezone.utc).isoformat()

    state.active = {
        "session_id": session_id,
        "person_id": person_id,
        "description": description,
        "start_time": start_time,
    }
    state.watch_sample_count = 0
    state.chart_buffer = []
    state.chart_window_acc_mags = []
    state.chart_window_gyro_mags = []
    state.last_watch_sample = None
    state.last_watch_packet = None
    state.watch_sequence_last = None
    state.watch_sequence_gaps = 0
    state.watch_phone_latency_ms = None
    state.watch_server_latency_ms = None
    state.watch_clock_skew_ms = None
    state.last_pen_dot = None
    state.last_pen_log_key = None
    state.sample_log.clear()
    state.watch_command = {
        "command": "start",
        "ok": None,
        "at": _now_ms(),
        "detail": "Start command broadcast to iPhone bridge",
        "session_id": session_id,
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
            "status": "active",
        })

    # Falls der Pen noch mit "unsessioned" läuft, neu starten unter der richtigen Session-ID
    if state.pen_proc and state.pen_proc.returncode is None and state.pen_session_id == "unsessioned":
        await _stop_pen()
        await _start_pen(session_id)

    state.append_event("session", "info", f"Session {session_id} started", {
        "person_id": person_id,
        "description": description,
    })
    await _broadcast({
        "type": "start",
        "session_id": session_id,
        "person_id": person_id,
        "description": description,
    })
    return {"session_id": session_id, "person_id": person_id, "description": description}


@router.post("/session/stop")
async def session_stop():
    if not state.active:
        return JSONResponse({"error": "No active session"}, status_code=409)

    session_id = state.active["session_id"]
    end_time = datetime.now(timezone.utc).isoformat()

    # Session sofort deaktivieren, damit die Watch beim nächsten Poll aufhört zu senden
    state.active = None

    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Stop command broadcast to iPhone bridge",
        "session_id": session_id,
    }
    state.append_event("session", "info", f"Stop requested for {session_id}", {
        "session_id": session_id,
    })
    await _broadcast({"type": "stop", "session_id": session_id})

    await _stop_pen()

    pen_samples = _pen_sample_count(session_id)
    watch_samples = state.watch_sample_count

    _update_session_row(session_id, {
        "end_time": end_time,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "status": "completed",
    })

    state.append_event("session", "info", f"Session {session_id} finalized", {
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
    })
    return {"session_id": session_id, "pen_samples": pen_samples, "watch_samples": watch_samples}


# ── Pen-Steuerung ─────────────────────────────────────────────────────────────

@router.post("/pen/connect")
async def pen_connect():
    if state.pen_proc and state.pen_proc.returncode is None:
        return JSONResponse({"error": "Pen already running"}, status_code=409)
    session_id = state.active["session_id"] if state.active else "unsessioned"
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
    sid = state.active["session_id"] if state.active else None
    pid = state.active["person_id"] if state.active else "manual"
    state.watch_command = {
        "command": "start",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual start command broadcast",
        "session_id": sid,
    }
    state.append_event("watch", "info", "Manual start command broadcast", {"session_id": sid})
    await _broadcast({"type": "start", "session_id": sid, "person_id": pid})
    return {"ok": True}


@router.post("/watch/stop")
async def watch_cmd_stop():
    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual stop command broadcast",
        "session_id": state.active["session_id"] if state.active else None,
    }
    state.append_event("watch", "info", "Manual stop command broadcast")
    await _broadcast({"type": "stop", "session_id": None})
    return {"ok": True}


# ── Watch-Daten empfangen ─────────────────────────────────────────────────────

@router.post("/watch")
async def receive_watch(request: Request):
    """
    Empfängt einen Batch von IMU-Samples von der Watch (via iPhone-Bridge oder direkt).
    Unterstützt sowohl das Envelope-Format {samples: [...], ...} als auch rohe Listen.
    """
    try:
        payload = await request.json()
    except Exception:
        state.append_event("watch", "error", "Invalid JSON payload")
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    if isinstance(payload, list):
        envelope, batch = {}, payload
    elif isinstance(payload, dict):
        envelope = payload
        batch = envelope.get("samples", [])
    else:
        state.append_event("watch", "error", "Payload must be an object or a sample list")
        return JSONResponse({"error": "Payload must be an object or a sample list"}, status_code=422)

    if not isinstance(batch, list):
        state.append_event("watch", "error", "Watch payload missing samples list")
        return JSONResponse({"error": "Payload field 'samples' must be a list"}, status_code=422)

    session_id = (
        state.active["session_id"] if state.active
        else envelope.get("sessionId", "unsessioned")
    )
    session_id = _safe_file_id(session_id)
    csv_path = DATA_RAW_WATCH / f"{session_id}_watch.csv"

    server_received_ms = _now_ms()
    local_ts = _utc_iso_from_ms(server_received_ms)
    state.last_watch_time = time.time()
    state.watch_config_rate_hz = _as_float(envelope.get("sampleRateHz")) or state.watch_config_rate_hz

    # Sequenzlücken erkennen und zählen
    seq = _as_int(envelope.get("sequence"))
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

    watch_sent_at = _as_int(envelope.get("watchSentAt"))
    phone_received_at = _as_int(envelope.get("phoneReceivedAt"))
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
    invalid_count = 0
    first_ts = None
    last_ts = None
    last_sample = None

    _ensure_csv_header(csv_path, WATCH_FIELDNAMES)
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WATCH_FIELDNAMES)
        for s in batch:
            if not isinstance(s, dict):
                invalid_count += 1
                continue

            sample_ts = _as_int(s.get("ts"))
            if sample_ts is not None:
                first_ts = sample_ts if first_ts is None else first_ts
                last_ts = sample_ts

            w.writerow({
                "local_ts":           local_ts,
                "local_ts_ms":        server_received_ms,
                "session_id":         session_id,
                "sequence":           envelope.get("sequence"),
                "sample_rate_hz":     envelope.get("sampleRateHz"),
                "watch_sent_at":      envelope.get("watchSentAt"),
                "phone_received_at":  envelope.get("phoneReceivedAt"),
                "server_received_ms": server_received_ms,
                "source":             envelope.get("source"),
                "ts":  s.get("ts"),
                "ax":  s.get("ax"),
                "ay":  s.get("ay"),
                "az":  s.get("az"),
                "rx":  s.get("rx"),
                "ry":  s.get("ry"),
                "rz":  s.get("rz"),
            })
            valid_count += 1

            ax = _as_float(s.get("ax"))
            ay = _as_float(s.get("ay"))
            az = _as_float(s.get("az"))
            rx = _as_float(s.get("rx"))
            ry = _as_float(s.get("ry"))
            rz = _as_float(s.get("rz"))
            acc_mag = (
                math.sqrt(ax * ax + ay * ay + az * az)
                if None not in (ax, ay, az) else None
            )
            gyro_mag = (
                math.sqrt(rx * rx + ry * ry + rz * rz)
                if None not in (rx, ry, rz) else None
            )
            if acc_mag is not None:
                state.chart_window_acc_mags.append(acc_mag)
            if gyro_mag is not None:
                state.chart_window_gyro_mags.append(gyro_mag)

            last_sample = {
                "session_id": session_id,
                "sequence": seq,
                "ts": sample_ts,
                "ax": _round_or_none(ax),
                "ay": _round_or_none(ay),
                "az": _round_or_none(az),
                "rx": _round_or_none(rx),
                "ry": _round_or_none(ry),
                "rz": _round_or_none(rz),
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
        "invalid_samples": invalid_count,
        "source": envelope.get("source"),
        "sample_rate_hz": state.watch_config_rate_hz,
        "server_received_ms": server_received_ms,
        "watch_sent_at": watch_sent_at,
        "phone_received_at": phone_received_at,
    }

    if invalid_count:
        state.append_event("watch", "warn", "Dropped invalid watch sample(s)", {
            "invalid_samples": invalid_count,
            "sequence": seq,
        })

    if state.active:
        state.watch_sample_count += valid_count

    return {
        "ok": True,
        "samples": valid_count,
        "invalid_samples": invalid_count,
        "session_active": state.active is not None,
        "session_id": state.active["session_id"] if state.active else None,
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
        state.watch_command = {
            "command": msg.get("command"),
            "ok": ok,
            "at": _now_ms(),
            "detail": msg.get("detail") or ("Watch acknowledged command" if ok else "Watch command failed"),
            "session_id": msg.get("session_id"),
            "reply": msg.get("reply"),
        }
        state.append_event("watch", "info" if ok else "error", state.watch_command["detail"], {
            "command": msg.get("command"),
            "session_id": msg.get("session_id"),
        })
    elif msg_type == "phone_status":
        state.ws_client_meta.setdefault(ws_id, {})["phone_status"] = msg


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_id = id(websocket)
    state.ws_clients.add(websocket)
    state.ws_client_meta[ws_id] = {
        "client": "unknown",
        "connected_at_ms": _now_ms(),
        "last_seen_ms": _now_ms(),
    }
    try:
        while True:
            text = await websocket.receive_text()
            _handle_ws_client_message(ws_id, text)
    except WebSocketDisconnect:
        pass
    finally:
        meta = state.ws_client_meta.pop(ws_id, {})
        if meta.get("client") in {"iphone", "watch_bridge"}:
            state.append_event("phone", "warn", "iPhone bridge WebSocket disconnected")
        state.ws_clients.discard(websocket)
