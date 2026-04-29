"""Basic preprocessing utilities for the semester project."""

from pathlib import Path
import pandas as pd
import numpy as np


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a CSV file into a pandas DataFrame."""
    return pd.read_csv(path)


def summarize_dataframe(df: pd.DataFrame) -> dict:
    """Return a simple summary of the dataframe."""
    return {
        "rows": df.shape[0],
        "columns": df.shape[1],
        "column_names": list(df.columns),
        "missing_values": df.isna().sum().to_dict(),
    }


def prepare_pen_data(path: str | Path) -> pd.DataFrame:

    """Prepare Smart Pen data for a simple writing vs. not-writing task."""

    df = load_csv(path)
    df = df[["timestamp", "x", "y", "pressure", "dot_type"]].copy()
    df = df[(df["x"] != -1) & (df["y"] != -1)].copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["dt"] = df["timestamp"].diff() / 1000.0
    df["dx"] = df["x"].diff()
    df["dy"] = df["y"].diff()
    df["distance"] = np.sqrt(df["dx"] ** 2 + df["dy"] ** 2)
    df["speed"] = df["distance"] / df["dt"]
    df["speed"] = df["speed"].replace([np.inf, -np.inf], np.nan)
    df = df.dropna().reset_index(drop=True)
    df["label_writing"] = df["dot_type"].apply(
        lambda x: 1 if x in ["PEN_DOWN", "PEN_MOVE"] else 0

    )

    return df[["pressure", "distance", "speed", "label_writing"]].copy()


if __name__ == "__main__":
    csv_path = "data/experiments/pen_log_20260423_090846.csv"
    prepared_df = prepare_pen_data(csv_path)
    print("Prepared data summary:")
    print(summarize_dataframe(prepared_df))
    print(prepared_df.head())
    print(prepared_df["label_writing"].value_counts())