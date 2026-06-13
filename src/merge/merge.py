"""Watch + Pen zu einem watch-basierten gelabelten Dataset zusammenführen.

Ablauf in ``merge_watch_pen()``:

  1. Rohe CSVs einlesen
  2. δ schätzen (via :mod:`src.alignment`)
  3. Wenn σ ≤ -2 (Confidence ok): pen.local_ts_ms += δ·1000
     Wenn σ > -2 (flache Kurve): δ verwerfen, ohne Shift weitermachen
  4. ``pd.merge_asof`` mit **Watch als Basis**, Pen-Aktivität als Label:
     - innerhalb ±``label_tol_ms`` der nächste Pen-``dot_type`` ∈
       {PEN_DOWN, PEN_MOVE} → ``label_writing = 1``
     - sonst → ``label_writing = 0`` (umfasst auch Pen-Lücken, in denen
       der Pen gar nichts berichtet → "nicht schreiben")
  5. δ und σ als ``df.attrs`` für Downstream-Diagnose anhängen

Output: 1 Zeile pro Watch-Sample (alle Watch-Spalten + ``label_writing``).
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.alignment import (
    PenMatchResult,
    match_pen_data,
    reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)
from .prep import load_csv

WRITING_DOT_TYPES = ("PEN_DOWN", "PEN_MOVE")

# Override hook for tests; production resolves to data/raw/markers.
_MARKERS_DIR_OVERRIDE: Path | None = None
_SESSION_FROM_PATH = re.compile(r"^(S\d+)_(?:pen|watch)\.csv$")


def _markers_dir() -> Path:
    if _MARKERS_DIR_OVERRIDE is not None:
        return _MARKERS_DIR_OVERRIDE
    return Path(__file__).parents[2] / "data" / "raw" / "markers"


def _session_id_from_path(p: str | Path) -> str | None:
    m = _SESSION_FROM_PATH.match(Path(p).name)
    return m.group(1) if m else None


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


def merge_watch_pen(
    pen_path: str | Path,
    watch_path: str | Path,
    label_tol_ms: int = 40,
    align_clocks: bool = True,
    sigma_threshold: float = -2.0,
) -> pd.DataFrame:
    """Watch-base merge: jedes Watch-Sample bekommt ein Label.

    Pen-Lücken (kein Pen-Sample in ±``label_tol_ms``) → label 0. Das ist
    die Grundlage für den Writing-Detektor, der auf der Watch allein läuft.

    Standard-Toleranz 40 ms = ~2× Watch-Periode bei 50 Hz; kleine Jitter
    werden geschluckt, aber echte Pen-freie Phasen bleiben Label 0.

    Result-DataFrame trägt ``pen_clock_offset_sec`` und ``pen_clock_sigma``
    als ``df.attrs`` für Diagnose.
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

    if "local_ts_ms" not in raw_watch.columns:
        raise ValueError("Watch CSV is missing local_ts_ms — cannot align.")
    if "local_ts_ms" not in raw_pen.columns:
        raise ValueError("Pen CSV is missing local_ts_ms — legacy log not supported.")

    watch = raw_watch.copy()
    watch["local_ts_ms"] = pd.to_numeric(watch["local_ts_ms"], errors="coerce")
    # Why: Join-Achse muss exakt die Achse sein, gegen die δ optimiert wurde
    # (match_pen_data nutzt reconstruct_watch_wall_clock = per-Sample `ts`).
    # local_ts_ms ist Batch-Ankunftszeit: alle Samples eines POSTs teilen
    # einen Wert (Labels batch-quantisiert), und Spill-Drain-Strecken kommen
    # Minuten verspätet an (S043: 5,3 % der Samples >2,5 s, max 13,6 s —
    # Forensik 2026-06-12). Fallback auf local_ts_ms nur ohne ts-Spalte.
    if "ts" in watch.columns:
        wall = pd.to_numeric(watch["ts"], errors="coerce")
        watch["_wall_ms"] = wall.fillna(watch["local_ts_ms"])
    else:
        watch["_wall_ms"] = watch["local_ts_ms"]
    # Why: stable sort preserves arrival order on exact-tie timestamps.
    # Unstable sort scrambled feature inputs in a way live inference
    # doesn't replicate -> 2026-05-25 diagnosis of the live-vs-offline
    # accuracy gap.
    watch = watch.dropna(subset=["_wall_ms"]).sort_values("_wall_ms", kind="stable")
    watch["_wall_ms"] = watch["_wall_ms"].astype(float)

    pen = raw_pen.copy()
    pen["_wall_ms"] = (
        pd.to_numeric(pen["local_ts_ms"], errors="coerce") + delta_sec * 1000.0
    )
    pen = pen.dropna(subset=["_wall_ms"]).sort_values("_wall_ms", kind="stable")
    pen["_wall_ms"] = pen["_wall_ms"].astype(float)
    pen["pen_writing"] = pen["dot_type"].isin(WRITING_DOT_TYPES).astype(int)
    pen_slim = pen[["_wall_ms", "pen_writing"]]

    merged = pd.merge_asof(
        watch,
        pen_slim,
        on="_wall_ms",
        tolerance=float(label_tol_ms),
        direction="nearest",
    )
    # Why: kein Pen-Sample in Toleranz → fillna(0) heisst "nicht schreiben".
    merged["label_writing"] = merged["pen_writing"].fillna(0).astype(int)
    merged = merged.drop(columns=["pen_writing"]).reset_index(drop=True)
    merged.attrs["pen_clock_offset_sec"] = delta_sec
    merged.attrs["pen_clock_sigma"] = sigma

    # Why: Study Mode emits per-session task markers; sessions without a
    # markers CSV (legacy + non-study) merge unchanged for backward-compat.
    session_id = _session_id_from_path(pen_path) or _session_id_from_path(watch_path)
    if session_id is not None:
        markers_path = _markers_dir() / f"{session_id}_markers.csv"
        if markers_path.exists():
            markers = pd.read_csv(markers_path)
            boundaries = markers[markers["event"].isin(
                ["task_start", "task_end", "abort", "study_end"]
            )].copy()
            boundaries["timestamp_ms"] = boundaries["timestamp_ms"].astype("int64")
            boundaries = boundaries.sort_values("timestamp_ms").reset_index(drop=True)

            intervals: list[dict] = []
            active: dict | None = None
            for _, row in boundaries.iterrows():
                if row["event"] == "task_start":
                    active = {
                        "start": int(row["timestamp_ms"]),
                        "task_id": row.get("task_id", ""),
                        "task_category": row.get("task_category", ""),
                    }
                elif row["event"] in ("task_end", "abort", "study_end") and active is not None:
                    active["end"] = int(row["timestamp_ms"])
                    intervals.append(active)
                    active = None

            merged["task_id"] = pd.NA
            merged["task_category"] = pd.NA
            # Why: Marker tragen Server-Wall-Clock; die Watch-`ts`-Achse ist
            # NTP-nah (<100 ms Skew) — für Minuten-lange Task-Blöcke exakt
            # genug, und anders als local_ts_ms nicht durch Spill verzerrt.
            for iv in intervals:
                mask = (
                    (merged["_wall_ms"] >= iv["start"])
                    & (merged["_wall_ms"] < iv["end"])
                )
                merged.loc[mask, "task_id"] = iv["task_id"]
                merged.loc[mask, "task_category"] = iv["task_category"]

    return merged.drop(columns=["_wall_ms"])
