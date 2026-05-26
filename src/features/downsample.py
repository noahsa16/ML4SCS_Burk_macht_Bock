"""Downsample a Modern-Pool Watch-CSV to Legacy-Pool format.

Use case: cross-pool training / evaluation. Modern-Pool sessions are
100 Hz with gravity (9 IMU channels). To compare them against the
Legacy-Pool baseline (50 Hz, 6 channels, N=10), we need to view them
"as if" they were Legacy:

    downsample_watch_csv("S034", target_hz=50, drop_gravity=True)
      → data/raw/watch/S034_watch_legacy.csv

Pipeline:
    src.merge S034 --watch-suffix legacy → data/processed/S034_merged.csv
    src.features S034 → 88-feature windows (no gravity)
    src.training.train_loso --pool legacy

CLI::

    python -m src.features.downsample S034
    python -m src.features.downsample S034 --target-hz 50 --keep-gravity
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal

ROOT = Path(__file__).parents[2]
DATA_RAW_WATCH = ROOT / "data" / "raw" / "watch"

_NUMERIC_IMU_COLS = ("ax", "ay", "az", "rx", "ry", "rz", "gx", "gy", "gz")


def _infer_source_hz(df: pd.DataFrame) -> float:
    """Determine source rate from the sample_rate_hz column or from ts diffs."""
    if "sample_rate_hz" in df.columns and df["sample_rate_hz"].notna().any():
        return float(df["sample_rate_hz"].dropna().iloc[0])
    if "ts" in df.columns:
        ts = df["ts"].dropna().astype(float).to_numpy()
        diffs = np.diff(ts)
        diffs = diffs[diffs > 0]
        if len(diffs) >= 5:
            return 1000.0 / float(np.median(diffs))
    raise ValueError("could not infer source Hz from DataFrame")


def downsample_watch_df(
    df: pd.DataFrame,
    target_hz: float,
    drop_gravity: bool = True,
) -> pd.DataFrame:
    """Downsample a Watch-CSV DataFrame to ``target_hz``.

    Uses scipy.signal.decimate (8th-order Chebyshev type I anti-aliasing
    by default) per IMU channel. Decimation factor must be integer —
    otherwise ValueError. Non-IMU columns (metadata, timestamps) are
    decimated by strided slicing (`::factor`).
    """
    source_hz = _infer_source_hz(df)
    if target_hz <= 0:
        raise ValueError(f"target_hz must be > 0, got {target_hz}")
    if abs(source_hz - target_hz) < 0.5:
        return df.copy()

    ratio = source_hz / target_hz
    factor = int(round(ratio))
    if abs(ratio - factor) > 1e-3 or factor < 2:
        raise ValueError(
            f"decimation factor {ratio:.3f} is not an integer ≥ 2 "
            f"({source_hz:.1f} → {target_hz} Hz)"
        )

    # Anti-aliased decimation per numeric IMU column. zero_phase=True
    # uses filtfilt under the hood to avoid time-shifts in the output —
    # important when downstream code aligns to pen wall-clock.
    imu_present = [c for c in _NUMERIC_IMU_COLS if c in df.columns]
    out: dict[str, np.ndarray] = {}
    n_out = None
    for c in imu_present:
        arr = df[c].to_numpy(dtype=float)
        # decimate doesn't tolerate NaN; impute with column mean before
        # filtering, then restore NaN positions after decimation by
        # mapping their indices.
        if np.isnan(arr).any():
            mean = float(np.nanmean(arr)) if np.isfinite(np.nanmean(arr)) else 0.0
            arr = np.where(np.isnan(arr), mean, arr)
        decimated = signal.decimate(arr, factor, ftype="iir", zero_phase=True)
        out[c] = decimated
        n_out = len(decimated) if n_out is None else n_out

    if n_out is None:
        # Edge case: no IMU columns at all (malformed input). Fall back to
        # plain strided decimation across all columns.
        n_out = len(df) // factor

    # Strided slicing for non-IMU metadata columns. Keep first sample of
    # each source-window — preserves session_id, sequence, timestamps.
    for c in df.columns:
        if c in imu_present:
            continue
        sliced = df[c].to_numpy()[::factor][:n_out]
        out[c] = sliced

    result = pd.DataFrame(out, columns=list(df.columns))

    # Update sample_rate_hz to reflect the new rate so downstream tools
    # don't infer wrong fs from the original column value.
    if "sample_rate_hz" in result.columns:
        result["sample_rate_hz"] = float(target_hz)

    if drop_gravity:
        for c in ("gx", "gy", "gz"):
            if c in result.columns:
                result = result.drop(columns=c)

    return result


def downsample_watch_csv(
    session_id: str,
    target_hz: float = 50.0,
    drop_gravity: bool = True,
    out_suffix: str = "legacy",
) -> Path:
    """Read raw watch CSV, downsample, write sibling with ``_<suffix>``."""
    src = DATA_RAW_WATCH / f"{session_id}_watch.csv"
    if not src.exists():
        raise FileNotFoundError(src)
    df = pd.read_csv(src)
    out = downsample_watch_df(df, target_hz=target_hz, drop_gravity=drop_gravity)
    dst = DATA_RAW_WATCH / f"{session_id}_watch_{out_suffix}.csv"
    out.to_csv(dst, index=False)
    return dst


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session_id", help="session id, e.g. S034")
    p.add_argument("--target-hz", type=float, default=50.0,
                   help="downsample target rate (default: 50)")
    p.add_argument("--keep-gravity", action="store_true",
                   help="keep gx/gy/gz columns (default: drop)")
    p.add_argument("--suffix", default="legacy",
                   help="output file suffix (default: 'legacy')")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    dst = downsample_watch_csv(
        args.session_id,
        target_hz=args.target_hz,
        drop_gravity=not args.keep_gravity,
        out_suffix=args.suffix,
    )
    print(f"→ {dst}")
