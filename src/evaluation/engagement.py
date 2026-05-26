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

# Why: matches v1.json's `pre_task_seconds: 5`. Used to anchor reconstructed
# task_start timestamps when the marker writer dropped one (real one-off in
# S022). If a future protocol uses a different countdown, derive this from
# the markers' protocol_id instead of hardcoding.
RECONSTRUCT_PRE_TASK_MS = 5000


def task_timeline(session_id: str) -> pd.DataFrame:
    """Task-Blöcke einer Session aus ihrer Marker-CSV.

    Iteriert über jeden ``task_end`` und paart ihn mit dem ``task_start``
    gleichen ``task_index``. Rückgabe: eine Zeile pro Block (Spalten
    ``TIMELINE_COLS``), nach ``start_ms`` sortiert. Ein ``task_start``
    ohne passendes ``task_end`` (abgebrochene Session) wird verworfen.

    Fehlt der ``task_start`` zu einem ``task_end`` (Marker-Writer-Hiccup,
    real einmal in S022 vorgekommen), wird der Block **rekonstruiert**:
    ``start_ms`` = Zeitstempel des unmittelbar vorhergehenden Events
    + ``RECONSTRUCT_PRE_TASK_MS``. So bleibt der Block in der Engagement-
    Aggregation enthalten statt still wegzufallen.

    Fehlt die Marker-CSV, kommt ein leerer DataFrame zurück.
    """
    path = MARKERS_DIR / f"{session_id}_markers.csv"
    if not path.exists():
        return pd.DataFrame(columns=TIMELINE_COLS)

    m = pd.read_csv(path).sort_values("timestamp_ms").reset_index(drop=True)
    starts = (m[m["event"] == "task_start"]
              .drop_duplicates("task_index", keep="first")
              .set_index("task_index"))
    rows: list[dict] = []
    for _, e in (m[m["event"] == "task_end"]
                 .drop_duplicates("task_index", keep="first").iterrows()):
        idx = e["task_index"]
        end_ms = float(e["timestamp_ms"])

        if idx in starts.index:
            s = starts.loc[idx]
            start_ms = float(s["timestamp_ms"])
            task_id = s["task_id"]
            task_name = s["task_name"]
            task_category = s["task_category"]
        else:
            prior = m[m["timestamp_ms"] < end_ms]
            if prior.empty:
                continue  # Why: nothing to anchor against — malformed CSV.
            start_ms = (float(prior["timestamp_ms"].iloc[-1])
                        + RECONSTRUCT_PRE_TASK_MS)
            task_id = e["task_id"]
            task_name = e["task_name"]
            task_category = e["task_category"]
            print(f"  ⚠ {session_id}: task_start for index {int(idx)} "
                  f"({task_id}) missing — reconstructed start at "
                  f"{start_ms:.0f} ms (prior event + "
                  f"{RECONSTRUCT_PRE_TASK_MS} ms pre-task)")

        rows.append({
            "task_index": int(idx),
            "task_id": task_id,
            "task_name": task_name,
            "task_category": task_category,
            "start_ms": start_ms,
            "end_ms": end_ms,
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


def plot_engagement_heatmap(eng_df: pd.DataFrame, out_path: Path) -> None:
    """Proband × Schreib-Task Heatmap plus Pausen-Kontrollstreifen.

    Zellfarbe = ``true_pct``; Zell-Text zeigt ``echt/geschätzt``. Der
    Pausen-Streifen rechts sollte durchgehend niedrige Werte zeigen.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    persons = sorted(eng_df["person_id"].unique())
    writing = eng_df[eng_df["task_category"] == "writing"]
    tasks = [t for t in WRITING_TASKS if t in set(writing["task_id"])]

    true_grid = np.full((len(persons), len(tasks)), np.nan)
    pred_grid = np.full((len(persons), len(tasks)), np.nan)
    for i, p in enumerate(persons):
        for j, t in enumerate(tasks):
            cell = writing[(writing["person_id"] == p)
                           & (writing["task_id"] == t)]
            if not cell.empty:
                true_grid[i, j] = cell["true_pct"].mean()
                pred_grid[i, j] = cell["pred_pct"].mean()

    # Pausen-Kontrolle: mittlerer true_pct der idle-Blöcke je Proband.
    idle = eng_df[eng_df["task_category"] == "idle"]
    pause_col = np.array([
        idle.loc[idle["person_id"] == p, "true_pct"].mean()
        for p in persons
    ]).reshape(-1, 1)

    fig, (ax, axp) = plt.subplots(
        1, 2, figsize=(2.2 * len(tasks) + 3.0, 0.55 * len(persons) + 1.6),
        gridspec_kw={"width_ratios": [max(len(tasks), 1), 1]})

    im = ax.imshow(true_grid, cmap="viridis", vmin=0, vmax=100,
                   aspect="auto")
    ax.set_xticks(range(len(tasks)))
    ax.set_xticklabels(tasks, rotation=20, ha="right")
    ax.set_yticks(range(len(persons)))
    ax.set_yticklabels(persons)
    ax.set_title("Schreibzeit-Anteil je Aufgabe  (echt / geschätzt)")
    for i in range(len(persons)):
        for j in range(len(tasks)):
            if not np.isnan(true_grid[i, j]):
                ax.text(j, i,
                        f"{true_grid[i, j]:.0f}/{pred_grid[i, j]:.0f}",
                        ha="center", va="center", fontsize=8,
                        color="white" if true_grid[i, j] < 55 else "black")

    axp.imshow(pause_col, cmap="viridis", vmin=0, vmax=100, aspect="auto")
    axp.set_xticks([0])
    axp.set_xticklabels(["Pause"], rotation=20, ha="right")
    axp.set_yticks([])
    axp.set_title("Kontrolle")
    for i in range(len(persons)):
        if not np.isnan(pause_col[i, 0]):
            axp.text(0, i, f"{pause_col[i, 0]:.0f}", ha="center",
                     va="center", fontsize=8,
                     color="white" if pause_col[i, 0] < 55 else "black")

    fig.colorbar(im, ax=[ax, axp], fraction=0.04,
                 label="echter Schreibzeit-Anteil (%)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def evaluate(oof_path: Path = MODEL_DIR / "loso_oof.csv",
             out_csv: Path = MODEL_DIR / "engagement_metrics.csv") -> dict:
    """Orchestriert die Engagement-Auswertung: CSV + Heatmap."""
    oof = load_oof(oof_path)
    eng_df = engagement_per_task(oof)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    eng_df.to_csv(out_csv, index=False)

    writing = eng_df[eng_df["task_category"] == "writing"]
    idle = eng_df[eng_df["task_category"] == "idle"]
    print("=== Schreib-Tasks (Engagement: echter Schreibzeit-Anteil) ===")
    print(writing.to_string(index=False))
    print()
    print("=== Pausen (Kontrolle — true_pct sollte niedrig sein) ===")
    print(idle.to_string(index=False))

    heatmap = FIG_DIR / "engagement_heatmap.png"
    plot_engagement_heatmap(eng_df, heatmap)
    print(f"→ {out_csv}")
    print(f"→ {heatmap}")
    return {"engagement": eng_df}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oof", default=str(MODEL_DIR / "loso_oof.csv"),
                   help="Pfad zur OOF-CSV (default: models/loso_oof.csv).")
    p.add_argument("--out", default=str(MODEL_DIR / "engagement_metrics.csv"),
                   help="Ziel-CSV für die Engagement-Metriken.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    evaluate(oof_path=Path(args.oof), out_csv=Path(args.out))
