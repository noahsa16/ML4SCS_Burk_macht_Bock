"""Sanity-check the sample-level watch↔pen merge.

Tests whether the merge_asof step is producing correct 1-to-1 pairings:
  1. fraction of watch samples that got matched to a pen sample at all
  2. distribution of |Δt| between matched pairs (close to 0 = good)
  3. compare merged label_writing rate to raw pen DOWN/MOVE rate
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.merge.merge import merge_watch_pen  # type: ignore

SESSIONS = ["S007", "S008", "S009", "S011"]
SESSION_TO_PERSON = {"S007": "Noah", "S008": "P01", "S009": "P02", "S011": "P03"}
TOL_MS = 40.0


def analyze(session_id: str) -> None:
    person = SESSION_TO_PERSON[session_id]
    watch_path = ROOT / "data" / "raw" / "watch" / f"{session_id}_watch.csv"
    pen_path = ROOT / "data" / "raw" / "pen" / f"{session_id}_pen.csv"

    merged = merge_watch_pen(pen_path, watch_path)
    delta_sec = merged.attrs["pen_clock_offset_sec"]
    sigma = merged.attrs["pen_clock_sigma"]

    raw_pen = pd.read_csv(pen_path).dropna(subset=["local_ts_ms"]).copy()
    raw_pen["local_ts_ms"] = raw_pen["local_ts_ms"].astype(float) + delta_sec * 1000.0
    raw_pen = raw_pen.sort_values("local_ts_ms").reset_index(drop=True)
    raw_pen["pen_writing"] = raw_pen["dot_type"].isin(["PEN_DOWN", "PEN_MOVE"]).astype(int)

    watch_ts = merged["local_ts_ms"].to_numpy().astype(float)
    pen_ts = raw_pen["local_ts_ms"].to_numpy()

    # Δt from each watch sample to its nearest pen sample (no tolerance)
    idx = np.searchsorted(pen_ts, watch_ts)
    left = np.clip(idx - 1, 0, len(pen_ts) - 1)
    right = np.clip(idx, 0, len(pen_ts) - 1)
    dt_left = np.abs(watch_ts - pen_ts[left])
    dt_right = np.abs(watch_ts - pen_ts[right])
    nearest_dt = np.minimum(dt_left, dt_right)
    within_tol = nearest_dt <= TOL_MS

    raw_pen_writing_pct = raw_pen["pen_writing"].mean() * 100
    merged_writing_pct = merged["label_writing"].mean() * 100

    # Pen-density check: how long are the gaps between consecutive pen samples?
    pen_gaps = np.diff(pen_ts)

    print(f"\n=== {person} ({session_id})   δ={delta_sec:+.3f}s  σ={sigma:.2f} ===")
    print(f"  Watch samples:            {len(watch_ts)}")
    print(f"  Pen samples:              {len(pen_ts)}")
    print(f"  Watch median Δt:          {np.median(np.diff(watch_ts)):.1f} ms  "
          f"(50 Hz expected)")
    print(f"  Pen median Δt:            {np.median(pen_gaps):.1f} ms")
    print(f"  Pen Δt p99 / max:         {np.percentile(pen_gaps, 99):.0f} ms / {pen_gaps.max():.0f} ms")
    print()
    print(f"  Watch samples within ±{TOL_MS:.0f}ms of a pen sample: "
          f"{within_tol.mean()*100:.1f}%  ({within_tol.sum()}/{len(watch_ts)})")
    print(f"  Watch samples OUTSIDE tolerance (auto-labeled 0): "
          f"{(~within_tol).mean()*100:.1f}%")
    print()
    print(f"  Δt watch→nearest pen (all watch samples):")
    print(f"    median={np.median(nearest_dt):.1f}ms  "
          f"p90={np.percentile(nearest_dt, 90):.1f}ms  "
          f"p99={np.percentile(nearest_dt, 99):.1f}ms  max={nearest_dt.max():.0f}ms")
    print(f"  Δt watch→nearest pen (matched within tol only):")
    print(f"    median={np.median(nearest_dt[within_tol]):.1f}ms  "
          f"p90={np.percentile(nearest_dt[within_tol], 90):.1f}ms  "
          f"p99={np.percentile(nearest_dt[within_tol], 99):.1f}ms")
    print()
    print(f"  Pen DOWN/MOVE rate (raw):       {raw_pen_writing_pct:.1f}%")
    print(f"  Merged label_writing rate:      {merged_writing_pct:.1f}%")
    print(f"  Gap (label coverage):           {raw_pen_writing_pct - merged_writing_pct:+.1f} pp")


def main() -> None:
    targets = sys.argv[1:] or SESSIONS
    for sid in targets:
        analyze(sid)


if __name__ == "__main__":
    main()
