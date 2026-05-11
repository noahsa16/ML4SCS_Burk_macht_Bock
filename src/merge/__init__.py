"""Watch + Pen CSV-Merge auf Watch-Basis.

Pipeline-Schritt 2:
    raw CSVs  →  alignment  →  [merge]  →  (features)  →  (train)

Was das Modul macht
-------------------
Nimmt eine rohe Pen-CSV und eine rohe Watch-CSV und produziert *einen*
DataFrame mit **Watch-Rows als Basis**: jede Zeile = ein Watch-Sample,
ergänzt um ``label_writing`` ∈ {0,1} basierend auf der Pen-Aktivität im
selben Moment (±``label_tol_ms``). Watch-Samples in Pen-Lücken bekommen
Label 0 — sie sind das negative Trainings-Material.

Vorher wird die Pen-Uhr mittels δ aus :mod:`src.alignment` auf die
Watch-Uhr geschoben; bei schwacher Confidence (σ > -2) wird der Shift
verworfen.

Hauptfunktion: ``merge_watch_pen(pen_path, watch_path)``.

CLI
---
::

    python -m src.merge              # neueste Session mergen
    python -m src.merge S027         # spezifische Session

Schreibt nach ``data/processed/{session}_merged.csv``.
"""

from .merge import estimate_pen_imu_offset, merge_watch_pen
from .prep import (
    load_csv,
    prepare_pen_data,
    prepare_watch_data,
    summarize_dataframe,
)

__all__ = [
    "estimate_pen_imu_offset",
    "merge_watch_pen",
    "load_csv",
    "prepare_pen_data",
    "prepare_watch_data",
    "summarize_dataframe",
]
