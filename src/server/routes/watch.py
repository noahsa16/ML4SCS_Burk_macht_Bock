"""Watch-Endpunkte: Heartbeat, manuelle Befehle, IMU-Datenempfang."""

import json
import math
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..broadcast import _broadcast
from ..config import DATA_RAW_WATCH
from ..csv_io import flush_watch_writer, get_watch_writer
from ..inference import live
from ..models import WatchEnvelope
from ..state import state
from ..utils import _now_ms, _round_or_none, _safe_file_id, _utc_iso_from_ms
from ._helpers import _new_command_id

# Why: gleiche Toleranz wie data_outside_session_window und der Merge-Filter.
# Die Watch-`ts` ist NTP-nah (<100 ms Skew) — 60 s sind 600-fach überdimensio-
# niert, damit ein Uhren-Wackler niemals echte Samples verwirft.
_PRE_SESSION_TOL_MS = 60_000

# Why: Untergrenze für "das ist plausibel eine Epoch-Millisekunden-Zeit"
# (1e12 ms = 2001-09-09). Der Guard unten urteilt NUR über solche Werte.
# Läge `ts` je in einer anderen Einheit — Uptime-Zähler, Sekunden statt ms,
# geänderte Firmware — sähe jedes Sample "vor dem Session-Start" aus und eine
# komplette Aufnahme verschwände still in der Quarantäne. Lieber einen Spill
# durchlassen (der Merge-Filter fängt ihn) als eine echte Session verlieren.
_TS_EPOCH_MS_FLOOR = 1_000_000_000_000


def _is_pre_session_batch(envelope: WatchEnvelope, active) -> bool:
    """True, wenn der GESAMTE Batch vor dem Session-Start aufgenommen wurde.

    Kriterium ist das jüngste Sample: sobald ein einziges im Session-Fenster
    liegt, ist es ein Live-Batch und wird normal einsortiert. Bei fehlender
    oder unlesbarer ``start_time`` — oder wenn ``ts`` keine Epoch-ms-Zeit ist —
    wird nichts quarantänisiert; der Guard darf im Zweifel keine echten Daten
    aus der Session drängen.
    """
    from datetime import datetime

    ts_values = [s.ts for s in envelope.samples if s.ts is not None]
    if not ts_values:
        return False
    newest = max(ts_values)
    if newest < _TS_EPOCH_MS_FLOOR:
        return False
    try:
        start_ms = datetime.fromisoformat(active.start_time).timestamp() * 1000
    except (AttributeError, TypeError, ValueError):
        return False
    return newest < start_ms - _PRE_SESSION_TOL_MS

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

    # Why: ohne aktive Session NIEMALS an die vom iPhone gemeldete (= zuletzt
    # gestreamte) Session anhängen — die Bridge behält die alte ID im Speicher
    # und schiebt beim Reconnect (z.B. am nächsten Morgen) verwaiste Samples
    # nach, die sonst still an eine längst gestoppte Session-CSV angehängt
    # würden. Stattdessen in einen Quarantäne-Bucket schreiben.
    #
    # Derselbe Bucket fängt Spill-Nachlieferungen WÄHREND einer laufenden
    # Session: die Watch puffert bei Verbindungsproblemen auf Disk und liefert
    # beim nächsten Connect nach. Solche Batches tragen eine Capture-`ts` von
    # vor dem Session-Start, aber der Server stempelt die aktive Session auf
    # jeden Batch — so kamen 8.925 fremde Samples (davon 4.651 aus der
    # abgebrochenen S092) in S093.
    session_id = (
        state.active.session_id
        if state.active and not _is_pre_session_batch(envelope, state.active)
        else "unsessioned"
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
            "qx":  s.qx,
            "qy":  s.qy,
            "qz":  s.qz,
            "qw":  s.qw,
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

    # Server-ACK-Persistenz: den Batch auf OS-Ebene durchschreiben, BEVOR die 200
    # zurückgeht. Das iPhone löscht seine Kopie auf diese ACK hin — ohne Flush
    # lägen die Zeilen bis zum Buffer-Füllen im Prozess-Puffer und ein
    # Server-Neustart dazwischen verlöre den bereits bestätigten Batch.
    flush_watch_writer(csv_path)

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
