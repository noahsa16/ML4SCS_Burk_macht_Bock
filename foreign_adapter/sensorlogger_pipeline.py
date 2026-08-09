"""Adapter for data_ege_sensorlogger_pipeline (iOS SensorLogger app export).

WristMotion.csv already separates rotationRate / gravity / acceleration /
quaternion — a 1:1 semantic match to our own Modern-Pool schema (verified:
gravity magnitude == 1.000 +/- 4e-8, confirms it's the same CMDeviceMotion
decomposition CoreMotion gives us natively). Only column renaming needed,
no reconstruction.

Pen ground truth is NOT in the empty Annotation.csv — it's embedded as
pen_down/pen_move/pen_up events in the session JSON (same web-app event
log format as data_ege_pipeline). Each event's outer t_ms is already an
absolute, wall-clock-aligned epoch-ms timestamp (verified against
session.started_at_ms + t_session_ms); payload.timestamp is the pen
device's own (unaligned) clock, kept only as metadata like our own
pen_logger.py distinguishes local_ts_ms (capture wall-clock) from
timestamp (raw pen clock).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import PEN_DOWN, PEN_MOVE, PEN_UP, assemble_pen_df, assemble_watch_df

_DOT_TYPE_MAP = {
    "pen_down": PEN_DOWN,
    "pen_move": PEN_MOVE,
    "pen_up": PEN_UP,
}


def load_sensorlogger_session(session_dir: Path, session_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read WristMotion.csv + the session JSON's pen events, return (watch_df, pen_df)."""
    wm = pd.read_csv(session_dir / "WristMotion.csv")
    wm = wm.sort_values("time", kind="stable").reset_index(drop=True)
    ts_ms = (wm["time"].to_numpy(dtype=np.float64) / 1e6).round()

    watch_df = assemble_watch_df(
        session_id=session_id,
        source="foreign_sensorlogger",
        ts_ms=ts_ms,
        ax=wm["accelerationX"].to_numpy(), ay=wm["accelerationY"].to_numpy(), az=wm["accelerationZ"].to_numpy(),
        rx=wm["rotationRateX"].to_numpy(), ry=wm["rotationRateY"].to_numpy(), rz=wm["rotationRateZ"].to_numpy(),
        gx=wm["gravityX"].to_numpy(), gy=wm["gravityY"].to_numpy(), gz=wm["gravityZ"].to_numpy(),
        qx=wm["quaternionX"].to_numpy(), qy=wm["quaternionY"].to_numpy(),
        qz=wm["quaternionZ"].to_numpy(), qw=wm["quaternionW"].to_numpy(),
        sample_rate_hz=100.0,
    )

    json_paths = list(session_dir.glob("*.json"))
    if len(json_paths) != 1:
        raise ValueError(f"Expected exactly one session JSON in {session_dir}, found {json_paths}")
    session_json = json.loads(json_paths[0].read_text())
    events = [e for e in session_json["events"] if e["event"] in _DOT_TYPE_MAP]
    if not events:
        raise ValueError(f"No pen_down/pen_move/pen_up events found in {json_paths[0]}")

    local_ts_ms = np.array([e["t_ms"] for e in events]).round()
    dot_type = np.array([_DOT_TYPE_MAP[e["event"]] for e in events])
    x = np.array([e["payload"].get("x", np.nan) for e in events], dtype=float)
    y = np.array([e["payload"].get("y", np.nan) for e in events], dtype=float)
    pressure = np.array([e["payload"].get("force", np.nan) for e in events], dtype=float)
    tilt_x = np.array([e["payload"].get("tilt", {}).get("x", np.nan) for e in events], dtype=float)
    tilt_y = np.array([e["payload"].get("tilt", {}).get("y", np.nan) for e in events], dtype=float)
    timestamp = np.array([e["payload"].get("timestamp", np.nan) for e in events], dtype=float)

    order = np.argsort(local_ts_ms, kind="stable")
    pen_df = assemble_pen_df(
        local_ts_ms=local_ts_ms[order],
        dot_type=dot_type[order],
        x=x[order], y=y[order],
        pressure=pressure[order],
        tilt_x=tilt_x[order], tilt_y=tilt_y[order],
        timestamp=timestamp[order],
        owner="foreign_sensorlogger",
    )
    return watch_df, pen_df
