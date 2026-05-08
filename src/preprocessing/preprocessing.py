"""Preprocessing utilities — Pen + Watch data."""

from pathlib import Path
import pandas as pd
import numpy as np

from .pen_match import (
    PenMatchResult, match_pen_data, reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)

DATA_RAW   = Path(__file__).parents[2] / "data" / "raw"
DATA_PROC  = Path(__file__).parents[2] / "data" / "processed"


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
    """
    Build a session-relative timeline from device timestamps.
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
    """Bereitet Stiftdaten für Writing-vs-NotWriting auf."""
    df = load_csv(path)
    cols = ["timestamp", "x", "y", "pressure", "dot_type"]
    if "local_ts_ms" in df.columns:
        cols.append("local_ts_ms")
    df = df[cols].copy()
    df = df[(df["x"] != -1) & (df["y"] != -1)].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["device_time_ms"] = _device_aligned_time(
        df,
        "timestamp",
        ["local_ts_ms"],
        anchor_local_ms,
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


def prepare_watch_data(
    path: str | Path,
    anchor_local_ms: float | None = None,
) -> pd.DataFrame:
    """Lädt Watch-IMU-Daten und normalisiert auf die Geräte-Zeitachse."""
    df = load_csv(path)
    df = df.sort_values("ts").reset_index(drop=True)
    df["device_time_ms"] = _device_aligned_time(
        df,
        "ts",
        ["local_ts_ms", "server_received_ms"],
        anchor_local_ms,
    )
    return df


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
    """
    Joined Pen- und Watch-Daten per Nearest-Neighbour auf Gerätezeit.

    Wenn ``align_clocks=True`` (default), wird zuerst der pen↔IMU
    Zeitversatz via Varianz-Minimierung über Stroke-Fenstern bestimmt
    (siehe :mod:`pen_match`) und auf die Pen-Wallclock angewandt, bevor
    das ``merge_asof`` läuft. Das Ergebnis hat zusätzlich die Spalten
    ``pen_clock_offset_sec`` (angewandter Shift) und
    ``pen_clock_sigma`` (Confidence-Z-Score) als konstante Annotationen.
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
    # prepare_pen_data needs a path; reuse the in-memory raw_pen via a
    # temporary detour — safer than refactoring its signature.
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


def _prepare_pen_from_df(df: pd.DataFrame, anchor_local_ms: float | None) -> pd.DataFrame:
    """In-memory variant of prepare_pen_data — same logic, takes a DataFrame."""
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


if __name__ == "__main__":
    pen_files = sorted((DATA_RAW / "pen").glob("pen_log_*.csv"))
    if pen_files:
        df = prepare_pen_data(pen_files[-1])
        print(summarize_dataframe(df))
        print(df.head())
    else:
        print("Keine Pen-Logs unter data/raw/pen/ gefunden.")
