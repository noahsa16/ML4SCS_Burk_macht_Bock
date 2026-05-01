"""Preprocessing utilities — Pen + Watch data."""

from pathlib import Path
import pandas as pd
import numpy as np

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


def merge_pen_watch(pen_path: str | Path,
                    watch_path: str | Path,
                    tolerance_ms: int = 20) -> pd.DataFrame:
    """
    Joined Pen- und Watch-Daten per Nearest-Neighbour auf Gerätezeit.
    Absolute Pen- und Watch-Timestamps werden nicht direkt verglichen, weil die
    Geräte nicht zwingend dieselbe Wallclock verwenden.
    """
    raw_watch = load_csv(watch_path)
    anchor_local_ms = _first_numeric(raw_watch, ["local_ts_ms", "server_received_ms"])
    pen = prepare_pen_data(pen_path, anchor_local_ms=anchor_local_ms).rename(
        columns={"timestamp": "ts_pen", "device_time_ms": "pen_device_time_ms"}
    )
    watch = prepare_watch_data(watch_path, anchor_local_ms=anchor_local_ms).rename(
        columns={"device_time_ms": "watch_device_time_ms"}
    )
    merged = pd.merge_asof(
        pen.sort_values("pen_device_time_ms"),
        watch.sort_values("watch_device_time_ms"),
        left_on="pen_device_time_ms", right_on="watch_device_time_ms",
        tolerance=tolerance_ms,
        direction="nearest",
    )
    return merged


if __name__ == "__main__":
    pen_files = sorted((DATA_RAW / "pen").glob("pen_log_*.csv"))
    if pen_files:
        df = prepare_pen_data(pen_files[-1])
        print(summarize_dataframe(df))
        print(df.head())
    else:
        print("Keine Pen-Logs unter data/raw/pen/ gefunden.")
