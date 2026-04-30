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


def prepare_pen_data(path: str | Path) -> pd.DataFrame:
    """Bereitet Stiftdaten für Writing-vs-NotWriting auf."""
    df = load_csv(path)
    df = df[["timestamp", "x", "y", "pressure", "dot_type"]].copy()
    df = df[(df["x"] != -1) & (df["y"] != -1)].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["dt"]       = df["timestamp"].diff() / 1000.0
    df["dx"]       = df["x"].diff()
    df["dy"]       = df["y"].diff()
    df["distance"] = np.sqrt(df["dx"] ** 2 + df["dy"] ** 2)
    df["speed"]    = (df["distance"] / df["dt"]).replace([np.inf, -np.inf], np.nan)
    df = df.dropna().reset_index(drop=True)
    df["label_writing"] = df["dot_type"].apply(
        lambda x: 1 if x in ["PEN_DOWN", "PEN_MOVE"] else 0
    )
    return df[["timestamp", "pressure", "distance", "speed", "label_writing"]].copy()


def prepare_watch_data(path: str | Path) -> pd.DataFrame:
    """Lädt Watch-IMU-Daten und normalisiert den Timestamp."""
    df = load_csv(path)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def merge_pen_watch(pen_path: str | Path,
                    watch_path: str | Path,
                    tolerance_ms: int = 20) -> pd.DataFrame:
    """Joined Pen- und Watch-Daten per Nearest-Neighbour auf ±tolerance_ms."""
    pen   = prepare_pen_data(pen_path).rename(columns={"timestamp": "ts_pen"})
    watch = prepare_watch_data(watch_path)
    merged = pd.merge_asof(
        pen.sort_values("ts_pen"),
        watch.sort_values("ts"),
        left_on="ts_pen", right_on="ts",
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
