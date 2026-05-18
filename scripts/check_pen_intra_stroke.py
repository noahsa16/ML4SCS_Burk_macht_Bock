"""Check pen sample density INSIDE strokes vs between strokes.

If BLE is reliable, the inter-sample interval inside a single stroke
should be tight (~12-15 ms = 65-80 Hz). If BLE drops samples during
strokes, we'd see elevated p90/p99 intervals or a fat tail above 20 ms.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SESSIONS = ["S007", "S008", "S009", "S011"]
SESSION_TO_PERSON = {"S007": "Noah", "S008": "P01", "S009": "P02", "S011": "P03"}


def analyze(session_id: str) -> None:
    person = SESSION_TO_PERSON[session_id]
    pen = pd.read_csv(ROOT / "data" / "raw" / "pen" / f"{session_id}_pen.csv")
    pen = pen.dropna(subset=["local_ts_ms"]).copy()
    pen["local_ts_ms"] = pen["local_ts_ms"].astype(float)
    pen = pen.sort_values("local_ts_ms").reset_index(drop=True)

    # A "stroke" = consecutive run of PEN_DOWN/PEN_MOVE events
    writing = pen["dot_type"].isin(["PEN_DOWN", "PEN_MOVE"])
    # stroke_id increments each time writing goes from False→True
    pen["stroke_id"] = (writing & ~writing.shift(fill_value=False)).cumsum().where(writing)

    # Per-stroke stats
    strokes = pen.dropna(subset=["stroke_id"]).groupby("stroke_id")
    intra_dts: list[float] = []
    stroke_durations: list[float] = []
    stroke_lengths: list[int] = []
    for _, g in strokes:
        if len(g) < 2:
            continue
        dts = np.diff(g["local_ts_ms"].to_numpy())
        intra_dts.extend(dts.tolist())
        stroke_durations.append(g["local_ts_ms"].iloc[-1] - g["local_ts_ms"].iloc[0])
        stroke_lengths.append(len(g))

    intra = np.array(intra_dts)
    durs = np.array(stroke_durations)

    print(f"\n=== {person} ({session_id}) — intra-stroke pen density ===")
    print(f"  Strokes: {len(stroke_durations)}")
    print(f"  Total pen samples: {len(pen)}  (DOWN/MOVE only: {writing.sum()})")
    print(f"  Total writing time (sum of stroke durations): {durs.sum()/1000:.1f}s")
    print(f"  Median stroke duration: {np.median(durs):.0f} ms")
    print()
    print(f"  Inter-sample Δt INSIDE strokes:")
    print(f"    median={np.median(intra):.1f}ms  "
          f"mean={intra.mean():.1f}ms  "
          f"p90={np.percentile(intra, 90):.1f}ms  "
          f"p99={np.percentile(intra, 99):.1f}ms  "
          f"max={intra.max():.0f}ms")
    # BLE drop indicator: fraction of intra-stroke gaps > 30 ms
    suspicious = (intra > 30).mean() * 100
    very_suspicious = (intra > 50).mean() * 100
    print(f"    Δt > 30 ms (suspicious): {suspicious:.2f}%  "
          f"  Δt > 50 ms (likely drop): {very_suspicious:.2f}%")
    # Effective sample rate within strokes
    if intra.size:
        eff_hz = 1000.0 / np.median(intra)
        print(f"    Effective intra-stroke sample rate: {eff_hz:.1f} Hz")


def main() -> None:
    targets = sys.argv[1:] or SESSIONS
    for sid in targets:
        analyze(sid)


if __name__ == "__main__":
    main()
