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


def _pen_pct(merged: pd.DataFrame, block_start: float,
             block_end: float | None, anchor: float) -> float:
    """Anteil Pen-down-Samples im Zeitblock [block_start, block_end), in %."""
    if merged.empty:
        return float("nan")
    if block_end is None:
        sel = merged
    else:
        t = merged["local_ts_ms"]
        # Why: Block 0 (block_start == anchor) muss die ~0.5 s vor dem
        # ersten Fenster-Zentrum mitnehmen — sonst fallen frühe Samples
        # durch den window-center-Inset still raus.
        lo = -np.inf if block_start <= anchor else block_start
        sel = merged[(t >= lo) & (t < block_end)]
    if sel.empty:
        return float("nan")
    return float(sel["label_writing"].mean()) * 100.0


def aggregate(oof_df: pd.DataFrame, scale_sec: float | None,
              merged_loader=pen_truth_per_session) -> pd.DataFrame:
    """Eine Zeile pro (Session, Zeitblock).

    ``scale_sec=None`` → ein Block je Session (ganze Session). Sonst
    nicht-überlappende Blöcke der Länge ``scale_sec``, verankert am
    ersten ``t_center_ms`` der Session.
    """
    scale_ms = None if scale_sec is None else scale_sec * 1000.0
    rows: list[dict] = []
    for sid, g in oof_df.groupby("session_id", sort=False):
        g = g.sort_values("t_center_ms")
        anchor = float(g["t_center_ms"].min())
        if scale_ms is None:
            blk = pd.Series(0, index=g.index)
        else:
            blk = ((g["t_center_ms"] - anchor) // scale_ms).astype(int)
        merged = merged_loader(sid)
        for blk_idx, bg in g.groupby(blk, sort=True):
            block_start = anchor if scale_ms is None else anchor + blk_idx * scale_ms
            block_end = None if scale_ms is None else block_start + scale_ms
            rows.append({
                "session_id": sid,
                "person_id": bg["person_id"].iat[0],
                "block_start_ms": block_start,
                "n_windows": int(len(bg)),
                "pred_pct": float(bg["proba_cal"].mean()) * 100.0,
                "truth_closed_pct": float(bg["label"].mean()) * 100.0,
                "truth_pen_pct": _pen_pct(merged, block_start, block_end, anchor),
            })
    return pd.DataFrame(rows)
