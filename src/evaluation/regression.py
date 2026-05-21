"""Regression: Schreib-Prozent pro Zeitfenster.

Stufe 2 der Schreib-Prozent-Auswertung (siehe
``docs/specs/2026-05-21-regression-schreibprozent-design.md``). Reines
Post-Processing über ``models/loso_oof.csv`` (von ``train_loso.py
--save-oof`` erzeugt) — kein Modell-Training. Liefert MAE/RMSE/Bias der
geschätzten Schreib-Prozente gegen zwei Ground-Truth-Definitionen plus
Calibration-Plots.

CLI
---
::

    python -m src.evaluation.regression                       # Defaults
    python -m src.evaluation.regression --oof PATH
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
FIG_DIR = ROOT / "reports" / "figures"

# Spaltenschema der OOF-CSV, die train_loso.py --save-oof schreibt.
OOF_COLS = ["session_id", "person_id", "t_center_ms",
            "label", "proba_raw", "proba_cal"]


def load_oof(path: Path) -> pd.DataFrame:
    """Liest models/loso_oof.csv."""
    return pd.read_csv(path)


def pen_truth_per_session(session_id: str) -> pd.DataFrame:
    """Rohe Pen-Wahrheit: label_writing je 50-Hz-Sample aus merged.csv.

    Zeit-Achse ``local_ts_ms`` ist dieselbe, aus der windows.py
    ``t_center_ms`` mittelt — Aggregations-Blöcke greifen ohne Umrechnung.
    """
    path = DATA_PROC / f"{session_id}_merged.csv"
    df = pd.read_csv(path, usecols=["local_ts_ms", "label_writing"])
    return df.dropna(subset=["local_ts_ms"]).sort_values(
        "local_ts_ms"
    ).reset_index(drop=True)
