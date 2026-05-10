"""Pen + Watch CSV-Merge auf gemeinsame Device-Time-Achse.

Pipeline-Schritt 2:
    raw CSVs  →  alignment  →  [merge]  →  (features)  →  (train)

Was das Modul macht
-------------------
Nimmt eine rohe Pen-CSV und eine rohe Watch-CSV und produziert *einen*
DataFrame mit Pen-Rows als Basis und nächstgelegenem IMU-Sample (±20 ms)
in derselben Zeile. Vorher wird die Pen-Uhr mittels δ aus
:mod:`src.alignment` auf die Watch-Uhr geschoben — falls die Confidence
schwach ist (σ > -2), wird der Shift verworfen und der Merge läuft auf
den ungeshifteten Daten.

Hauptfunktion: ``merge_pen_watch(pen_path, watch_path)``.
Zusätzlich wird ``prepare_pen_data`` / ``prepare_watch_data`` exportiert
— das sind die Pro-Stream-Aufbereitungen, die der Merge intern nutzt
(siehe :mod:`src.merge.prep`).

CLI
---
::

    python -m src.merge              # neueste Session mergen
    python -m src.merge S027         # spezifische Session
"""

from .merge import estimate_pen_imu_offset, merge_pen_watch
from .prep import (
    load_csv,
    prepare_pen_data,
    prepare_watch_data,
    summarize_dataframe,
)

__all__ = [
    "estimate_pen_imu_offset",
    "merge_pen_watch",
    "load_csv",
    "prepare_pen_data",
    "prepare_watch_data",
    "summarize_dataframe",
]
