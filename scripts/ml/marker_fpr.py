"""Marker-getriebene Per-Task-FPR: sitzen die False-Positives auf den Hard-Negatives?

Legt die LOSO-OOF-Vorhersagen über die Study-Mode-Marker-Blöcke und zählt die
False-Positive-Rate (Anteil als „writing" vorhergesagter Fenster) GETRENNT nach
Idle-Task-Typ. Beantwortet die Decke-vs-Artefakt-Frage: ist die Schwäche eines
Folds (z. B. P17) eine **Hard-Negative-Trainingslücke** (FPs clustern auf
``keyboard_typing``/``phone_typing``) oder echte **Signal-Ambiguität** (FPR flach
über alle Idle-Tasks)?

Timestamp: ``markers.timestamp_ms`` (Server-Wall-Clock) und ``oof.t_center_ms``
(Watch-``ts``, post Capture-Clock-Fix) haben < 100 ms Skew; Task-Blöcke sind
Minuten lang → direkte Zuordnung ohne Offset (siehe CLAUDE.md, Marker-Semantik).

CLI: ``python scripts/ml/marker_fpr.py [--oof models/loso_oof_legacy.csv]``.
Output: ``reports/marker_fpr.md`` + ``models/marker_fpr.csv``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MARKER_DIR = ROOT / "data" / "raw" / "markers"
SESSIONS = ROOT / "data" / "sessions.csv"
MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"

HARD_NEGATIVES = ("keyboard_typing", "phone_typing", "phone_scrolling",
                  "pen_fidgeting", "gesturing")
EASY_NEGATIVE = "pause"


# ---- reine, testbare Kernlogik -------------------------------------------

def parse_task_blocks(markers: pd.DataFrame) -> pd.DataFrame:
    """Marker-Events → Task-Blöcke. Paart task_start/task_end je ``task_index``.

    Returns DataFrame[task_id, task_category, start_ms, end_ms], nur vollständig
    gepaarte Blöcke.
    """
    ev = markers[markers["event"].isin(["task_start", "task_end"])]
    rows = []
    for idx, g in ev.groupby("task_index"):
        starts = g[g["event"] == "task_start"]
        ends = g[g["event"] == "task_end"]
        if starts.empty or ends.empty:
            continue
        s = starts.iloc[0]
        rows.append({
            "task_id": s["task_id"],
            "task_category": s["task_category"],
            "start_ms": float(starts["timestamp_ms"].min()),
            "end_ms": float(ends["timestamp_ms"].max()),
        })
    return pd.DataFrame(rows, columns=["task_id", "task_category", "start_ms", "end_ms"])


def assign_task(oof_sess: pd.DataFrame, blocks: pd.DataFrame) -> pd.DataFrame:
    """Ordnet jedes OOF-Fenster (t_center_ms) seinem Task-Block zu (start ≤ t < end).

    Fenster außerhalb aller Blöcke werden verworfen. Returns die OOF-Zeilen mit
    zusätzlichen Spalten task_id, task_category.
    """
    if blocks.empty:
        return oof_sess.iloc[0:0].assign(task_id=[], task_category=[])
    intervals = pd.IntervalIndex.from_arrays(
        blocks["start_ms"], blocks["end_ms"], closed="left")
    idx = intervals.get_indexer(oof_sess["t_center_ms"].to_numpy())
    out = oof_sess.copy()
    out["_bi"] = idx
    out = out[out["_bi"] >= 0].copy()
    out["task_id"] = blocks["task_id"].to_numpy()[out["_bi"].to_numpy()]
    out["task_category"] = blocks["task_category"].to_numpy()[out["_bi"].to_numpy()]
    return out.drop(columns="_bi")


def fpr_by_task(assigned: pd.DataFrame, proba_col: str = "proba_cal",
                thresh: float = 0.5) -> pd.DataFrame:
    """Per Idle-Task: FPR = Anteil Fenster mit Proba ≥ thresh (fälschlich „writing").

    Returns DataFrame[task_category, task_id, n, n_fp, fpr], nur idle-Tasks
    (echte Nicht-Schreib-Blöcke), absteigend nach fpr.
    """
    idle = assigned[assigned["task_category"] == "idle"].copy()
    if idle.empty:
        return pd.DataFrame(columns=["task_category", "task_id", "n", "n_fp", "fpr"])
    idle["_pos"] = (idle[proba_col] >= thresh).astype(int)
    g = idle.groupby("task_id")["_pos"].agg(["size", "sum"]).reset_index()
    g.columns = ["task_id", "n", "n_fp"]
    g["task_category"] = "idle"
    g["fpr"] = g["n_fp"] / g["n"]
    return g[["task_category", "task_id", "n", "n_fp", "fpr"]].sort_values(
        "fpr", ascending=False).reset_index(drop=True)


def _proba_col(df: pd.DataFrame) -> str:
    for c in ("proba_cal", "proba", "proba_raw"):
        if c in df.columns:
            return c
    raise KeyError("keine proba-Spalte in OOF")


# ---- Plumbing ------------------------------------------------------------

def _session_person_protocol() -> pd.DataFrame:
    if not SESSIONS.exists():
        return pd.DataFrame(columns=["session_id", "person_id", "protocol_id"])
    df = pd.read_csv(SESSIONS)
    cols = [c for c in ("session_id", "person_id", "protocol_id") if c in df.columns]
    return df[cols].drop_duplicates("session_id")


def build_fpr_table(oof: pd.DataFrame) -> pd.DataFrame:
    """Über alle Sessions mit Markern: FPR je (person, protocol, task_id)."""
    pcol = _proba_col(oof)
    meta = _session_person_protocol().set_index("session_id")
    rows = []
    for sid, g in oof.groupby("session_id"):
        mfile = MARKER_DIR / f"{sid}_markers.csv"
        if not mfile.exists():
            continue
        blocks = parse_task_blocks(pd.read_csv(mfile))
        assigned = assign_task(g, blocks)
        fpr = fpr_by_task(assigned, pcol)
        if fpr.empty:
            continue
        person = (oof.loc[oof.session_id == sid, "person_id"].iloc[0]
                  if "person_id" in oof.columns else
                  meta.loc[sid, "person_id"] if sid in meta.index else sid)
        protocol = meta.loc[sid, "protocol_id"] if sid in meta.index and "protocol_id" in meta.columns else ""
        fpr["session_id"], fpr["person_id"], fpr["protocol_id"] = sid, person, protocol
        rows.append(fpr)
    return (pd.concat(rows, ignore_index=True) if rows
            else pd.DataFrame(columns=["task_category", "task_id", "n", "n_fp",
                                       "fpr", "session_id", "person_id", "protocol_id"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--oof", type=Path, default=MODEL_DIR / "loso_oof_legacy.csv")
    args = ap.parse_args()
    if not args.oof.exists():
        raise SystemExit(f"OOF fehlt: {args.oof}")

    oof = pd.read_csv(args.oof)
    table = build_fpr_table(oof)
    if table.empty:
        raise SystemExit("keine Fenster den Markern zuordenbar (Zeitachsen prüfen)")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(MODEL_DIR / "marker_fpr.csv", index=False)

    # Pooled: Hard-Negatives vs pause (gewichtet nach n)
    def _pool(mask) -> float:
        sub = table[mask]
        return float(sub["n_fp"].sum() / sub["n"].sum()) if sub["n"].sum() else float("nan")
    hard = _pool(table["task_id"].isin(HARD_NEGATIVES))
    easy = _pool(table["task_id"] == EASY_NEGATIVE)

    lines = ["# Marker-Per-Task-FPR: Hard-Negatives vs. easy negatives", "",
             f"OOF: `{args.oof.name}` | {oof['person_id'].nunique() if 'person_id' in oof else '?'} "
             f"Personen | {table['session_id'].nunique()} Sessions mit Markern", "",
             "## Pooled (alle Sessions)", "",
             f"- **Hard-Negatives** (keyboard/phone/fidget/gesture) FPR: **{hard:.3f}**",
             f"- **pause** FPR: **{easy:.3f}**",
             f"- Verhältnis hard/easy: **{hard/easy:.1f}×**" if easy else "- pause n=0", "",
             "## FPR je Task-Typ (pooled über Personen)", "",
             "| task_id | n | FPR |", "|---|---|---|"]
    pooled_task = (table.groupby("task_id")[["n", "n_fp"]].sum()
                   .assign(fpr=lambda d: d.n_fp / d.n).sort_values("fpr", ascending=False))
    for tid, r in pooled_task.iterrows():
        lines.append(f"| {tid} | {int(r.n)} | {r.fpr:.3f} |")

    # Per v2-Proband (die interessanten Folds)
    v2 = table[table["protocol_id"].astype(str) == "v2"]
    if not v2.empty:
        lines += ["", "## FPR je v2-Proband × Task (die Trainingslücken-Kandidaten)", ""]
        for person, pg in v2.groupby("person_id"):
            pt = (pg.groupby("task_id")[["n", "n_fp"]].sum()
                  .assign(fpr=lambda d: d.n_fp / d.n).sort_values("fpr", ascending=False))
            cells = ", ".join(f"{tid}={r.fpr:.2f}(n{int(r.n)})" for tid, r in pt.iterrows())
            lines.append(f"- **{person}**: {cells}")

    lines += ["", "## Lesart", "",
              "Hard-FPR ≫ pause-FPR (task-spezifische Cluster auf keyboard/phone) → "
              "die Fold-Schwäche ist eine **Hard-Negative-Trainingslücke** (Artefakt). "
              "Flache FPR über alle Idle-Tasks → echte **Signal-Ambiguität** (Decke).",
              "", f"Rohdaten: `{(MODEL_DIR / 'marker_fpr.csv').relative_to(ROOT)}`.", ""]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "marker_fpr.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
