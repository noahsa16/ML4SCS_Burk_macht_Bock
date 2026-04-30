"""Modell-Evaluation."""

from pathlib import Path
import pandas as pd

DATA_PROC = Path(__file__).parents[2] / "data" / "processed"


def evaluate(dataset_csv: Path | None = None) -> None:
    path = dataset_csv or DATA_PROC / "merged_dataset.csv"
    if not path.exists():
        print(f"Dataset nicht gefunden: {path}")
        return
    df = pd.read_csv(path)
    print(f"Zeilen: {len(df)}")
    if "label_writing" in df.columns:
        print(df["label_writing"].value_counts())
    # TODO: Metriken, Plots etc.


if __name__ == "__main__":
    evaluate()
