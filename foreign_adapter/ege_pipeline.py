"""Adapter for data_ege_pipeline (custom watchOS app, direct-to-Supabase).

Raw schema quirk (see memory/foreign_swiss_dataset.md): imu_samples_rows.csv
columns are named ax,ay,az,gx,gy,gz,qw,qx,qy,qz — but gx/gy/gz here is
rotationRate (gyroscope), NOT gravity like in our own schema, and ax/ay/az
is total acceleration (gravity included), not userAcceleration. Verified
via magnitude: ||ax,ay,az|| ~= 1.0 +/- 0.07 (gravity-dominated), ||gx,gy,gz||
varies 0-2+ (not unit-norm, so it's angular rate). Gravity + userAcceleration
are reconstructed from the quaternion instead (gravity_quat.py).

Pen ground truth is a separate pen_events.csv (Moleskine-style dot stream):
pen_dot = continuous stroke sample (-> PEN_MOVE), pen_down/pen_up bracket a
stroke, pen_paper_info carries no coordinates (-> PEN_HOVER, dropped by
strokes_from_dot_types same as our own PEN_HOVER rows).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .common import PEN_DOWN, PEN_HOVER, PEN_MOVE, PEN_UP, assemble_pen_df, assemble_watch_df
from .gravity_quat import gravity_from_quaternion

_DOT_TYPE_MAP = {
    "pen_down": PEN_DOWN,
    "pen_dot": PEN_MOVE,
    "pen_up": PEN_UP,
    "pen_paper_info": PEN_HOVER,
}


def load_ege_session(session_dir: Path, session_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read imu_samples_rows.csv + pen_events.csv, return (watch_df, pen_df)."""
    imu = pd.read_csv(session_dir / "imu_samples_rows.csv")
    imu = imu.sort_values("t_ms", kind="stable").reset_index(drop=True)

    grav = gravity_from_quaternion(
        imu["qx"].to_numpy(), imu["qy"].to_numpy(),
        imu["qz"].to_numpy(), imu["qw"].to_numpy(),
    )
    user_accel = imu[["ax", "ay", "az"]].to_numpy() - grav

    watch_df = assemble_watch_df(
        session_id=session_id,
        source="foreign_ege",
        ts_ms=imu["t_ms"].round().to_numpy(),
        ax=user_accel[:, 0], ay=user_accel[:, 1], az=user_accel[:, 2],
        # Why: their gx/gy/gz is rotationRate, not gravity — see module docstring.
        rx=imu["gx"].to_numpy(), ry=imu["gy"].to_numpy(), rz=imu["gz"].to_numpy(),
        gx=grav[:, 0], gy=grav[:, 1], gz=grav[:, 2],
        qx=imu["qx"].to_numpy(), qy=imu["qy"].to_numpy(),
        qz=imu["qz"].to_numpy(), qw=imu["qw"].to_numpy(),
        sample_rate_hz=100.0,
    )

    pen = pd.read_csv(session_dir / "pen_events.csv")
    pen = pen.sort_values("t_ms", kind="stable").reset_index(drop=True)
    dot_type = pen["type"].map(_DOT_TYPE_MAP)
    unmapped = pen["type"][dot_type.isna()].unique()
    if len(unmapped):
        raise ValueError(f"Unmapped pen event types in {session_dir}: {unmapped}")

    pen_df = assemble_pen_df(
        local_ts_ms=pen["t_ms"].round().to_numpy(),
        dot_type=dot_type.to_numpy(),
        x=pen["x"].to_numpy(), y=pen["y"].to_numpy(),
        pressure=pen["force"].to_numpy(),
        owner="foreign_ege",
    )
    return watch_df, pen_df
