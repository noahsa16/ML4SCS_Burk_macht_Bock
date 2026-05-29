"""Watch-Endpunkte: Heartbeat, manuelle Befehle, IMU-Datenempfang."""

import json
import math
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..broadcast import _broadcast
from ..config import DATA_RAW_WATCH
from ..csv_io import get_watch_writer
from ..inference import live
from ..models import WatchEnvelope
from ..state import state
from ..utils import _now_ms, _round_or_none, _safe_file_id, _utc_iso_from_ms
from ._helpers import _new_command_id

router = APIRouter()


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
            "gx":  s.gx,
            "gy":  s.gy,
            "gz":  s.gz,
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

        if s.ts is not None and None not in (s.ax, s.ay, s.az, s.rx, s.ry, s.rz):
            live.append_sample(s.ts, s.ax, s.ay, s.az, s.rx, s.ry, s.rz,
                               s.gx, s.gy, s.gz)

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
            "gx": _round_or_none(s.gx),
            "gy": _round_or_none(s.gy),
            "gz": _round_or_none(s.gz),
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
