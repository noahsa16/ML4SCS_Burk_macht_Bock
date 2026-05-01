"""
Verbindungsstatus und Status-Payload-Builder.

_pen_connected(), _watch_connected() etc. sind die zentralen Checks die
im Dashboard und in den Broadcasts verwendet werden.
_status_payload() baut das große JSON das jede Sekunde an alle WS-Clients geht.
"""

import time
from typing import Any, Optional

from .csv_io import _pen_last_dot, _pen_sample_count
from .state import state
from .utils import _now_ms, _round_or_none


def _pen_connected() -> bool:
    return state.pen_proc is not None and state.pen_proc.returncode is None


def _watch_connected() -> bool:
    return (time.time() - state.last_watch_time) < 5.0 if state.last_watch_time else False


def _watch_direct_status_connected() -> bool:
    return (
        (time.time() - state.last_watch_status_time) < 5.0
        if state.last_watch_status_time else False
    )


def _watch_bridge_connected() -> bool:
    return any(
        meta.get("client") in {"iphone", "watch_bridge"}
        for meta in state.ws_client_meta.values()
    )


def _watch_reachable() -> Optional[bool]:
    statuses = [
        meta.get("phone_status")
        for meta in state.ws_client_meta.values()
        if meta.get("client") in {"iphone", "watch_bridge"} and meta.get("phone_status")
    ]
    if not statuses:
        return None
    return any(bool(status.get("watch_reachable")) for status in statuses)


def _connected_clients() -> dict[str, int]:
    counts: dict[str, int] = {}
    for meta in state.ws_client_meta.values():
        client = meta.get("client", "unknown")
        counts[client] = counts.get(client, 0) + 1
    return counts


def _validation_payload(last_pen_dot: Optional[dict[str, Any]]) -> dict[str, Any]:
    watch = state.last_watch_sample or {}
    has_accel = all(watch.get(k) is not None for k in ("ax", "ay", "az"))
    has_gyro = all(watch.get(k) is not None for k in ("rx", "ry", "rz"))
    has_pen_server_time = bool(last_pen_dot and last_pen_dot.get("has_server_time"))
    return {
        "watch_has_accelerometer": has_accel,
        "watch_has_gyroscope": has_gyro,
        "pen_has_server_time": has_pen_server_time,
        "clock_alignment": (
            "ok" if has_pen_server_time else
            "legacy_pen_csv_missing_server_time"
        ),
        "watch_sequence_gaps": state.watch_sequence_gaps,
    }


def _status_payload(
    *,
    pen_samples: Optional[int] = None,
    last_pen_dot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    sid = state.active["session_id"] if state.active else None
    if pen_samples is None:
        pen_samples = _pen_sample_count(sid) if sid else 0
    if last_pen_dot is None and sid:
        last_pen_dot = _pen_last_dot(sid)

    pen_connected = _pen_connected()
    pen_writing = (
        last_pen_dot.get("dot_type") in ("PEN_DOWN", "PEN_MOVE")
        if last_pen_dot else False
    )
    pen_seen_ms = None
    if last_pen_dot and last_pen_dot.get("local_ts_ms"):
        pen_seen_ms = max(0, _now_ms() - int(last_pen_dot["local_ts_ms"]))

    watch_seen_ms = None
    if state.last_watch_time:
        watch_seen_ms = max(0, int((time.time() - state.last_watch_time) * 1000))

    watch_stream_active = _watch_connected()
    watch_direct_connected = _watch_direct_status_connected()
    watch_bridge_connected = _watch_bridge_connected()
    watch_reachable = _watch_reachable()

    return {
        "type": "status",
        "session_active": state.active is not None,
        "session_id": sid,
        "person_id": state.active["person_id"] if state.active else None,
        "description": state.active.get("description") if state.active else None,
        "start_time": state.active["start_time"] if state.active else None,
        "watch_samples": state.watch_sample_count,
        "watch_total_samples": state.watch_total_sample_count,
        "pen_samples": pen_samples,
        "pen_connected": pen_connected,
        "pen_session_id": state.pen_session_id,
        "pen_pid": state.pen_proc.pid if pen_connected else None,
        "pen_rate_hz": round(state.pen_rate_hz, 1),
        "pen_writing": pen_writing,
        "pen_last_dot": last_pen_dot,
        "pen_last_seen_ms_ago": pen_seen_ms,
        "watch_connected": watch_stream_active or watch_direct_connected or watch_reachable is True,
        "watch_direct_connected": watch_direct_connected,
        "watch_stream_active": watch_stream_active,
        "watch_bridge_connected": watch_bridge_connected,
        "watch_reachable": watch_reachable,
        "watch_rate_hz": round(state.watch_rate_hz, 1),
        "watch_config_rate_hz": _round_or_none(state.watch_config_rate_hz, 1),
        "watch_batch_rate_hz": _round_or_none(state.watch_batch_rate_hz, 1),
        "watch_last_seen_ms_ago": watch_seen_ms,
        "watch_last_sample": state.last_watch_sample,
        "watch_last_packet": state.last_watch_packet,
        "watch_sequence": state.watch_sequence_last,
        "watch_sequence_gaps": state.watch_sequence_gaps,
        "watch_phone_latency_ms": state.watch_phone_latency_ms,
        "watch_server_latency_ms": state.watch_server_latency_ms,
        "watch_clock_skew_ms": state.watch_clock_skew_ms,
        "watch_command": state.watch_command,
        "connected_clients": _connected_clients(),
        "uptime_seconds": int(time.time() - state.server_start),
        "chart": state.chart_buffer[-60:],
        "event_log": list(state.event_log)[-80:],
        "sample_log": list(state.sample_log)[-80:],
        "validation": _validation_payload(last_pen_dot),
    }
