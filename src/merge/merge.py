"""Pen + Watch zu einem device-time-alignten DataFrame zusammenführen.

Ablauf in ``merge_pen_watch()``:

  1. Rohe CSVs einlesen
  2. δ schätzen (via :mod:`src.alignment`)
  3. Wenn σ ≤ -2 (Confidence ok): pen.local_ts_ms += δ·1000
     Wenn σ > -2 (flache Kurve): δ verwerfen, ohne Shift weitermachen
  4. Beide Streams auf gemeinsame Device-Time-Achse bringen (Anker = erstes
     Watch-Sample); Pen-Features berechnen (distance, speed, label_writing)
  5. ``pd.merge_asof`` mit ±20 ms Toleranz, Pen-Rows = Basis,
     direction="nearest"
  6. δ und σ als ``df.attrs`` für Downstream-Diagnose anhängen
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.alignment import (
    PenMatchResult,
    match_pen_data,
    reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)
from .prep import (
    _first_numeric,
    _prepare_pen_from_df,
    _prepare_watch_from_df,
    load_csv,
)


def estimate_pen_imu_offset(
    raw_pen: pd.DataFrame,
    raw_watch: pd.DataFrame,
) -> PenMatchResult | None:
    """Run the variance-based pen↔IMU alignment on raw CSVs.

    Returns a ``PenMatchResult`` (delta_sec + diagnostics) or None if the
    inputs are too small to align. The caller decides whether to trust
    the returned δ — ``sigma_minimal_variance < -2`` is a reasonable
    threshold (the Swiss reference uses the same heuristic).
    """
    if "local_ts_ms" not in raw_pen.columns or "local_ts_ms" not in raw_watch.columns:
        return None

    pen_ts = pd.to_datetime(
        pd.to_numeric(raw_pen["local_ts_ms"], errors="coerce"),
        unit="ms", utc=True,
    )
    if "ts" not in raw_watch.columns:
        return None
    watch_ts = reconstruct_watch_wall_clock(raw_watch)

    pen_for_match = pd.DataFrame({
        "timestamp": pen_ts,
        "dot_type": raw_pen.get("dot_type", ""),
        "x": pd.to_numeric(raw_pen.get("x"), errors="coerce"),
        "y": pd.to_numeric(raw_pen.get("y"), errors="coerce"),
    }).dropna(subset=["timestamp"])
    pen_strokes = strokes_from_dot_types(pen_for_match)
    if pen_strokes.empty:
        return None

    watch_for_match = pd.DataFrame({
        "timestamp": watch_ts,
        "ax": pd.to_numeric(raw_watch.get("ax"), errors="coerce"),
        "ay": pd.to_numeric(raw_watch.get("ay"), errors="coerce"),
        "az": pd.to_numeric(raw_watch.get("az"), errors="coerce"),
    }).dropna().sort_values("timestamp").reset_index(drop=True)
    if len(watch_for_match) < 50:
        return None

    return match_pen_data(watch_for_match, pen_strokes)


def merge_pen_watch(pen_path: str | Path,
                    watch_path: str | Path,
                    tolerance_ms: int = 20,
                    align_clocks: bool = True,
                    sigma_threshold: float = -2.0) -> pd.DataFrame:
    """Joined pen + watch data via nearest-neighbour on device time.

    With ``align_clocks=True`` (default), the pen↔IMU clock offset is first
    estimated via variance minimization over stroke windows
    (see :mod:`src.alignment`) and applied to the pen wall-clock before
    ``merge_asof``. The result carries ``pen_clock_offset_sec`` (applied
    shift) and ``pen_clock_sigma`` (confidence z-score) as DataFrame attrs.
    """
    raw_pen = load_csv(pen_path)
    raw_watch = load_csv(watch_path)

    delta_sec = 0.0
    sigma = float("nan")
    if align_clocks:
        result = estimate_pen_imu_offset(raw_pen, raw_watch)
        if result is not None and np.isfinite(result.sigma_minimal_variance):
            sigma = result.sigma_minimal_variance
            if sigma <= sigma_threshold:
                delta_sec = result.delta_sec
                # Apply δ to pen wall-clock — pen reports samples late by δ
                # relative to the watch, so we shift pen timestamps forward
                # in time when δ < 0 and back when δ > 0. The convention
                # matches the PDF math: t_pen ↦ t_pen + δ.
                if "local_ts_ms" in raw_pen.columns:
                    raw_pen = raw_pen.copy()
                    raw_pen["local_ts_ms"] = (
                        pd.to_numeric(raw_pen["local_ts_ms"], errors="coerce")
                        + delta_sec * 1000.0
                    )

    anchor_local_ms = _first_numeric(raw_watch, ["local_ts_ms", "server_received_ms"])
    pen = _prepare_pen_from_df(raw_pen, anchor_local_ms=anchor_local_ms).rename(
        columns={"timestamp": "ts_pen", "device_time_ms": "pen_device_time_ms"}
    )
    watch = _prepare_watch_from_df(raw_watch, anchor_local_ms=anchor_local_ms).rename(
        columns={"device_time_ms": "watch_device_time_ms"}
    )
    merged = pd.merge_asof(
        pen.sort_values("pen_device_time_ms"),
        watch.sort_values("watch_device_time_ms"),
        left_on="pen_device_time_ms", right_on="watch_device_time_ms",
        tolerance=tolerance_ms,
        direction="nearest",
    )
    merged.attrs["pen_clock_offset_sec"] = delta_sec
    merged.attrs["pen_clock_sigma"] = sigma
    return merged
