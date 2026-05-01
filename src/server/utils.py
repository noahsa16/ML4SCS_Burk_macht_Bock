"""
Reine Hilfsfunktionen ohne Seiteneffekte.

Typ-Coercions, Zeitstempel-Konvertierungen, Statistik-Helfer.
Kein Import aus anderen src/server-Modulen — das hier ist die Basis-Schicht.
"""

import time
from datetime import datetime, timezone
from statistics import median
from typing import Any, Optional


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


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_to_ms(value: Any) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def _row_local_ms(row: dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = _as_int(row.get(key))
        if value is not None:
            return value
    return _iso_to_ms(row.get("local_ts"))


def _median(values: list[float]) -> Optional[float]:
    return median(values) if values else None


def _mad(values: list[float], center: Optional[float] = None) -> float:
    if not values:
        return 0.0
    c = center if center is not None else median(values)
    return median([abs(v - c) for v in values])
