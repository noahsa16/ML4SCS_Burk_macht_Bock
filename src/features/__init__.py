"""Sliding-Window-Features auf der watch-base gemergten CSV.

Sliding-Window-Stats (1 s / 0.5 s Stride, 42 Features) auf den 50 Hz
Watch-IMU-Stream. Pen-Aktivität liefert das Window-Label.

Hauptfunktion: ``build_windows(merged_df)`` — siehe :mod:`src.features.windows`.

CLI
---
::

    python -m src.features              # neueste Session
    python -m src.features S029         # spezifische Session

Schreibt nach ``data/processed/{session}_windows.csv``.
"""

from .windows import build_windows, load_session_windows

__all__ = ["build_windows", "load_session_windows"]
