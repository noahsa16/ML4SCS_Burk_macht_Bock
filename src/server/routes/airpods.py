"""AirPods-Endpunkte: Heartbeat, manuelle Befehle, Head-Motion-Datenempfang."""

import json
import math
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..broadcast import _broadcast
from ..config import DATA_RAW_AIRPODS
from ..csv_io import get_airpods_writer
from ..models import AirPodsEnvelope
from ..state import state
from ..utils import _now_ms, _round_or_none, _safe_file_id, _utc_iso_from_ms
from ._helpers import _new_command_id

router = APIRouter()


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
