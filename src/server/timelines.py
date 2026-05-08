"""
CSV → Timeline-Strukturen für Watch, Pen und AirPods.

Reine Loader / Statistik-Helfer ohne Score-Logik. Konsumiert von
``quality._session_facts``; ``_watch_peaks`` lebt absichtlich in
``sync.py`` (einziger Aufrufer), nicht hier.

Read-only: kein Zugriff auf globalen State.
"""

import csv
import math
from statistics import median
from typing import Any, Optional

from .config import DATA_RAW_AIRPODS, DATA_RAW_PEN, DATA_RAW_WATCH
from .utils import _as_float, _as_int, _mad, _row_local_ms


# ── CSV-Timeline laden ────────────────────────────────────────────────────────

def _load_watch_timeline(session_id: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    path = DATA_RAW_WATCH / f"{session_id}_watch.csv"
    if not path.exists():
        return [], f"Missing watch CSV: {path.name}"
    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                source_ts = _as_int(row.get("ts"))
                local_ts = _row_local_ms(row, "local_ts_ms", "server_received_ms")
                ax = _as_float(row.get("ax"))
                ay = _as_float(row.get("ay"))
                az = _as_float(row.get("az"))
                rx = _as_float(row.get("rx"))
                ry = _as_float(row.get("ry"))
                rz = _as_float(row.get("rz"))
                acc_mag = math.sqrt(ax*ax + ay*ay + az*az) if None not in (ax, ay, az) else None
                gyro_mag = math.sqrt(rx*rx + ry*ry + rz*rz) if None not in (rx, ry, rz) else None
                rows.append({
                    "source_ts": source_ts,
                    "local_ts": local_ts,
                    "motion_mag": (gyro_mag if gyro_mag is not None else 0.0)
                    + 0.35 * (acc_mag if acc_mag is not None else 0.0),
                    "acc_mag": acc_mag,
                    "gyro_mag": gyro_mag,
                    "sequence": _as_int(row.get("sequence")),
                    "has_accel": acc_mag is not None,
                    "has_gyro": gyro_mag is not None,
                    "has_server_ms": _as_int(row.get("server_received_ms")) is not None,
                })
    except Exception as exc:
        return [], f"Could not read watch CSV: {exc}"
    return rows, None


def _load_pen_timeline(session_id: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return [], f"Missing pen CSV: {path.name}"
    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "source_ts": _as_int(row.get("timestamp")),
                    "local_ts": _row_local_ms(row, "local_ts_ms"),
                    "dot_type": row.get("dot_type") or "",
                    "x": _as_float(row.get("x")),
                    "y": _as_float(row.get("y")),
                    "pressure": _as_int(row.get("pressure")),
                    "has_local_ts_ms": _as_int(row.get("local_ts_ms")) is not None,
                })
    except Exception as exc:
        return [], f"Could not read pen CSV: {exc}"
    return rows, None


# ── Zeitstempel-Statistiken ───────────────────────────────────────────────────

def _clock_summary(rows: list[dict[str, Any]], count_key: str) -> dict[str, Any]:
    source_values = [r["source_ts"] for r in rows if r.get("source_ts") is not None]
    local_values = [r["local_ts"] for r in rows if r.get("local_ts") is not None]
    paired_offsets = [
        r["local_ts"] - r["source_ts"]
        for r in rows
        if r.get("local_ts") is not None and r.get("source_ts") is not None
    ]
    offset_start = paired_offsets[0] if paired_offsets else None
    offset_end = paired_offsets[-1] if paired_offsets else None
    drift_ms = (
        offset_end - offset_start
        if offset_start is not None and offset_end is not None else None
    )
    return {
        "start_ms": min(local_values) if local_values else None,
        "end_ms": max(local_values) if local_values else None,
        "duration_seconds": (
            round((max(local_values) - min(local_values)) / 1000, 3)
            if len(local_values) > 1 else None
        ),
        "device_start_ms": min(source_values) if source_values else None,
        "device_end_ms": max(source_values) if source_values else None,
        "device_duration_seconds": (
            round((max(source_values) - min(source_values)) / 1000, 3)
            if len(source_values) > 1 else None
        ),
        count_key: len(rows),
        "source_start_ms": min(source_values) if source_values else None,
        "source_end_ms": max(source_values) if source_values else None,
        "source_duration_seconds": (
            round((max(source_values) - min(source_values)) / 1000, 3)
            if len(source_values) > 1 else None
        ),
        "source_to_local_offset_start_ms": offset_start,
        "source_to_local_offset_end_ms": offset_end,
        "source_to_local_drift_ms": drift_ms,
        "source_to_local_offset_median_ms": round(median(paired_offsets), 3)
        if paired_offsets else None,
        "source_to_local_offset_min_ms": min(paired_offsets) if paired_offsets else None,
        "source_to_local_offset_max_ms": max(paired_offsets) if paired_offsets else None,
        "source_to_local_offset_mad_ms": round(_mad(paired_offsets), 3)
        if paired_offsets else None,
        "rows_with_local_ts": len(local_values),
        "rows_with_source_ts": len(source_values),
    }


# ── Stift-Intervalle ──────────────────────────────────────────────────────────

def _pen_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    open_start = None
    open_local_start = None
    dot_count = 0
    for row in rows:
        dtype = row.get("dot_type")
        source_ts = row.get("source_ts")
        local_ts = row.get("local_ts")
        if dtype == "PEN_DOWN":
            open_start = source_ts
            open_local_start = local_ts
            dot_count = 1
        elif dtype in ("PEN_MOVE", "PEN_HOVER") and open_start is not None:
            dot_count += 1
        elif dtype == "PEN_UP" and open_start is not None:
            end = source_ts if source_ts is not None else open_start
            local_end = local_ts if local_ts is not None else open_local_start
            intervals.append({
                "source_start_ms": open_start,
                "source_end_ms": end,
                "local_start_ms": open_local_start,
                "local_end_ms": local_end,
                "duration_ms": max(0, end - open_start)
                if None not in (open_start, end) else None,
                "dot_count": dot_count + 1,
            })
            open_start = None
            open_local_start = None
            dot_count = 0
    return intervals


# ── AirPods (optionaler Stream) ───────────────────────────────────────────────

def _airpods_summary(session_id: str) -> dict[str, Any]:
    """Lightweight stats for the AirPods CSV — no full timeline parse.

    Returns row count, server-time row count, and overall server_received_ms
    range. Enough for coverage / legacy-time / count-mismatch issues.
    """
    path = DATA_RAW_AIRPODS / f"{session_id}_airpods.csv"
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "row_count": 0,
        "server_time_rows": 0,
        "server_ms_min": None,
        "server_ms_max": None,
        "load_error": None,
    }
    if not path.exists():
        return summary
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                summary["row_count"] += 1
                ms = _as_int(r.get("server_received_ms"))
                if ms is not None:
                    summary["server_time_rows"] += 1
                    if summary["server_ms_min"] is None or ms < summary["server_ms_min"]:
                        summary["server_ms_min"] = ms
                    if summary["server_ms_max"] is None or ms > summary["server_ms_max"]:
                        summary["server_ms_max"] = ms
    except (OSError, csv.Error) as e:
        summary["load_error"] = str(e)
    return summary
