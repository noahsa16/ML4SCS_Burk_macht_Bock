"""
CSV-Lesen und -Schreiben für Watch, Pen und Sessions.

Alle Dateioperationen (außer dem eigentlichen Watch-Empfang in routes.py)
laufen hier durch. Schreibt bei Bedarf ins state.event_log via state.append_event().
"""

import csv
from pathlib import Path
from typing import Any, Optional

from .config import (
    DATA_RAW_PEN, DATA_RAW_WATCH, SESSIONS_CSV, SESSIONS_FIELDNAMES,
    WATCH_FIELDNAMES,
)
from .state import state
from .utils import _as_float, _as_int, _utc_iso_from_ms


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

    state.append_event("server", "warn", f"Migrated CSV schema for {path.name}", {
        "added_columns": [c for c in fieldnames if c not in existing],
    })
    return False


def _next_session_id() -> str:
    _ensure_csv_header(SESSIONS_CSV, SESSIONS_FIELDNAMES)
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
            return max(0, sum(1 for _ in f) - 1)
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


def _update_session_row(session_id: str, updates: dict):
    _ensure_csv_header(SESSIONS_CSV, SESSIONS_FIELDNAMES)
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


def _read_session_rows() -> list[dict[str, str]]:
    _ensure_csv_header(SESSIONS_CSV, SESSIONS_FIELDNAMES)
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
