"""
Pen ↔ IMU Sync-Diagnostik.

Drei Funktionen, ein Thema:
  _sync_diagnostic               Human-readable Status (für Reports/UI)
  _estimate_sync_via_pen_match   Stroke-Varianz-Algorithmus (TH Zürich) —
                                 die heute genutzte Methode
  _estimate_sync_drift           Legacy Tap-Matching-Heuristik (PEN_DOWN ↔
                                 Watch-Motion-Peaks) — bleibt als Fallback

``_watch_peaks`` lebt hier statt in ``timelines.py``, weil es nur von
``_estimate_sync_drift`` aufgerufen wird; die Modul-Grenze entlang des
einzigen Aufrufers vermeidet einen Cross-Import in Gegenrichtung.
"""

import math
from statistics import median
from typing import Any

from .config import DATA_RAW_PEN, DATA_RAW_WATCH
from .issues import _SYNC_SIGMA_OK_MAX, _SYNC_SIGMA_WEAK_MAX
from .utils import _mad


# ── Sync-Heuristik: Konstanten ────────────────────────────────────────────────
_TAP_MAX_DURATION_MS         = 1400
_TAP_MAX_DOTS                = 80
_PEAK_MIN_SEPARATION_MS      = 250
_MATCH_SEARCH_WINDOW_MS      = 1600
_CONFIDENCE_HIGH_MIN_MATCHES = 6
_CONFIDENCE_HIGH_MAX_ERROR   = 350
_CONFIDENCE_LOW_MAX_ERROR    = 900
_MAX_CANDIDATES              = 24
_CANDIDATES_KEEP_EACH        = 12


def _sync_diagnostic(sync: dict[str, Any]) -> dict[str, Any]:
    """Human-readable summary of the pen↔IMU variance alignment result."""
    method = sync.get("method", "")
    if method != "stroke_variance_minimization":
        # Legacy / unknown shape — fall through to the older descriptions.
        if sync.get("usable"):
            return {"status": "estimated", "label": "estimated",
                    "message": f"Heuristik-Confidence: {sync.get('confidence', 'unknown')}."}
        return {"status": "not_required", "label": "not required",
                "message": sync.get("reason", "Keine Sync-Diagnose verfügbar.")}

    confidence = sync.get("confidence", "none")
    delta_ms = sync.get("delta_ms")
    sigma = sync.get("sigma_minimal_variance")

    if confidence == "high":
        return {
            "status": "aligned",
            "label": "aligned",
            "message": (
                f"Pen↔IMU Sync gefunden: δ = {delta_ms:.0f} ms "
                f"(σ = {sigma:.2f}, klare Senke in der Varianzkurve). "
                f"Sample-level Merge ist verlässlich."
            ),
        }
    if confidence == "low":
        return {
            "status": "weak_signal",
            "label": "weak signal",
            "message": (
                f"δ = {delta_ms:.0f} ms gefunden, aber σ = {sigma:.2f} ist "
                f"schwach (Schwelle ≤ {_SYNC_SIGMA_OK_MAX}). Session-level "
                f"Overlap ok; sample-level Merge mit Vorsicht verwenden."
            ),
        }
    reason = sync.get("reason") or (
        "Varianzkurve ist flach — kein klares δ erkennbar."
        if sigma is not None else "Algorithmus konnte nicht ausgeführt werden."
    )
    return {
        "status": "no_alignment",
        "label": "no alignment",
        "message": reason,
    }


# ── Watch-Bewegungs-Peaks (für die Tap-Matching-Heuristik) ────────────────────

def _watch_peaks(rows: list[dict[str, Any]], max_peaks: int = 80) -> list[dict[str, Any]]:
    candidates = [
        r for r in rows
        if r.get("source_ts") is not None and r.get("motion_mag") is not None
    ]
    if len(candidates) < 5:
        return []
    mags = [float(r["motion_mag"]) for r in candidates]
    center = median(mags)
    spread = _mad(mags, center)
    threshold = center + max(0.015, spread * 4)
    peaks: list[dict[str, Any]] = []
    last_ts = None
    for row in sorted(candidates, key=lambda r: r["source_ts"]):
        mag = float(row["motion_mag"])
        if mag < threshold:
            continue
        source_ts = row["source_ts"]
        if last_ts is not None and source_ts - last_ts < _PEAK_MIN_SEPARATION_MS:
            if peaks and mag > peaks[-1]["motion_mag"]:
                peaks[-1] = {"source_ts": source_ts, "motion_mag": round(mag, 6)}
            continue
        peaks.append({"source_ts": source_ts, "motion_mag": round(mag, 6)})
        last_ts = source_ts
    return sorted(peaks, key=lambda r: r["motion_mag"], reverse=True)[:max_peaks]


def _estimate_sync_via_pen_match(session_id: str) -> dict[str, Any]:
    """Variance-minimization pen↔IMU sync (Swiss TH-Zürich algorithm).

    Loads the raw watch and pen CSVs for ``session_id`` and runs
    :func:`src.alignment.match_pen_data`. Returns a dict
    with the same broad shape as the legacy tap-matching result so all
    existing consumers (``_sync_diagnostic``, reports, frontend) keep
    working unchanged.
    """
    import pandas as pd
    from src.alignment import (
        match_pen_data, reconstruct_watch_wall_clock, strokes_from_dot_types,
    )

    watch_path = DATA_RAW_WATCH / f"{session_id}_watch.csv"
    pen_path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not watch_path.exists() or not pen_path.exists():
        return {
            "usable": False, "confidence": "none",
            "method": "stroke_variance_minimization",
            "reason": "Missing watch or pen CSV.",
        }

    try:
        watch_df = pd.read_csv(watch_path)
        pen_df = pd.read_csv(pen_path)
    except Exception as exc:
        return {
            "usable": False, "confidence": "none",
            "method": "stroke_variance_minimization",
            "reason": f"Could not read CSV: {exc}",
        }

    if (
        "local_ts_ms" not in watch_df.columns
        or "ts" not in watch_df.columns
        or "local_ts_ms" not in pen_df.columns
    ):
        return {
            "usable": False, "confidence": "none",
            "method": "stroke_variance_minimization",
            "reason": "Legacy CSV without local_ts_ms / ts — cannot align on wall-clock.",
        }

    watch_for_match = pd.DataFrame({
        "timestamp": reconstruct_watch_wall_clock(watch_df),
        "ax": pd.to_numeric(watch_df.get("ax"), errors="coerce"),
        "ay": pd.to_numeric(watch_df.get("ay"), errors="coerce"),
        "az": pd.to_numeric(watch_df.get("az"), errors="coerce"),
    }).dropna().sort_values("timestamp").reset_index(drop=True)

    pen_for_match = pd.DataFrame({
        "timestamp": pd.to_datetime(
            pd.to_numeric(pen_df["local_ts_ms"], errors="coerce"),
            unit="ms", utc=True,
        ),
        "dot_type": pen_df.get("dot_type", ""),
        "x": pd.to_numeric(pen_df.get("x"), errors="coerce"),
        "y": pd.to_numeric(pen_df.get("y"), errors="coerce"),
    }).dropna(subset=["timestamp"])
    pen_strokes = strokes_from_dot_types(pen_for_match)

    if len(watch_for_match) < 50 or pen_strokes.empty:
        return {
            "usable": False, "confidence": "none",
            "method": "stroke_variance_minimization",
            "reason": "Too few IMU samples or no pen strokes for alignment.",
            "n_strokes": int(pen_strokes["StrokeID"].nunique()) if not pen_strokes.empty else 0,
            "n_imu_samples": int(len(watch_for_match)),
        }

    result = match_pen_data(watch_for_match, pen_strokes)
    if result is None:
        return {
            "usable": False, "confidence": "none",
            "method": "stroke_variance_minimization",
            "reason": "Algorithm returned no result.",
        }

    sigma = result.sigma_minimal_variance
    if not math.isfinite(sigma):
        confidence = "none"
        usable = False
    elif sigma <= _SYNC_SIGMA_OK_MAX:
        confidence = "high"
        usable = True
    elif sigma <= _SYNC_SIGMA_WEAK_MAX:
        confidence = "low"
        usable = True
    else:
        confidence = "none"
        usable = False

    return {
        "usable": usable,
        "confidence": confidence,
        "method": "stroke_variance_minimization",
        "delta_sec": round(result.delta_sec, 4),
        "delta_ms": round(result.delta_sec * 1000.0, 1),
        "minimal_variance": round(result.minimal_variance, 6),
        "average_variance": round(result.average_variance, 6),
        "stddev_variance": round(result.stddev_variance, 6),
        "sigma_minimal_variance": (
            round(sigma, 3) if math.isfinite(sigma) else None
        ),
        "coarse_delta_sec": round(result.coarse_delta_sec, 3),
        "n_strokes": result.n_strokes,
        "n_imu_samples": result.n_imu_samples,
        "fs_hz": round(result.fs_hz, 2),
    }


def _estimate_sync_drift(
    watch_rows: list[dict[str, Any]],
    pen_rows: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    watch_offsets = [
        r["local_ts"] - r["source_ts"]
        for r in watch_rows
        if r.get("local_ts") is not None and r.get("source_ts") is not None
    ]
    pen_offsets = [
        r["local_ts"] - r["source_ts"]
        for r in pen_rows
        if r.get("local_ts") is not None and r.get("source_ts") is not None
    ]
    if not watch_offsets or not pen_offsets:
        return {
            "usable": False, "confidence": "none", "method": "sync tap matching",
            "reason": "Need local and source timestamps for both streams.",
            "matched_events": [],
        }

    approx_pen_to_watch_offset = median(pen_offsets) - median(watch_offsets)
    peaks = _watch_peaks(watch_rows)
    if not peaks:
        return {
            "usable": False, "confidence": "none", "method": "sync tap matching",
            "reason": "No clear watch motion peaks found.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "matched_events": [],
        }

    pen_downs = [
        r for r in pen_rows
        if r.get("dot_type") == "PEN_DOWN" and r.get("source_ts") is not None
    ]
    short_intervals = [
        i for i in intervals
        if i.get("source_start_ms") is not None
        and i.get("duration_ms") is not None
        and i["duration_ms"] <= _TAP_MAX_DURATION_MS
        and i.get("dot_count", 9999) <= _TAP_MAX_DOTS
    ]
    candidate_ts = [i["source_start_ms"] for i in short_intervals] or [
        r["source_ts"] for r in pen_downs
    ]
    if not candidate_ts:
        return {
            "usable": False, "confidence": "none", "method": "sync tap matching",
            "reason": "No PEN_DOWN candidates found.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "matched_events": [],
        }

    candidate_ts = sorted(candidate_ts)
    if len(candidate_ts) > _MAX_CANDIDATES:
        candidate_ts = candidate_ts[:_CANDIDATES_KEEP_EACH] + candidate_ts[-_CANDIDATES_KEEP_EACH:]

    peak_by_ts = sorted(peaks, key=lambda p: p["source_ts"])
    matches: list[dict[str, Any]] = []
    for pen_ts in candidate_ts:
        predicted = pen_ts + approx_pen_to_watch_offset
        nearest = min(peak_by_ts, key=lambda peak: abs(peak["source_ts"] - predicted), default=None)
        if not nearest:
            continue
        error = nearest["source_ts"] - predicted
        if abs(error) <= _MATCH_SEARCH_WINDOW_MS:
            matches.append({
                "pen_source_ms": pen_ts,
                "watch_peak_source_ms": nearest["source_ts"],
                "offset_ms": round(nearest["source_ts"] - pen_ts, 3),
                "error_from_local_anchor_ms": round(error, 3),
                "watch_motion_mag": nearest["motion_mag"],
            })

    if len(matches) < 2:
        return {
            "usable": False, "confidence": "low", "method": "sync tap matching",
            "reason": "Fewer than two matched sync-like events. Add clear start/end tap sync events.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "watch_peaks_found": len(peaks),
            "pen_candidates_found": len(candidate_ts),
            "matched_events": matches,
        }

    matches = sorted(matches, key=lambda m: m["pen_source_ms"])
    offsets = [m["offset_ms"] for m in matches]
    split = max(1, len(matches) // 2)
    start_offset = median(offsets[:split])
    end_offset = median(offsets[split:])
    drift_ms = end_offset - start_offset
    errors = [m["error_from_local_anchor_ms"] for m in matches]
    max_error = max(abs(e) for e in errors)
    confidence = "high" if len(matches) >= _CONFIDENCE_HIGH_MIN_MATCHES and max_error <= _CONFIDENCE_HIGH_MAX_ERROR else "medium"
    if max_error > _CONFIDENCE_LOW_MAX_ERROR:
        confidence = "low"
    return {
        "usable": True,
        "confidence": confidence,
        "method": "PEN_DOWN/short-stroke candidates matched to watch motion peaks",
        "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
        "median_offset_ms": round(median(offsets), 3),
        "start_offset_ms": round(start_offset, 3),
        "end_offset_ms": round(end_offset, 3),
        "estimated_drift_ms": round(drift_ms, 3),
        "max_abs_error_from_local_anchor_ms": round(max_error, 3),
        "watch_peaks_found": len(peaks),
        "pen_candidates_found": len(candidate_ts),
        "matched_events": matches,
        "note": "Use an explicit start/end tap protocol before trusting this as calibration.",
    }
