"""Modell-Training."""

from pathlib import Path
import pandas as pd
from src.preprocessing import merge_pen_watch

DATA_RAW  = Path(__file__).parents[2] / "data" / "raw"
DATA_PROC = Path(__file__).parents[2] / "data" / "processed"


def train(pen_csv: Path, watch_csv: Path) -> None:
    df = merge_pen_watch(pen_csv, watch_csv)
    print(f"Merged dataset: {len(df)} Zeilen")
    # TODO: Feature-Engineering + Modell hier
    out = DATA_PROC / "merged_dataset.csv"
    df.to_csv(out, index=False)
    print(f"Gespeichert: {out}")


if __name__ == "__main__":
    pen_files   = sorted((DATA_RAW / "pen").glob("pen_log_*.csv"))
    watch_files = sorted((DATA_RAW / "watch").glob("*.csv"))
    if pen_files and watch_files:
        train(pen_files[-1], watch_files[-1])
    else:
        print("Pen- oder Watch-Daten fehlen noch.")
