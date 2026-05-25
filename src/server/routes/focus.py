"""Focus-Tracker-Aggregator-Endpoints.

Liest data/inference_log.csv und baut zwei Sichten:

GET /focus/today
    Heutige Schreibphasen (aufeinanderfolgende writing=1 Ticks) plus
    Gesamt-Sekunden, fuer die Tages-Timeline. Lokale Zeitzone des Servers.

GET /focus/week
    Letzte 7 Tage als {date: writing_seconds}. Buckets enthalten auch
    Tage ohne Daten (Wert 0), damit das Frontend einen sauberen
    7er-Frieze zeichnen kann.

Beide Routen sind read-only und cachen *nichts* (der Log ist klein
genug, dass jeder Tick neu zu aggregieren billiger ist als ein
Cache-Invalidierungs-Pfad). Bei Bedarf spaeter rolling-cache nachruesten.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

from ..focus_log import INFERENCE_LOG_PATH

router = APIRouter()

# Max-Luecke innerhalb einer Schreibphase. Bei 1 Hz Tick-Rate sind 2.5 s
# (= max_gap_ms aus dem Label-Closing in build_windows) die natuerliche
# Wahl: dieselbe "writing mode includes micro-pauses"-Semantik wie im
# Training. >2.5 s Stille bricht die Phase.
_STRETCH_GAP_S = 2.5


def _read_log_rows() -> list[dict]:
    p: Path = INFERENCE_LOG_PATH
    if not p.exists():
        return []
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    out: list[dict] = []
    for r in rows:
        try:
            out.append({
                "ts_ms": int(r["ts_ms"]),
                "proba": float(r.get("proba") or 0.0),
                "writing": int(r.get("writing") or 0),
                "model_id": r.get("model_id") or "",
            })
        except (ValueError, KeyError):
            continue
    return out


def _local_day_bounds(d: datetime) -> tuple[int, int]:
    """Return [start_ms, end_ms) of the local-time day containing `d`."""
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _local_iso_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d")


def _stretches(rows: list[dict]) -> list[dict]:
    """Group rows into writing stretches with their own start/end/duration.

    A stretch = run of writing==1 ticks, with gaps <= _STRETCH_GAP_S forgiven.
    """
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: r["ts_ms"])
    stretches: list[dict] = []
    cur_start: int | None = None
    cur_end: int | None = None
    gap_ms = int(_STRETCH_GAP_S * 1000)
    for r in rows:
        if r["writing"]:
            if cur_start is None:
                cur_start = r["ts_ms"]
                cur_end = r["ts_ms"]
            else:
                if cur_end is not None and r["ts_ms"] - cur_end > gap_ms:
                    stretches.append({
                        "start_ms": cur_start,
                        "end_ms": cur_end,
                        "duration_s": (cur_end - cur_start) / 1000.0,
                    })
                    cur_start = r["ts_ms"]
                cur_end = r["ts_ms"]
        else:
            # Idle ticks within gap_ms don't break the stretch.
            if cur_end is not None and r["ts_ms"] - cur_end > gap_ms:
                stretches.append({
                    "start_ms": cur_start,
                    "end_ms": cur_end,
                    "duration_s": (cur_end - cur_start) / 1000.0,
                })
                cur_start = None
                cur_end = None
    if cur_start is not None and cur_end is not None:
        stretches.append({
            "start_ms": cur_start,
            "end_ms": cur_end,
            "duration_s": (cur_end - cur_start) / 1000.0,
        })
    # Drop strech of length 0 (single tick).
    return [s for s in stretches if s["duration_s"] >= 1.0]


@router.get("/focus/today")
async def focus_today() -> dict:
    rows = _read_log_rows()
    now = datetime.now()
    day_start_ms, day_end_ms = _local_day_bounds(now)
    today_rows = [r for r in rows if day_start_ms <= r["ts_ms"] < day_end_ms]

    stretches = _stretches(today_rows)
    total_writing_seconds = sum(s["duration_s"] for s in stretches)

    return {
        "date": now.strftime("%Y-%m-%d"),
        "day_start_ms": day_start_ms,
        "day_end_ms": day_end_ms,
        "now_ms": int(now.timestamp() * 1000),
        "total_writing_seconds": round(total_writing_seconds, 1),
        "stretches": [
            {
                "start_ms": s["start_ms"],
                "end_ms": s["end_ms"],
                "duration_s": round(s["duration_s"], 1),
            }
            for s in stretches
        ],
        "tick_count": len(today_rows),
    }


@router.get("/focus/week")
async def focus_week() -> dict:
    rows = _read_log_rows()
    now = datetime.now()
    today_iso = now.strftime("%Y-%m-%d")

    bucket: dict[str, float] = {}
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        d = _local_iso_date(r["ts_ms"])
        by_day.setdefault(d, []).append(r)

    # Iterate the last 7 days (oldest -> newest) so the frontend gets a
    # ready-to-render ordering.
    days: list[dict] = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_rows = by_day.get(day, [])
        secs = sum(s["duration_s"] for s in _stretches(day_rows))
        bucket[day] = round(secs, 1)
        days.append({
            "date": day,
            "weekday": (now - timedelta(days=i)).strftime("%a"),
            "writing_seconds": round(secs, 1),
            "is_today": day == today_iso,
        })

    return {
        "days": days,
        "today": today_iso,
        "max_seconds": max(bucket.values(), default=0.0),
    }
