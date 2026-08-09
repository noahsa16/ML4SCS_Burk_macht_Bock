"""Shared helpers: assemble our canonical watch/pen DataFrames.

Both pipeline-specific loaders (ege_pipeline.py, sensorlogger_pipeline.py)
compute a handful of core columns from their own raw format, then hand off
to assemble_watch_df / assemble_pen_df here to pad out the full
WATCH_FIELDNAMES / PEN_FIELDNAMES schema so the result is a drop-in for
src.merge.merge.merge_watch_pen and src.features.windows.build_windows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.server.config import WATCH_FIELDNAMES  # noqa: E402
from src.pen_schema import PEN_FIELDNAMES  # noqa: E402

# Our dot_type vocabulary (src/alignment/pen_match.py, src/merge/merge.py).
PEN_DOWN = "PEN_DOWN"
PEN_MOVE = "PEN_MOVE"
PEN_UP = "PEN_UP"
PEN_HOVER = "PEN_HOVER"


def assemble_watch_df(
    session_id: str,
    source: str,
    ts_ms: np.ndarray,
    ax: np.ndarray, ay: np.ndarray, az: np.ndarray,
    rx: np.ndarray, ry: np.ndarray, rz: np.ndarray,
    gx: np.ndarray | None = None,
    gy: np.ndarray | None = None,
    gz: np.ndarray | None = None,
    qx: np.ndarray | None = None,
    qy: np.ndarray | None = None,
    qz: np.ndarray | None = None,
    qw: np.ndarray | None = None,
    sample_rate_hz: float = 100.0,
) -> pd.DataFrame:
    n = len(ts_ms)
    ts_ms = np.asarray(ts_ms, dtype=np.int64)
    local_ts = pd.to_datetime(ts_ms, unit="ms", utc=True).astype(str)

    cols = {
        "local_ts": local_ts,
        "local_ts_ms": ts_ms,
        "session_id": session_id,
        "sequence": np.arange(n),
        "sample_rate_hz": sample_rate_hz,
        "watch_sent_at": np.nan,
        "phone_received_at": np.nan,
        "server_received_ms": np.nan,
        "source": source,
        "ts": ts_ms,
        "ax": ax, "ay": ay, "az": az,
        "rx": rx, "ry": ry, "rz": rz,
        "gx": gx if gx is not None else np.nan,
        "gy": gy if gy is not None else np.nan,
        "gz": gz if gz is not None else np.nan,
        "qx": qx if qx is not None else np.nan,
        "qy": qy if qy is not None else np.nan,
        "qz": qz if qz is not None else np.nan,
        "qw": qw if qw is not None else np.nan,
    }
    df = pd.DataFrame(cols)
    return df[WATCH_FIELDNAMES]


def assemble_pen_df(
    local_ts_ms: np.ndarray,
    dot_type: np.ndarray,
    x: np.ndarray | None = None,
    y: np.ndarray | None = None,
    pressure: np.ndarray | None = None,
    tilt_x: np.ndarray | None = None,
    tilt_y: np.ndarray | None = None,
    timestamp: np.ndarray | None = None,
    owner: str = "",
) -> pd.DataFrame:
    n = len(local_ts_ms)
    local_ts_ms = np.asarray(local_ts_ms, dtype=np.int64)
    local_ts = pd.to_datetime(local_ts_ms, unit="ms", utc=True).astype(str)

    def _fill(v, default):
        if v is None:
            return np.full(n, default)
        return pd.Series(v).fillna(default).to_numpy()

    cols = {
        "local_ts": local_ts,
        "local_ts_ms": local_ts_ms,
        "timestamp": _fill(timestamp, np.nan),
        "x": _fill(x, -1.0),
        "y": _fill(y, -1.0),
        "pressure": _fill(pressure, np.nan),
        "dot_type": dot_type,
        "tilt_x": _fill(tilt_x, np.nan),
        "tilt_y": _fill(tilt_y, np.nan),
        "section": "",
        "owner": owner,
        "note": "",
        "page": np.nan,
    }
    df = pd.DataFrame(cols)
    return df[PEN_FIELDNAMES]
