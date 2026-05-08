"""
CSV-Lesen und -Schreiben für Watch, Pen und Sessions.

Alle Dateioperationen (außer dem eigentlichen Watch-Empfang in routes.py)
laufen hier durch. Schreibt bei Bedarf ins state.event_log via state.append_event().
"""

import csv
from pathlib import Path
from typing import IO, Any, Optional

from .config import (
    AIRPODS_FIELDNAMES, DATA_RAW_AIRPODS, DATA_RAW_PEN, DATA_RAW_WATCH,
    SESSIONS_CSV, SESSIONS_FIELDNAMES, WATCH_FIELDNAMES,
)
from .state import state
from .utils import _as_float, _as_int, _utc_iso_from_ms

# session_id → (file_size_bytes, raw_line_count_including_header)
_pen_count_cache: dict[str, tuple[int, int]] = {}

# csv_path (str) → (open file handle, DictWriter)
_watch_writers: dict[str, tuple[IO[str], csv.DictWriter]] = {}
_airpods_writers: dict[str, tuple[IO[str], csv.DictWriter]] = {}
_airpods_count_cache: dict[str, tuple[int, int]] = {}


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
    nums: list[int] = []
    try:
        with open(SESSIONS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                sid = row.get("session_id", "")
                if sid.startswith("S") and sid[1:].isdigit():
                    nums.append(int(sid[1:]))
    except Exception:
        pass
    # Also scan raw data folders so a stale pen/watch CSV from a prior run
    # cannot be silently re-used (would cause old dots to leak into a new session).
    for folder in (DATA_RAW_PEN, DATA_RAW_WATCH, DATA_RAW_AIRPODS):
        try:
            for p in folder.glob("S[0-9][0-9][0-9]_*.csv"):
                stem = p.stem.split("_", 1)[0]
                if stem.startswith("S") and stem[1:].isdigit():
                    nums.append(int(stem[1:]))
        except Exception:
            pass
    return f"S{(max(nums) + 1 if nums else 1):03d}"


def _pen_sample_count(session_id: str) -> int:
    """O(new bytes) per call: only counts lines appended since the last check."""
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return 0
    try:
        size = path.stat().st_size
        cached_size, cached_lines = _pen_count_cache.get(session_id, (0, 0))
        if size == cached_size:
            return max(0, cached_lines - 1)
        if size < cached_size:
            # File was truncated or rewritten — full recount
            cached_size, cached_lines = 0, 0
        with open(path, "rb") as f:
            f.seek(cached_size)
            new_lines = f.read().count(b"\n")
        total = cached_lines + new_lines
        _pen_count_cache[session_id] = (size, total)
        return max(0, total - 1)
    except Exception:
        return 0


_TAIL_CHUNK = 8192  # bytes to read from the end — enough for any realistic CSV row

def _last_csv_row(path: Path) -> Optional[dict[str, str]]:
    """O(1): reads only the header + the tail chunk to find the last data row."""
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            header_bytes = f.readline()
            fieldnames = next(csv.reader([header_bytes.decode(errors="replace")]))
            file_size = f.seek(0, 2)
            header_size = len(header_bytes)
            if file_size <= header_size:
                return None  # only header, no data rows
            f.seek(max(header_size, file_size - _TAIL_CHUNK))
            tail = f.read().decode(errors="replace")
        # Last non-empty line in the tail
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if not line:
                continue
            row = next(csv.reader([line]))
            if len(row) == len(fieldnames):
                return dict(zip(fieldnames, row))
        return None
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


def get_watch_writer(path: Path) -> csv.DictWriter:
    """Gibt einen gecachten DictWriter zurück — öffnet die Datei nur beim ersten Aufruf."""
    key = str(path)
    if key not in _watch_writers:
        _ensure_csv_header(path, WATCH_FIELDNAMES)
        f: IO[str] = open(path, "a", newline="")
        _watch_writers[key] = (f, csv.DictWriter(f, fieldnames=WATCH_FIELDNAMES))
    return _watch_writers[key][1]


def close_watch_writer(path: Path) -> None:
    """Schließt und entfernt den Writer für diese Datei (beim Session-Stop)."""
    key = str(path)
    entry = _watch_writers.pop(key, None)
    if entry:
        try:
            entry[0].flush()
            entry[0].close()
        except OSError:
            pass


def close_all_watch_writers() -> None:
    """Schließt alle offenen Watch-Writer (beim Server-Shutdown)."""
    for key in list(_watch_writers):
        close_watch_writer(Path(key))


def get_airpods_writer(path: Path) -> csv.DictWriter:
    """Gibt einen gecachten DictWriter für die AirPods-CSV zurück."""
    key = str(path)
    if key not in _airpods_writers:
        _ensure_csv_header(path, AIRPODS_FIELDNAMES)
        f: IO[str] = open(path, "a", newline="")
        _airpods_writers[key] = (f, csv.DictWriter(f, fieldnames=AIRPODS_FIELDNAMES))
    return _airpods_writers[key][1]


def close_airpods_writer(path: Path) -> None:
    key = str(path)
    entry = _airpods_writers.pop(key, None)
    if entry:
        try:
            entry[0].flush()
            entry[0].close()
        except OSError:
            pass


def close_all_airpods_writers() -> None:
    for key in list(_airpods_writers):
        close_airpods_writer(Path(key))


def _airpods_sample_count(session_id: str) -> int:
    """Same incremental count strategy as _pen_sample_count."""
    path = DATA_RAW_AIRPODS / f"{session_id}_airpods.csv"
    if not path.exists():
        return 0
    try:
        size = path.stat().st_size
        cached_size, cached_lines = _airpods_count_cache.get(session_id, (0, 0))
        if size == cached_size:
            return max(0, cached_lines - 1)
        if size < cached_size:
            cached_size, cached_lines = 0, 0
        with open(path, "rb") as f:
            f.seek(cached_size)
            new_lines = f.read().count(b"\n")
        total = cached_lines + new_lines
        _airpods_count_cache[session_id] = (size, total)
        return max(0, total - 1)
    except Exception:
        return 0


_PEN_PREVIEW_TAIL = 524288  # 512 KB tail (~3000 dots at ~160 B each)
_PEN_PREVIEW_N = 2500       # max dots returned (~30 s at 80 Hz)

def _pen_recent_dots(session_id: str) -> list[dict[str, Any]]:
    """Return up to 200 most-recent pen dots for the live canvas preview.

    Each dict has keys: x (float), y (float), t (dot_type str), ts (int|None).
    Dots without valid x/y or with x==-1/y==-1 are excluded.
    """
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            header_bytes = f.readline()
            fieldnames = next(csv.reader([header_bytes.decode(errors="replace")]))
            file_size = f.seek(0, 2)
            header_size = len(header_bytes)
            if file_size <= header_size:
                return []
            f.seek(max(header_size, file_size - _PEN_PREVIEW_TAIL))
            tail = f.read().decode(errors="replace")
        results: list[dict[str, Any]] = []
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = next(csv.reader([line]), None)
            if not parsed or len(parsed) != len(fieldnames):
                continue
            row = dict(zip(fieldnames, parsed))
            x = _as_float(row.get("x"))
            y = _as_float(row.get("y"))
            if x is None or y is None or x == -1.0 or y == -1.0:
                continue
            dot_type = row.get("dot_type", "")
            if dot_type not in ("PEN_DOWN", "PEN_MOVE", "PEN_UP"):
                continue
            results.append({
                "x": x,
                "y": y,
                "t": dot_type,
                "ts": _as_int(row.get("local_ts_ms")) or _as_int(row.get("timestamp")),
            })
        return results[-_PEN_PREVIEW_N:]
    except Exception:
        return []


