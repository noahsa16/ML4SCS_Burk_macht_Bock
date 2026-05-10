"""Pro-Stream-Aufbereitung der rohen CSVs (Pen, Watch).

Helfer-Modul für :mod:`src.merge.merge`. Liest eine einzelne CSV ein,
normalisiert die Zeitachse auf Session-relative ms und leitet pro-Sample-
Features ab (für Pen: distance, speed, label_writing).

Public functions
----------------
* ``load_csv(path)``                — read_csv-Wrapper
* ``prepare_pen_data(path, …)``     — Pen-CSV → cleaned DataFrame
* ``prepare_watch_data(path, …)``   — Watch-CSV → DataFrame mit
                                      device_time_ms-Spalte
* ``summarize_dataframe(df)``       — Quick-Look-Zusammenfassung

Internal helpers (von ``merge.merge_pen_watch`` direkt benutzt)
---------------------------------------------------------------
* ``_prepare_pen_from_df`` / ``_prepare_watch_from_df``
* ``_device_aligned_time``
* ``_first_numeric``
"""

from pathlib import Path

import numpy as np
import pandas as pd


def load_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def summarize_dataframe(df: pd.DataFrame) -> dict:
    return {
        "rows": df.shape[0],
        "columns": df.shape[1],
        "column_names": list(df.columns),
        "missing_values": df.isna().sum().to_dict(),
    }


def _first_numeric(df: pd.DataFrame, columns: list[str]) -> float | None:
    for col in columns:
        if col not in df.columns:
            continue
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if not values.empty:
            return float(values.iloc[0])
    return None


def _device_aligned_time(
    df: pd.DataFrame,
    source_col: str,
    local_cols: list[str],
    anchor_local_ms: float | None = None,
) -> pd.Series:
    """Build a session-relative timeline from device timestamps.

    Server/local time is only used once as a coarse stream offset anchor.
    """
    source = pd.to_numeric(df[source_col], errors="coerce")
    valid_source = source.dropna()
    if valid_source.empty:
        return pd.Series(np.nan, index=df.index)
    source_start = valid_source.iloc[0]
    relative = source - source_start
    local_start = _first_numeric(df, local_cols)
    if anchor_local_ms is not None and local_start is not None:
        return relative + (local_start - anchor_local_ms)
    return relative


def prepare_pen_data(
    path: str | Path,
    anchor_local_ms: float | None = None,
) -> pd.DataFrame:
    """Load + clean pen CSV, derive per-row features and label_writing."""
    df = load_csv(path)
    return _prepare_pen_from_df(df, anchor_local_ms)


def prepare_watch_data(
    path: str | Path,
    anchor_local_ms: float | None = None,
) -> pd.DataFrame:
    """Load watch IMU CSV and normalize onto device-time axis."""
    df = load_csv(path)
    return _prepare_watch_from_df(df, anchor_local_ms)


def _prepare_pen_from_df(df: pd.DataFrame, anchor_local_ms: float | None) -> pd.DataFrame:
    cols = ["timestamp", "x", "y", "pressure", "dot_type"]
    if "local_ts_ms" in df.columns:
        cols.append("local_ts_ms")
    df = df[cols].copy()
    df = df[(df["x"] != -1) & (df["y"] != -1)].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["device_time_ms"] = _device_aligned_time(
        df, "timestamp", ["local_ts_ms"], anchor_local_ms,
    )
    df["dt"]       = df["device_time_ms"].diff() / 1000.0
    df["dx"]       = df["x"].diff()
    df["dy"]       = df["y"].diff()
    df["distance"] = np.sqrt(df["dx"] ** 2 + df["dy"] ** 2)
    df["speed"]    = (df["distance"] / df["dt"]).replace([np.inf, -np.inf], np.nan)
    df = df.dropna().reset_index(drop=True)
    df["label_writing"] = df["dot_type"].apply(
        lambda x: 1 if x in ["PEN_DOWN", "PEN_MOVE"] else 0
    )
    return df[[
        "timestamp", "device_time_ms", "pressure", "distance", "speed",
        "label_writing",
    ]].copy()


def _prepare_watch_from_df(df: pd.DataFrame, anchor_local_ms: float | None) -> pd.DataFrame:
    df = df.sort_values("ts").reset_index(drop=True)
    df["device_time_ms"] = _device_aligned_time(
        df, "ts", ["local_ts_ms", "server_received_ms"], anchor_local_ms,
    )
    return df
