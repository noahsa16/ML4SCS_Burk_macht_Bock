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

from fastapi import APIRouter, HTTPException

from ..focus_log import INFERENCE_LOG_PATH

router = APIRouter()

# Max-Luecke innerhalb einer Schreibphase. Bei 1 Hz Tick-Rate sind 2.5 s
# (= max_gap_ms aus dem Label-Closing in build_windows) die natuerliche
# Wahl: dieselbe "writing mode includes micro-pauses"-Semantik wie im
# Training. >2.5 s Stille bricht die Phase.
_STRETCH_GAP_S = 2.5

# Max number of intensity bins per stretch (downsampled proba for a sparkline).
# Short stretches use fewer bins (one per tick); the UI handles any length.
_INTENSITY_BINS = 24


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


def _intensity(rows: list[dict], start_ms: int, end_ms: int) -> list[float]:
    """Downsampled mean-proba across [start_ms, end_ms] — a sparkline of how
    confidently the model saw writing through the stretch. Empty bins forward-
    fill the previous value so brief tick gaps don't read as dips to zero.
    """
    window = [r for r in rows if start_ms <= r["ts_ms"] <= end_ms]
    if not window:
        return []
    n_bins = max(1, min(_INTENSITY_BINS, len(window)))
    span = max(1, end_ms - start_ms)
    sums = [0.0] * n_bins
    counts = [0] * n_bins
    for r in window:
        b = min(n_bins - 1, int((r["ts_ms"] - start_ms) / span * n_bins))
        sums[b] += r["proba"]
        counts[b] += 1
    out: list[float] = []
    last = 0.0
    for i in range(n_bins):
        if counts[i]:
            last = sums[i] / counts[i]
        out.append(round(last, 3))
    return out


def _day_payload(rows: list[dict], day_start_ms: int, day_end_ms: int,
                 date_iso: str, now_ms: int) -> dict:
    """Today-shaped focus payload for an arbitrary local day. Shared by
    /focus/today and /focus/day/{date} so both carry stretch intensity."""
    day_rows = [r for r in rows if day_start_ms <= r["ts_ms"] < day_end_ms]
    stretches = _stretches(day_rows)
    total_writing_seconds = sum(s["duration_s"] for s in stretches)
    return {
        "date": date_iso,
        "day_start_ms": day_start_ms,
        "day_end_ms": day_end_ms,
        "now_ms": now_ms,
        "total_writing_seconds": round(total_writing_seconds, 1),
        "stretches": [
            {
                "start_ms": s["start_ms"],
                "end_ms": s["end_ms"],
                "duration_s": round(s["duration_s"], 1),
                "intensity": _intensity(day_rows, s["start_ms"], s["end_ms"]),
            }
            for s in stretches
        ],
        "tick_count": len(day_rows),
    }


@router.get("/focus/today")
async def focus_today() -> dict:
    rows = _read_log_rows()
    now = datetime.now()
    day_start_ms, day_end_ms = _local_day_bounds(now)
    return _day_payload(rows, day_start_ms, day_end_ms,
                        now.strftime("%Y-%m-%d"), int(now.timestamp() * 1000))


@router.get("/focus/day/{date}")
async def focus_day(date: str) -> dict:
    """Stretches + intensity for any local day (powers historical Day-Detail)."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    rows = _read_log_rows()
    day_start_ms, day_end_ms = _local_day_bounds(d)
    now_ms = int(datetime.now().timestamp() * 1000)
    return _day_payload(rows, day_start_ms, day_end_ms, date, now_ms)


@router.get("/focus/timeofday")
async def focus_timeofday(days: int = 7) -> dict:
    """24 hourly writing-seconds buckets over the last `days` days, for the
    time-of-day distribution. Seconds are approximated by writing-tick counts
    (~1 Hz log), which is adequate for the relative shape across hours."""
    days = max(1, min(days, 365))
    rows = _read_log_rows()
    now = datetime.now()
    start_ms, _ = _local_day_bounds(now - timedelta(days=days - 1))
    _, end_ms = _local_day_bounds(now)
    buckets = [0.0] * 24
    for r in rows:
        if start_ms <= r["ts_ms"] < end_ms and r["writing"]:
            buckets[datetime.fromtimestamp(r["ts_ms"] / 1000.0).hour] += 1.0
    return {
        "buckets": [{"hour": h, "seconds": round(buckets[h], 1)} for h in range(24)],
        "days": days,
        "max_seconds": round(max(buckets), 1) if buckets else 0.0,
    }


def _day_buckets(rows: list[dict], n_days: int, now: datetime) -> tuple[list[dict], float]:
    """Sum writing-stretch seconds per local day for the last `n_days` days.

    Returns (days, max_seconds) where days is oldest -> newest, exactly
    `n_days` entries, today always last. Single source of truth shared by
    /focus/week and /focus/history.
    """
    today_iso = now.strftime("%Y-%m-%d")
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(_local_iso_date(r["ts_ms"]), []).append(r)

    days: list[dict] = []
    max_seconds = 0.0
    for i in range(n_days - 1, -1, -1):
        d = now - timedelta(days=i)
        day = d.strftime("%Y-%m-%d")
        secs = round(sum(s["duration_s"] for s in _stretches(by_day.get(day, []))), 1)
        max_seconds = max(max_seconds, secs)
        days.append({
            "date": day,
            "weekday": d.strftime("%a"),
            "writing_seconds": secs,
            "is_today": day == today_iso,
        })
    return days, max_seconds


@router.get("/focus/week")
async def focus_week() -> dict:
    rows = _read_log_rows()
    now = datetime.now()
    days, max_seconds = _day_buckets(rows, 7, now)
    return {
        "days": days,
        "today": now.strftime("%Y-%m-%d"),
        "max_seconds": max_seconds,
    }


@router.get("/focus/history")
async def focus_history(days: int = 7) -> dict:
    days = max(1, min(days, 365))
    rows = _read_log_rows()
    now = datetime.now()
    buckets, max_seconds = _day_buckets(rows, days, now)
    return {
        "days": buckets,
        "today": now.strftime("%Y-%m-%d"),
        "max_seconds": max_seconds,
    }
