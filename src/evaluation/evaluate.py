"""Modell-Evaluation.

Aktuell ein Placeholder, der ein per-Session gemergtes Dataset (Output
von ``python -m src.merge``) einliest und die Label-Verteilung ausgibt.
Echte Test-Metriken: ``src/training/train_loso.py`` (Headline,
cross-subject/-session) oder ``src/training/within_session/train_rf.py``
(within-session 80/20, Debug/Feature-Iteration).
"""

from pathlib import Path

import pandas as pd

DATA_PROC = Path(__file__).parents[2] / "data" / "processed"


def evaluate(session_id: str = "S029") -> None:
    path = DATA_PROC / f"{session_id}_merged.csv"
    if not path.exists():
        print(f"Dataset nicht gefunden: {path}")
        return
    df = pd.read_csv(path)
    print(f"Session {session_id}: {len(df)} Watch-Samples")
    if "label_writing" in df.columns:
        print(df["label_writing"].value_counts())
    # TODO: Metriken, Plots etc.


if __name__ == "__main__":
    import sys

    evaluate(sys.argv[1] if len(sys.argv) > 1 else "S029")
