import asyncio
import csv
import json
import math
import signal
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).parent
DATA_RAW_WATCH = ROOT / "data" / "raw" / "watch"
DATA_RAW_PEN   = ROOT / "data" / "raw" / "pen"
SESSIONS_CSV   = ROOT / "data" / "sessions.csv"
DASHBOARD_HTML = ROOT / "dashboard.html"

DATA_RAW_WATCH.mkdir(parents=True, exist_ok=True)
DATA_RAW_PEN.mkdir(parents=True, exist_ok=True)

WATCH_FIELDNAMES = [
    "local_ts", "session_id", "sequence", "sample_rate_hz",
    "watch_sent_at", "phone_received_at", "server_received_ms", "source",
    "ts", "ax", "ay", "az", "rx", "ry", "rz",
]
PEN_FIELDNAMES = [
    "local_ts", "local_ts_ms",
    "timestamp", "x", "y", "pressure", "dot_type",
    "tilt_x", "tilt_y", "section", "owner", "note", "page",
]
SESSIONS_FIELDNAMES = [
    "session_id", "person_id", "start_time", "end_time",
    "pen_samples", "watch_samples", "status",
]

if not SESSIONS_CSV.exists():
    with open(SESSIONS_CSV, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writeheader()


# ── Shared state ──────────────────────────────────────────────────────────────

class SessionState:
    def __init__(self):
        self.active: Optional[dict] = None       # {session_id, person_id, start_time}
        self.pen_proc = None                      # asyncio.subprocess.Process
        self.pen_log_task: Optional[asyncio.Task] = None
        self.pen_session_id: Optional[str] = None
        self.watch_sample_count: int = 0
        self.watch_total_sample_count: int = 0
        self.server_start: float = time.time()
        self.ws_clients: set[WebSocket] = set()
        self.ws_client_meta: dict[int, dict[str, Any]] = {}
        self.last_watch_time: float = 0.0        # for "watch connected" check
        self.chart_buffer: list[dict] = []        # [{t, acc_mag, gyro_mag, pen_writing}, ...]
        self.chart_window_acc_mags: list[float] = []
        self.chart_window_gyro_mags: list[float] = []
        self.event_log: deque[dict[str, Any]] = deque(maxlen=220)
        self.sample_log: deque[dict[str, Any]] = deque(maxlen=140)
        self.last_watch_sample: Optional[dict[str, Any]] = None
        self.last_watch_packet: Optional[dict[str, Any]] = None
        self.watch_config_rate_hz: Optional[float] = None
        self.watch_batch_rate_hz: Optional[float] = None
        self.watch_rate_hz: float = 0.0
        self.watch_sequence_last: Optional[int] = None
        self.watch_sequence_gaps: int = 0
        self.watch_phone_latency_ms: Optional[int] = None
        self.watch_server_latency_ms: Optional[int] = None
        self.watch_clock_skew_ms: Optional[int] = None
        self.last_watch_rate_check: float = time.time()
        self.last_watch_count_for_rate: int = 0
        self.last_pen_dot: Optional[dict[str, Any]] = None
        self.last_pen_log_key: Optional[tuple] = None
        self.pen_rate_hz: float = 0.0
        self.last_pen_rate_check: float = time.time()
        self.last_pen_count_for_rate: int = 0
        self.watch_command: dict[str, Any] = {
            "command": None,
            "ok": None,
            "at": None,
            "detail": "No command sent yet",
        }

state = SessionState()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _as_float(value: Any) -> Optional[float]:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        if value in ("", None):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Optional[float], digits: int = 3) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _safe_file_id(value: Any, fallback: str = "unsessioned") -> str:
    raw = str(value or fallback).strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in raw)
    return safe[:80] or fallback


def _append_event(source: str, level: str, message: str, data: Optional[dict] = None) -> None:
    entry = {
        "ts": _now_ms(),
        "source": source,
        "level": level,
        "message": message,
    }
    if data:
        entry["data"] = data
    state.event_log.append(entry)


def _append_sample(source: str, data: dict[str, Any]) -> None:
    state.sample_log.append({
        "ts": _now_ms(),
        "source": source,
        "data": data,
    })


def _ensure_csv_header(path: Path, fieldnames: list[str]) -> bool:
    """Create or migrate a CSV header before appending new rows."""
    if not path.exists() or path.stat().st_size == 0:
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        return True

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        existing = reader.fieldnames or []
        if existing == fieldnames:
            return False
        rows = list(reader)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})

    _append_event("server", "warn", f"Migrated CSV schema for {path.name}", {
        "added_columns": [c for c in fieldnames if c not in existing],
    })
    return False


# ── Session CSV helpers ───────────────────────────────────────────────────────

def _next_session_id() -> str:
    nums = []
    try:
        with open(SESSIONS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                sid = row.get("session_id", "")
                if sid.startswith("S") and sid[1:].isdigit():
                    nums.append(int(sid[1:]))
    except Exception:
        pass
    return f"S{(max(nums) + 1 if nums else 1):03d}"


def _pen_sample_count(session_id: str) -> int:
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return 0
    try:
        with open(path, newline="") as f:
            return max(0, sum(1 for _ in f) - 1)  # subtract header
    except Exception:
        return 0


def _last_csv_row(path: Path) -> Optional[dict[str, str]]:
    if not path.exists():
        return None
    try:
        last = None
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                last = row
        return last
    except Exception:
        return None


def _pen_last_dot(session_id: str) -> Optional[dict[str, Any]]:
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    row = _last_csv_row(path)
    if not row:
        return None
    local_ts_ms = _as_int(row.get("local_ts_ms"))
    return {
        "local_ts": row.get("local_ts") or (
            _utc_iso_from_ms(local_ts_ms) if local_ts_ms else None
        ),
        "local_ts_ms": local_ts_ms,
        "timestamp": _as_int(row.get("timestamp")),
        "x": _as_float(row.get("x")),
        "y": _as_float(row.get("y")),
        "pressure": _as_int(row.get("pressure")),
        "dot_type": row.get("dot_type") or "",
        "tilt_x": _as_int(row.get("tilt_x")),
        "tilt_y": _as_int(row.get("tilt_y")),
        "section": _as_int(row.get("section")),
        "owner": _as_int(row.get("owner")),
        "note": _as_int(row.get("note")),
        "page": _as_int(row.get("page")),
        "has_server_time": local_ts_ms is not None,
    }


def _pen_connected() -> bool:
    return state.pen_proc is not None and state.pen_proc.returncode is None


def _watch_connected() -> bool:
    return (time.time() - state.last_watch_time) < 5.0 if state.last_watch_time else False


def _update_session_row(session_id: str, updates: dict):
    rows = []
    try:
        with open(SESSIONS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                if row["session_id"] == session_id:
                    row.update(updates)
                rows.append(row)
    except Exception:
        return
    with open(SESSIONS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def _connected_clients() -> dict[str, int]:
    counts: dict[str, int] = {}
    for meta in state.ws_client_meta.values():
        client = meta.get("client", "unknown")
        counts[client] = counts.get(client, 0) + 1
    return counts


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_session_rows() -> list[dict[str, str]]:
    try:
        with open(SESSIONS_CSV, newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _csv_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with open(path, newline="") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def _quality_status(issues: list[dict[str, str]]) -> str:
    severities = {issue["severity"] for issue in issues}
    if "bad" in severities:
        return "bad"
    if "warn" in severities:
        return "warn"
    return "ok"


def _session_quality(row: dict[str, str]) -> dict[str, Any]:
    sid = row.get("session_id", "")
    watch_path = DATA_RAW_WATCH / f"{sid}_watch.csv"
    pen_path = DATA_RAW_PEN / f"{sid}_pen.csv"
    issues: list[dict[str, str]] = []

    watch_rows = 0
    watch_fieldnames: list[str] = []
    watch_ts_values: list[int] = []
    watch_sequences: list[int] = []
    gyro_rows = 0
    accel_rows = 0
    server_time_rows = 0

    if watch_path.exists():
        try:
            with open(watch_path, newline="") as f:
                reader = csv.DictReader(f)
                watch_fieldnames = reader.fieldnames or []
                last_seq = None
                for sample in reader:
                    watch_rows += 1
                    ts = _as_int(sample.get("ts"))
                    if ts is not None:
                        watch_ts_values.append(ts)
                    seq = _as_int(sample.get("sequence"))
                    if seq is not None and seq != last_seq:
                        watch_sequences.append(seq)
                        last_seq = seq
                    if all(_as_float(sample.get(k)) is not None for k in ("rx", "ry", "rz")):
                        gyro_rows += 1
                    if all(_as_float(sample.get(k)) is not None for k in ("ax", "ay", "az")):
                        accel_rows += 1
                    if _as_int(sample.get("server_received_ms")) is not None:
                        server_time_rows += 1
        except Exception as exc:
            issues.append({
                "code": "watch_read_error",
                "severity": "bad",
                "message": f"Could not read watch CSV: {exc}",
            })

    pen_rows = 0
    pen_fieldnames: list[str] = []
    pen_server_time_rows = 0
    pen_timestamp_years: list[int] = []

    if pen_path.exists():
        try:
            with open(pen_path, newline="") as f:
                reader = csv.DictReader(f)
                pen_fieldnames = reader.fieldnames or []
                for dot in reader:
                    pen_rows += 1
                    if _as_int(dot.get("local_ts_ms")) is not None:
                        pen_server_time_rows += 1
                    pen_ts = _as_int(dot.get("timestamp"))
                    if pen_ts:
                        try:
                            pen_timestamp_years.append(
                                datetime.fromtimestamp(pen_ts / 1000, tz=timezone.utc).year
                            )
                        except (OSError, OverflowError, ValueError):
                            pass
        except Exception as exc:
            issues.append({
                "code": "pen_read_error",
                "severity": "bad",
                "message": f"Could not read pen CSV: {exc}",
            })

    watch_diffs = [
        b - a for a, b in zip(watch_ts_values, watch_ts_values[1:])
        if b > a
    ]
    median_dt_ms = median(watch_diffs) if watch_diffs else None
    watch_est_hz = (1000 / median_dt_ms) if median_dt_ms else None

    sequence_gaps = 0
    for prev, cur in zip(watch_sequences, watch_sequences[1:]):
        if cur > prev + 1:
            sequence_gaps += cur - prev - 1

    start = _parse_iso(row.get("start_time", ""))
    end = _parse_iso(row.get("end_time", ""))
    duration_seconds = None
    expected_watch_samples = None
    if start and end and end > start:
        duration_seconds = (end - start).total_seconds()
        expected_watch_samples = int(duration_seconds * 50)

    session_watch_samples = _as_int(row.get("watch_samples")) or 0
    session_pen_samples = _as_int(row.get("pen_samples")) or 0
    is_active_session = row.get("status") == "active"

    if watch_rows == 0:
        issues.append({
            "code": "no_watch_samples",
            "severity": "bad",
            "message": "No watch samples were recorded.",
        })
    if pen_rows == 0:
        issues.append({
            "code": "no_pen_samples",
            "severity": "warn",
            "message": "No pen dots were recorded for ground truth.",
        })
    if watch_rows and gyro_rows == 0:
        issues.append({
            "code": "missing_gyroscope",
            "severity": "bad",
            "message": "Watch samples do not contain rx/ry/rz gyroscope values.",
        })
    if watch_rows and accel_rows == 0:
        issues.append({
            "code": "missing_accelerometer",
            "severity": "warn",
            "message": "Watch samples do not contain ax/ay/az accelerometer values.",
        })
    if watch_est_hz is not None and not (40 <= watch_est_hz <= 60):
        issues.append({
            "code": "watch_rate_out_of_range",
            "severity": "warn",
            "message": f"Estimated watch sample rate is {watch_est_hz:.1f} Hz.",
        })
    if sequence_gaps:
        issues.append({
            "code": "sequence_gaps",
            "severity": "warn",
            "message": f"Detected {sequence_gaps} missing watch batch sequence(s).",
        })
    if not is_active_session and watch_rows != session_watch_samples:
        issues.append({
            "code": "watch_count_mismatch",
            "severity": "warn",
            "message": f"sessions.csv has {session_watch_samples}, file has {watch_rows}.",
        })
    if not is_active_session and pen_rows != session_pen_samples:
        issues.append({
            "code": "pen_count_mismatch",
            "severity": "warn",
            "message": f"sessions.csv has {session_pen_samples}, file has {pen_rows}.",
        })
    if pen_rows and pen_server_time_rows == 0:
        issues.append({
            "code": "legacy_pen_time",
            "severity": "warn",
            "message": "Pen CSV has no local_ts_ms; align with watch only cautiously.",
        })
    if watch_rows and server_time_rows == 0:
        issues.append({
            "code": "legacy_watch_time",
            "severity": "warn",
            "message": "Watch CSV has no server_received_ms column.",
        })
    if not is_active_session and expected_watch_samples and watch_rows < expected_watch_samples * 0.7:
        issues.append({
            "code": "low_watch_coverage",
            "severity": "warn",
            "message": "Watch rows are far below duration * 50 Hz.",
        })
    if start and pen_timestamp_years and start.year not in pen_timestamp_years and pen_server_time_rows == 0:
        issues.append({
            "code": "pen_clock_mismatch",
            "severity": "bad",
            "message": "Pen internal timestamp year does not match the session year.",
        })

    return {
        "session_id": sid,
        "person_id": row.get("person_id", ""),
        "status": row.get("status", ""),
        "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        "expected_watch_samples_50hz": expected_watch_samples,
        "watch": {
            "path": str(watch_path),
            "exists": watch_path.exists(),
            "rows": watch_rows,
            "sessions_csv_rows": session_watch_samples,
            "estimated_hz": round(watch_est_hz, 2) if watch_est_hz else None,
            "median_dt_ms": round(median_dt_ms, 2) if median_dt_ms else None,
            "has_accelerometer": accel_rows > 0,
            "accelerometer_rows": accel_rows,
            "has_gyroscope": gyro_rows > 0,
            "gyroscope_rows": gyro_rows,
            "has_server_received_ms": server_time_rows > 0,
            "server_received_ms_rows": server_time_rows,
            "sequence_batches": len(watch_sequences),
            "sequence_gaps": sequence_gaps,
            "schema": watch_fieldnames,
        },
        "pen": {
            "path": str(pen_path),
            "exists": pen_path.exists(),
            "rows": pen_rows,
            "sessions_csv_rows": session_pen_samples,
            "has_server_time": pen_server_time_rows > 0,
            "server_time_rows": pen_server_time_rows,
            "timestamp_year_min": min(pen_timestamp_years) if pen_timestamp_years else None,
            "timestamp_year_max": max(pen_timestamp_years) if pen_timestamp_years else None,
            "schema": pen_fieldnames,
        },
        "issues": issues,
        "quality": _quality_status(issues),
    }


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

    return {
        "type": "status",
        "session_active": state.active is not None,
        "session_id": sid,
        "person_id": state.active["person_id"] if state.active else None,
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
        "watch_connected": _watch_connected(),
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


# ── WebSocket broadcast ───────────────────────────────────────────────────────

async def _broadcast(msg: dict):
    dead = set()
    for ws in list(state.ws_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    state.ws_clients -= dead


async def _status_loop():
    while True:
        await asyncio.sleep(1.0)
        sid = state.active["session_id"] if state.active else None
        pen_samples = _pen_sample_count(sid) if sid else 0
        last_pen_dot = _pen_last_dot(sid) if sid else None

        now = time.time()
        pen_elapsed = max(0.001, now - state.last_pen_rate_check)
        state.pen_rate_hz = max(0.0, (pen_samples - state.last_pen_count_for_rate) / pen_elapsed)
        state.last_pen_count_for_rate = pen_samples
        state.last_pen_rate_check = now

        watch_elapsed = max(0.001, now - state.last_watch_rate_check)
        state.watch_rate_hz = max(
            0.0,
            (state.watch_total_sample_count - state.last_watch_count_for_rate) / watch_elapsed,
        )
        state.last_watch_count_for_rate = state.watch_total_sample_count
        state.last_watch_rate_check = now

        if last_pen_dot:
            key = (
                last_pen_dot.get("local_ts_ms"),
                last_pen_dot.get("timestamp"),
                last_pen_dot.get("x"),
                last_pen_dot.get("y"),
                last_pen_dot.get("dot_type"),
            )
            if key != state.last_pen_log_key:
                state.last_pen_log_key = key
                state.last_pen_dot = last_pen_dot
                _append_sample("pen", {
                    "dot_type": last_pen_dot.get("dot_type"),
                    "x": last_pen_dot.get("x"),
                    "y": last_pen_dot.get("y"),
                    "pressure": last_pen_dot.get("pressure"),
                    "timestamp": last_pen_dot.get("timestamp"),
                    "local_ts_ms": last_pen_dot.get("local_ts_ms"),
                })

        pen_writing = (
            last_pen_dot.get("dot_type") in ("PEN_DOWN", "PEN_MOVE")
            if last_pen_dot else False
        )

        # Update rolling chart buffer (one point per second)
        if state.active:
            acc_mag = (
                sum(state.chart_window_acc_mags) / len(state.chart_window_acc_mags)
                if state.chart_window_acc_mags else 0.0
            )
            gyro_mag = (
                sum(state.chart_window_gyro_mags) / len(state.chart_window_gyro_mags)
                if state.chart_window_gyro_mags else 0.0
            )
            state.chart_buffer.append({
                "t": int(time.time() * 1000),
                "mag": round(acc_mag, 3),  # backward compatible key for older dashboards
                "acc_mag": round(acc_mag, 3),
                "gyro_mag": round(gyro_mag, 3),
                "pen_writing": pen_writing,
            })
            if len(state.chart_buffer) > 60:
                state.chart_buffer = state.chart_buffer[-60:]
        state.chart_window_acc_mags = []
        state.chart_window_gyro_mags = []

        await _broadcast(_status_payload(pen_samples=pen_samples, last_pen_dot=last_pen_dot))


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _append_event("server", "info", "FastAPI server started")
    task = asyncio.create_task(_status_loop())
    yield
    task.cancel()
    if state.pen_proc and state.pen_proc.returncode is None:
        state.pen_proc.send_signal(signal.SIGINT)
    if state.pen_log_task:
        state.pen_log_task.cancel()


app = FastAPI(lifespan=lifespan)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard():
    return FileResponse(DASHBOARD_HTML)


@app.get("/status")
async def get_status():
    return _status_payload()


@app.get("/sessions")
async def get_sessions():
    return list(reversed(_read_session_rows()))


@app.get("/sessions/quality")
async def get_session_quality():
    rows = _read_session_rows()
    reports = [_session_quality(row) for row in rows]
    summary = {
        "total": len(reports),
        "ok": sum(1 for r in reports if r["quality"] == "ok"),
        "warn": sum(1 for r in reports if r["quality"] == "warn"),
        "bad": sum(1 for r in reports if r["quality"] == "bad"),
    }
    return {
        "summary": summary,
        "sessions": list(reversed(reports)),
    }


@app.post("/session/start")
async def session_start(request: Request):
    if state.active:
        return JSONResponse({"error": "Session already active"}, status_code=409)

    try:
        body = await request.json()
    except Exception:
        body = {}
    person_id = str(body.get("person_id", "unknown")).strip() or "unknown"
    session_id = _next_session_id()
    start_time = datetime.now(timezone.utc).isoformat()

    state.active = {"session_id": session_id, "person_id": person_id, "start_time": start_time}
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

    with open(SESSIONS_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow({
            "session_id": session_id,
            "person_id": person_id,
            "start_time": start_time,
            "end_time": "",
            "pen_samples": 0,
            "watch_samples": 0,
            "status": "active",
        })

    if state.pen_proc and state.pen_proc.returncode is None and state.pen_session_id == "unsessioned":
        await _stop_pen()
        await _start_pen(session_id)

    _append_event("session", "info", f"Session {session_id} started", {
        "person_id": person_id,
    })
    await _broadcast({"type": "start", "session_id": session_id, "person_id": person_id})
    return {"session_id": session_id, "person_id": person_id}


@app.post("/session/stop")
async def session_stop():
    if not state.active:
        return JSONResponse({"error": "No active session"}, status_code=409)

    session_id = state.active["session_id"]
    end_time = datetime.now(timezone.utc).isoformat()

    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Stop command broadcast to iPhone bridge",
        "session_id": session_id,
    }
    _append_event("session", "info", f"Stop requested for {session_id}", {
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

    state.active = None

    _append_event("session", "info", f"Session {session_id} finalized", {
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
    })
    return {"session_id": session_id, "pen_samples": pen_samples, "watch_samples": watch_samples}


async def _stop_pen():
    if state.pen_proc and state.pen_proc.returncode is None:
        try:
            state.pen_proc.send_signal(signal.SIGINT)
            await asyncio.wait_for(state.pen_proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            state.pen_proc.kill()
            await state.pen_proc.wait()
        _append_event("pen", "info", "Pen logger stopped")
    if state.pen_log_task:
        state.pen_log_task.cancel()
        state.pen_log_task = None
    state.pen_proc = None
    state.pen_session_id = None


async def _pipe_pen_output(proc: asyncio.subprocess.Process):
    if not proc.stdout:
        return
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text:
                _append_event("pen", "info", text[:500])
    except asyncio.CancelledError:
        pass
    finally:
        if proc.returncode not in (None, 0):
            _append_event("pen", "error", f"Pen logger exited with code {proc.returncode}")


async def _start_pen(session_id: str) -> dict:
    if state.pen_proc and state.pen_proc.returncode is None:
        return {"error": "Pen already running"}
    try:
        state.pen_proc = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "pen_logger.py"), "--session", session_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        state.pen_session_id = session_id
        state.pen_log_task = asyncio.create_task(_pipe_pen_output(state.pen_proc))
        _append_event("pen", "info", "Pen logger started", {
            "session_id": session_id,
            "pid": state.pen_proc.pid,
        })
        return {"ok": True, "session_id": session_id}
    except Exception as e:
        state.pen_proc = None
        state.pen_session_id = None
        _append_event("pen", "error", "Could not start pen logger", {"error": str(e)})
        return {"error": str(e)}


@app.post("/pen/connect")
async def pen_connect():
    if state.pen_proc and state.pen_proc.returncode is None:
        return JSONResponse({"error": "Pen already running"}, status_code=409)
    session_id = state.active["session_id"] if state.active else "unsessioned"
    result = await _start_pen(session_id)
    if "ok" in result:
        return result
    return JSONResponse({"error": result["error"]}, status_code=500)


@app.post("/pen/disconnect")
async def pen_disconnect():
    await _stop_pen()
    return {"ok": True}


@app.post("/watch/start")
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
    _append_event("watch", "info", "Manual start command broadcast", {"session_id": sid})
    await _broadcast({"type": "start", "session_id": sid, "person_id": pid})
    return {"ok": True}


@app.post("/watch/stop")
async def watch_cmd_stop():
    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Manual stop command broadcast",
        "session_id": state.active["session_id"] if state.active else None,
    }
    _append_event("watch", "info", "Manual stop command broadcast")
    await _broadcast({"type": "stop", "session_id": None})
    return {"ok": True}


@app.post("/watch")
async def receive_watch(request: Request):
    try:
        payload = await request.json()
    except Exception:
        _append_event("watch", "error", "Invalid JSON payload")
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    if isinstance(payload, list):
        envelope, batch = {}, payload
    elif isinstance(payload, dict):
        envelope = payload
        batch = envelope.get("samples", [])
    else:
        _append_event("watch", "error", "Payload must be an object or a sample list")
        return JSONResponse({"error": "Payload must be an object or a sample list"}, status_code=422)

    if not isinstance(batch, list):
        _append_event("watch", "error", "Watch payload missing samples list")
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

    seq = _as_int(envelope.get("sequence"))
    if seq is not None:
        if (
            state.watch_sequence_last is not None
            and seq > state.watch_sequence_last + 1
        ):
            gap = seq - state.watch_sequence_last - 1
            state.watch_sequence_gaps += gap
            _append_event("watch", "warn", "Watch sequence gap detected", {
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
                "local_ts":          local_ts,
                "session_id":        session_id,
                "sequence":          envelope.get("sequence"),
                "sample_rate_hz":    envelope.get("sampleRateHz"),
                "watch_sent_at":     envelope.get("watchSentAt"),
                "phone_received_at": envelope.get("phoneReceivedAt"),
                "server_received_ms": server_received_ms,
                "source":            envelope.get("source"),
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
            _append_sample("watch", last_sample)

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
        _append_event("watch", "warn", "Dropped invalid watch sample(s)", {
            "invalid_samples": invalid_count,
            "sequence": seq,
        })

    if state.active:
        state.watch_sample_count += valid_count

    return {"ok": True, "samples": valid_count, "invalid_samples": invalid_count}


def _handle_ws_client_message(ws_id: int, text: str) -> None:
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
            _append_event("phone", "info", "iPhone bridge WebSocket connected")
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
        _append_event("watch", "info" if ok else "error", state.watch_command["detail"], {
            "command": msg.get("command"),
            "session_id": msg.get("session_id"),
        })
    elif msg_type == "phone_status":
        state.ws_client_meta.setdefault(ws_id, {})["phone_status"] = msg


@app.websocket("/ws")
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
            _append_event("phone", "warn", "iPhone bridge WebSocket disconnected")
        state.ws_clients.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
