"""Pen ↔ IMU Clock-Alignment (Schweizer Stroke-Variance-Algorithmus).

Pipeline-Schritt 1 von 4:
    raw CSVs  →  [alignment]  →  merge  →  features  →  train

Was das Modul macht
-------------------
Pen- und Watch-Uhren laufen mit unterschiedlichen Epochen (typisch ~922 Tage
Versatz beim Moleskine + zufällige Drift). Dieses Modul schätzt den
Zeit-Shift δ, mit dem die Pen-Wallclock auf die Watch-Wallclock geschoben
werden muss, damit Stroke-Intervalle und IMU-Samples wieder
zusammenpassen.

Algorithmus (siehe ``data/02_Pen_IMU_Timestamp_Alignment.pdf``):
während des Schreibens ist das Handgelenk relativ ruhig → der korrekte δ
minimiert die mittlere Watch-Acceleration-Variance unter dem geshifteten
Stroke-Mask. Coarse-Grid (±20 s @ 0.5 s) → Fine-Grid (±5 s @ 10 ms).

Wer das benutzt
---------------
* :mod:`src.merge` — wendet δ vor dem ``merge_asof`` an
* :mod:`src.server.sync` — gleicher Algo für Live-Quality-Anzeige
* ``scripts/plot_alignment.py`` — Visualisierung
"""

from .pen_match import (
    DEFAULT_PARAMS,
    PenMatchResult,
    match_pen_data,
    pen_match,
    reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)

__all__ = [
    "DEFAULT_PARAMS",
    "PenMatchResult",
    "match_pen_data",
    "pen_match",
    "reconstruct_watch_wall_clock",
    "strokes_from_dot_types",
]

from .pen_match import (
    DEFAULT_PARAMS,
    PenMatchResult,
    match_pen_data,
    pen_match,
    reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)

__all__ = [
    "DEFAULT_PARAMS",
    "PenMatchResult",
    "match_pen_data",
    "pen_match",
    "reconstruct_watch_wall_clock",
    "strokes_from_dot_types",
]
