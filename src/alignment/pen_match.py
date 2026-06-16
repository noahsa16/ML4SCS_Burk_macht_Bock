"""Pen ↔ IMU timestamp alignment via stroke-window variance minimization.

Algorithm courtesy of the ETH Zürich collaborators (see
``data/02_Pen_IMU_Timestamp_Alignment.pdf``). Physical assumption: while
the pen is on paper, the wrist holding the watch is comparatively still.
A wrong shift δ places stroke intervals on top of higher-variance arm
motion, so the right δ shows up as a clear minimum of the mean
acceleration variance under the shifted stroke mask.

Core function ``pen_match`` is a 1:1 port of the Swiss reference
implementation (page 7-8 of the PDF), adapted to our column names
(``ax/ay/az`` instead of ``AccX/Y/Z``). ``match_pen_data`` wraps the
coarse-then-fine search and emits diagnostics. ``strokes_from_dot_types``
converts our ``dot_type`` column (PEN_DOWN/PEN_MOVE/PEN_UP) into the
``StrokeID`` column the algorithm expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# Default search grid for the NWP-F130 Moleskine pen — matches the
# Swiss "moleskine" preset. Coarse covers ±20 s in 0.5 s steps to handle
# BLE buffering + clock drift; fine narrows to ±5 s at 10 ms resolution.
DEFAULT_PARAMS = {
    "coarse_start_delta_sec": -20.0,
    "coarse_end_delta_sec":    20.0,
    "coarse_step_sec":          0.5,
    "fine_half_width_sec":      5.0,
    "fine_step_sec":            0.01,
    "var_window_sec":           0.2,
}

ACC_COLS = ("ax", "ay", "az")


# ── Watch wall-clock reconstruction ──────────────────────────────────────────

def reconstruct_watch_wall_clock(raw_watch: pd.DataFrame) -> pd.Series:
    """Build a per-sample wall-clock timestamp for the watch.

    Watch CSVs carry two clocks per row:
      * ``ts`` — Unix-epoch ms set on the watch via
        ``Date().timeIntervalSince1970 * 1000`` (see ``MotionManager.swift``).
        This is wall-clock-like and regular at 50 Hz, but on the watch's
        own clock (NTP-synced via iPhone, drift typically < 100 ms).
      * ``local_ts_ms`` — phone wall-clock at batch receive (quantized,
        25 samples in a batch share the same value).

    For pen↔IMU alignment we need a regular per-sample timeline on the
    same wall-clock as the pen. ``ts`` is already exactly that. We use it
    directly. The small phone↔watch clock skew shows up as part of the
    recovered δ, which is exactly what we want.
    """
    ts = pd.to_numeric(raw_watch["ts"], errors="coerce")
    return pd.to_datetime(ts, unit="ms", utc=True)


@dataclass
class PenMatchResult:
    """Outcome of a coarse+fine pen↔IMU alignment search."""
    delta_sec: float
    minimal_variance: float
    average_variance: float
    stddev_variance: float
    sigma_minimal_variance: float  # z-score of the minimum vs the search-grid distribution
    coarse_delta_sec: float
    n_strokes: int
    n_imu_samples: int
    fs_hz: float
    fine_var_series: pd.Series = field(repr=False)


# ── Stroke derivation ────────────────────────────────────────────────────────

def strokes_from_dot_types(pen_df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``StrokeID`` column based on ``dot_type`` transitions.

    Rules:
        * PEN_DOWN starts a new stroke (incremented integer ID).
        * PEN_MOVE inherits the current stroke ID.
        * PEN_UP closes the stroke (still gets the current ID — it is the
          last sample of that stroke).
        * PEN_HOVER and rows with x == -1 / y == -1 are framing/non-writing
          events and are dropped.
        * Rows before the first PEN_DOWN are dropped (no stroke open).

    The pen logger occasionally emits PEN_MOVE without a preceding
    PEN_DOWN — those are treated as belonging to the most recent stroke;
    if there has been none, they are dropped.
    """
    if "dot_type" not in pen_df.columns:
        raise ValueError("pen_df must have a 'dot_type' column")

    df = pen_df.copy()
    df = df[df["dot_type"].isin(["PEN_DOWN", "PEN_MOVE", "PEN_UP"])].copy()
    # NB: our pen_logger emits PEN_DOWN events with x=-1, y=-1 (no coords
    # are carried in the DOWN packet — see pen_logger.py:288). Only apply
    # the framing-event filter to PEN_MOVE rows which require coordinates;
    # PEN_DOWN/UP carry the temporal stroke boundary even without coords.
    if {"x", "y"}.issubset(df.columns):
        keep = (df["dot_type"] != "PEN_MOVE") | ((df["x"] != -1) & (df["y"] != -1))
        df = df[keep]

    stroke_ids = np.empty(len(df), dtype=np.int64)
    current = -1
    for i, dt in enumerate(df["dot_type"].to_numpy()):
        if dt == "PEN_DOWN":
            current += 1
        stroke_ids[i] = current

    df["StrokeID"] = stroke_ids
    df = df[df["StrokeID"] >= 0].reset_index(drop=True)
    return df


# ── Core algorithm (1:1 port from the Swiss reference) ──────────────────────

def pen_match(
    imu_df: pd.DataFrame,
    pen_df: pd.DataFrame,
    start_delta_sec: float,
    end_delta_sec: float,
    step_sec: float,
    var_window_sec: float = 0.2,
    acc_cols: tuple[str, ...] = ACC_COLS,
) -> tuple[tuple[float, float], pd.Series]:
    """Find time shift between IMU and pen-stroke intervals.

    Builds a normalized rolling acceleration-variance signal on the IMU,
    masks samples that fall inside pen-stroke time ranges, then evaluates
    the mean variance under the shifted mask over a grid of integer-sample
    shifts. The shift with the lowest mean variance is returned.

    Args:
        imu_df: IMU samples in time order. Must include:
            - ``timestamp``: datetime-like, used to infer sample rate and
              for masking.
            - Columns named in ``acc_cols`` (default ``ax``, ``ay``, ``az``).
        pen_df: Pen stroke samples. Must include:
            - ``StrokeID``: identifier to group strokes (use
              ``strokes_from_dot_types`` to derive this from ``dot_type``).
            - ``timestamp``: datetime-like; per-stroke min/max define the
              in-stroke interval on the IMU timeline (before applying
              shift search).
        start_delta_sec: Start of shift grid (seconds), passed to
            ``numpy.arange``.
        end_delta_sec: End of shift grid (exclusive), passed to
            ``numpy.arange``.
        step_sec: Step size (seconds) between candidate shifts.
        var_window_sec: Rolling window length (seconds) for variance on
            ``acc_cols``.
        acc_cols: Subset of columns in ``imu_df`` used for the variance
            feature.

    Returns:
        Tuple ``((best_delta_sec, min_mean_variance), var_series)`` where
        ``var_series`` is a ``pd.Series`` of mean variance indexed by
        candidate ``delta_sec``.
    """
    if imu_df.empty:
        raise ValueError("imu_df is empty")
    if pen_df.empty:
        raise ValueError("pen_df is empty")
    if "StrokeID" not in pen_df.columns:
        raise ValueError("pen_df must have a 'StrokeID' column")

    diffs = imu_df["timestamp"].diff().dropna()
    if diffs.empty:
        raise ValueError("imu_df needs at least 2 timestamps to estimate fs")
    median_dt = diffs.median()
    median_dt_sec = (
        median_dt.total_seconds() if hasattr(median_dt, "total_seconds")
        else float(median_dt)
    )
    if median_dt_sec <= 0:
        raise ValueError("Non-positive median timestamp diff — IMU not sorted?")
    fs_hz = 1.0 / median_dt_sec

    var_window_samples = max(2, int(var_window_sec * fs_hz))
    acc = imu_df[list(acc_cols)].astype(np.float32)
    g_norm = np.sqrt((acc ** 2).sum(axis=1)).median()
    if not np.isfinite(g_norm) or g_norm == 0:
        g_norm = 1.0

    var_vec = (
        acc.rolling(window=var_window_samples, center=True).var()
    )
    var_vec = np.sqrt((var_vec ** 2).sum(axis=1)) / g_norm
    # NB: the Swiss reference implementation does an extra `var_vec.shift(-W)`
    # at this point. That step is not in the documented math (PDF §"Math")
    # — it's a convention that bakes a constant +var_window_sec offset into
    # every reported delta. We use centered alignment instead so the
    # returned δ corresponds directly to the math: t_pen ↦ t_pen + δ.

    strokes = pen_df.groupby("StrokeID")["timestamp"].agg(["min", "max"])
    if strokes.empty:
        raise ValueError("pen_df produced zero strokes after grouping")

    mask = pd.Series(False, index=imu_df.index)
    ts = imu_df["timestamp"]
    for _, row in strokes.iterrows():
        mask |= (ts >= row["min"]) & (ts <= row["max"])

    if not mask.any():
        # Strokes don't overlap the IMU window at all (in raw time before
        # shifting). Run the search anyway — non-zero shifts may bring
        # them into range.
        pass

    deltas_sec = np.arange(start_delta_sec, end_delta_sec, step_sec)
    deltas_samples = np.round(deltas_sec * fs_hz).astype(int)

    var_values: list[float] = []
    for d in deltas_samples:
        shifted_mask = mask.shift(d, fill_value=False)
        vals = var_vec[shifted_mask]
        var_values.append(float(vals.mean()) if not vals.empty else float("nan"))

    var_series = pd.Series(var_values, index=deltas_sec)
    finite = var_series.dropna()
    if finite.empty:
        # No shift produced any in-mask samples — alignment impossible.
        return (0.0, float("nan")), var_series
    best_delta = float(finite.idxmin())
    best_value = float(finite.loc[best_delta])
    return (best_delta, best_value), var_series


# ── High-level wrapper with coarse-then-fine + diagnostics ──────────────────

def match_pen_data(
    imu_df: pd.DataFrame,
    pen_df: pd.DataFrame,
    params: Optional[dict] = None,
) -> Optional[PenMatchResult]:
    """Run coarse-then-fine pen↔IMU alignment.

    Returns None if the inputs are too small to align (less than 1 stroke
    or fewer than 2 IMU rows). Otherwise returns a ``PenMatchResult`` with
    the best ``delta_sec`` and a ``sigma_minimal_variance`` z-score that
    callers can use as a confidence proxy (more negative = more confident
    well; values above ~-2 mean a flat curve = weak alignment).
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    if len(imu_df) < 2 or pen_df.empty or pen_df["StrokeID"].nunique() < 1:
        return None

    coarse_min, _ = pen_match(
        imu_df, pen_df,
        start_delta_sec=p["coarse_start_delta_sec"],
        end_delta_sec=p["coarse_end_delta_sec"],
        step_sec=p["coarse_step_sec"],
        var_window_sec=p["var_window_sec"],
    )
    coarse_delta = coarse_min[0]

    fine_min, fine_series = pen_match(
        imu_df, pen_df,
        start_delta_sec=coarse_delta - p["fine_half_width_sec"],
        end_delta_sec=coarse_delta + p["fine_half_width_sec"],
        step_sec=p["fine_step_sec"],
        var_window_sec=p["var_window_sec"],
    )

    finite = fine_series.dropna()
    mean_v = float(finite.mean()) if not finite.empty else float("nan")
    std_v = float(finite.std()) if not finite.empty else float("nan")
    sigma = (
        (fine_min[1] - mean_v) / std_v
        if std_v and np.isfinite(std_v) and std_v > 0
        else float("nan")
    )

    diffs = imu_df["timestamp"].diff().dropna()
    median_dt = diffs.median()
    median_dt_sec = (
        median_dt.total_seconds() if hasattr(median_dt, "total_seconds")
        else float(median_dt)
    )
    fs_hz = 1.0 / median_dt_sec if median_dt_sec else float("nan")

    return PenMatchResult(
        delta_sec=float(fine_min[0]),
        minimal_variance=float(fine_min[1]),
        average_variance=mean_v,
        stddev_variance=std_v,
        sigma_minimal_variance=float(sigma) if np.isfinite(sigma) else float("nan"),
        coarse_delta_sec=float(coarse_delta),
        n_strokes=int(pen_df["StrokeID"].nunique()),
        n_imu_samples=int(len(imu_df)),
        fs_hz=float(fs_hz),
        fine_var_series=fine_series,
    )
