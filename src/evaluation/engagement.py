"""Engagement — Schreibzeit-Anteil pro Aufgabe (Stufe 2, Prio 2).

Reines Post-Processing über ``models/loso_oof.csv`` + den
Study-Mode-``markers``-CSVs — kein Modell-Training. Ordnet jedes
1-s-Vorhersage-Fenster über ``t_center_ms`` einem Task-Block zu und
aggregiert pro (Session, Aufgabe) den Schreibzeit-Anteil.

Der gemessene Wert ist ein **Engagement-Proxy**, ausdrücklich kein
Aufmerksamkeits-Detektor: Schreibzeit ≠ Aufmerksamkeit.

CLI
---
::

    python -m src.evaluation.engagement                       # Defaults
    python -m src.evaluation.engagement --oof PATH
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.regression import block_percentages, load_oof

ROOT = Path(__file__).parents[2]
MARKERS_DIR = ROOT / "data" / "raw" / "markers"
MODEL_DIR = ROOT / "models"
FIG_DIR = ROOT / "reports" / "figures"

# Spaltenreihenfolge der Schreib-Tasks im Heatmap-Grid (Protokoll v1).
WRITING_TASKS = ["abschreiben", "free_writing", "math"]

TIMELINE_COLS = ["task_index", "task_id", "task_name", "task_category",
                 "start_ms", "end_ms"]


def task_timeline(session_id: str) -> pd.DataFrame:
    """Task-Blöcke einer Session aus ihrer Marker-CSV.

    Paart jedes ``task_start`` mit dem ``task_end`` gleichen
    ``task_index``. Rückgabe: eine Zeile pro Block (Spalten
    ``TIMELINE_COLS``), nach ``start_ms`` sortiert. Ein ``task_start``
    ohne passendes ``task_end`` (abgebrochene Session) wird verworfen.
    Fehlt die Marker-CSV, kommt ein leerer DataFrame zurück.
    """
    path = MARKERS_DIR / f"{session_id}_markers.csv"
    if not path.exists():
        return pd.DataFrame(columns=TIMELINE_COLS)

    m = pd.read_csv(path)
    ends = (m[m["event"] == "task_end"]
            .drop_duplicates("task_index", keep="first")
            .set_index("task_index")["timestamp_ms"])
    rows: list[dict] = []
    for _, s in m[m["event"] == "task_start"].iterrows():
        idx = s["task_index"]
        if idx not in ends.index:
            continue  # Why: task_start ohne task_end = abgebrochener Block.
        rows.append({
            "task_index": int(idx),
            "task_id": s["task_id"],
            "task_name": s["task_name"],
            "task_category": s["task_category"],
            "start_ms": float(s["timestamp_ms"]),
            "end_ms": float(ends.loc[idx]),
        })
    return pd.DataFrame(rows, columns=TIMELINE_COLS).sort_values(
        "start_ms").reset_index(drop=True)


def assign_tasks(oof_session: pd.DataFrame,
                 timeline: pd.DataFrame) -> pd.DataFrame:
    """Ordnet jedem OOF-Fenster einer Session seinen Task-Block zu.

    Fügt die Spalten task_index/task_id/task_name/task_category hinzu.
    Fenster, deren ``t_center_ms`` in keinem ``[start_ms, end_ms)``
    liegt (Vor-Task-Countdown, Übergänge), bekommen ``NaN``.
    """
    out = oof_session.copy()
    # Initialize columns with NaN
    out["task_index"] = np.nan
    # Convert string columns to object dtype to allow both NaN and strings
    out["task_id"] = np.nan
    out["task_id"] = out["task_id"].astype(object)
    out["task_name"] = np.nan
    out["task_name"] = out["task_name"].astype(object)
    out["task_category"] = np.nan
    out["task_category"] = out["task_category"].astype(object)

    t = out["t_center_ms"]
    for _, blk in timeline.iterrows():
        mask = (t >= blk["start_ms"]) & (t < blk["end_ms"])
        out.loc[mask, "task_index"] = blk["task_index"]
        out.loc[mask, "task_id"] = blk["task_id"]
        out.loc[mask, "task_name"] = blk["task_name"]
        out.loc[mask, "task_category"] = blk["task_category"]
    return out


ENGAGEMENT_COLS = ["session_id", "person_id", "task_index", "task_id",
                   "task_name", "task_category", "n_windows", "true_pct",
                   "pred_pct", "error_pp"]


def engagement_per_task(oof_df: pd.DataFrame,
                        timeline_loader=task_timeline) -> pd.DataFrame:
    """Eine Zeile pro (Session, Task-Block): Schreibzeit-Anteil.

    ``true_pct``/``pred_pct`` über den mit ``regression.py`` geteilten
    ``block_percentages()``. Sessions ohne Marker-CSV (leere Timeline)
    werden mit einer Warnung übersprungen. Fenster ohne Task-Zuordnung
    (Übergänge) zählen pro Session als Diagnose-Ausgabe.
    """
    rows: list[dict] = []
    for sid, g in oof_df.groupby("session_id", sort=False):
        timeline = timeline_loader(sid)
        if timeline.empty:
            print(f"  ⚠ {sid}: keine Marker-CSV — übersprungen")
            continue
        assigned = assign_tasks(g, timeline)
        n_unassigned = int(assigned["task_index"].isna().sum())
        if n_unassigned:
            print(f"  {sid}: {n_unassigned}/{len(assigned)} Fenster "
                  f"ohne Task (Übergänge)")
        tagged = assigned.dropna(subset=["task_index"])
        for tidx, bg in tagged.groupby("task_index", sort=True):
            first = bg.iloc[0]
            pcts = block_percentages(bg)
            rows.append({
                "session_id": sid,
                "person_id": bg["person_id"].iat[0],
                "task_index": int(tidx),
                "task_id": first["task_id"],
                "task_name": first["task_name"],
                "task_category": first["task_category"],
                "n_windows": pcts["n_windows"],
                "true_pct": pcts["true_pct"],
                "pred_pct": pcts["pred_pct"],
                "error_pp": pcts["pred_pct"] - pcts["true_pct"],
            })
    return pd.DataFrame(rows, columns=ENGAGEMENT_COLS)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oof", default=str(MODEL_DIR / "loso_oof.csv"),
                   help="Pfad zur OOF-CSV (default: models/loso_oof.csv).")
    p.add_argument("--out", default=str(MODEL_DIR / "engagement_metrics.csv"),
                   help="Ziel-CSV für die Engagement-Metriken.")
    return p.parse_args()
