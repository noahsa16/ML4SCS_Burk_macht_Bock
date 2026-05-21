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
        # Der letzte Block schneidet umgekehrt ~0.5 s Pen-Samples am
        # Session-Ende ab (Fenster-Zentrum liegt vor dem echten Ende) —
        # bewusst akzeptiert, Effekt < 1 % und nur im letzten Block.
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
    cols = ["session_id", "person_id", "block_start_ms", "n_windows",
            "pred_pct", "truth_closed_pct", "truth_pen_pct"]
    return pd.DataFrame(rows, columns=cols)


def regression_metrics(agg_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """MAE/RMSE/Bias der Schätzung gegen beide Ground-Truth-Definitionen.

    Alle Werte in Prozentpunkten. Bias = mittlerer vorzeichenbehafteter
    Fehler (pred − truth) — positiv = Überschätzung.
    """
    out: dict[str, dict[str, float]] = {}
    for truth_col, name in [("truth_closed_pct", "closed"),
                            ("truth_pen_pct", "pen")]:
        d = agg_df.dropna(subset=[truth_col, "pred_pct"])
        err = d["pred_pct"].to_numpy() - d[truth_col].to_numpy()
        n = len(err)
        out[name] = {
            "n": int(n),
            "mae": float(np.mean(np.abs(err))) if n else float("nan"),
            "rmse": float(np.sqrt(np.mean(err ** 2))) if n else float("nan"),
            "bias": float(np.mean(err)) if n else float("nan"),
        }
    return out


def plot_calibration(oof_df: pd.DataFrame, out_path: Path,
                      n_bins: int = 10) -> None:
    """Reliability-Diagramm der kalibrierten Sekunden-Proba."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = oof_df["proba_cal"].to_numpy()
    y = oof_df["label"].to_numpy()
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
    xs, ys = [], []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            xs.append(p[m].mean())
            ys.append(y[m].mean())

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="grey", label="perfekt kalibriert")
    ax.plot(xs, ys, "o-", label="kalibrierte Proba")
    ax.set_xlabel("vorhergesagte Schreib-Wahrscheinlichkeit")
    ax.set_ylabel("empirische Schreib-Frequenz")
    ax.set_title("Calibration (Sekunden-Ebene)")
    ax.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_scatter(aggs: dict[str, pd.DataFrame], out_path: Path) -> None:
    """Pro Skala ein Panel: geschätztes % vs. wahres % je Zeitblock."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(aggs), figsize=(5 * len(aggs), 5),
                             squeeze=False)
    for ax, (label, agg) in zip(axes[0], aggs.items()):
        d = agg.dropna(subset=["truth_closed_pct", "pred_pct"])
        ax.plot([0, 100], [0, 100], "--", color="grey")
        ax.scatter(d["truth_closed_pct"], d["pred_pct"], alpha=0.6)
        err = d["pred_pct"] - d["truth_closed_pct"]
        mae = float(np.mean(np.abs(err))) if len(d) else float("nan")
        bias = float(np.mean(err)) if len(d) else float("nan")
        ax.set_title(f"{label}  (MAE={mae:.1f}, Bias={bias:+.1f})")
        ax.set_xlabel("wahres % (geschlossen)")
        ax.set_ylabel("geschätztes %")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def evaluate(oof_path: Path = MODEL_DIR / "loso_oof.csv",
             scales: tuple[float | None, ...] = (60.0, 300.0, None),
             out_csv: Path = MODEL_DIR / "regression_metrics.csv") -> dict:
    """Orchestriert die Regression über alle Skalen, schreibt CSV + Plots."""
    oof = load_oof(oof_path)
    aggs: dict[str, pd.DataFrame] = {}
    metric_rows: list[dict] = []
    for scale in scales:
        label = "session" if scale is None else f"{int(scale)}s"
        agg = aggregate(oof, scale)
        aggs[label] = agg
        for truth, vals in regression_metrics(agg).items():
            metric_rows.append({"scale": label, "truth": truth, **vals})

    metrics = pd.DataFrame(metric_rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out_csv, index=False)
    print(metrics.to_string(index=False))

    plot_calibration(oof, FIG_DIR / "regression_calibration.png")
    plot_scatter(aggs, FIG_DIR / "regression_scatter.png")
    print(f"→ {out_csv}")
    print(f"→ {FIG_DIR / 'regression_calibration.png'}")
    print(f"→ {FIG_DIR / 'regression_scatter.png'}")
    return {"metrics": metrics, "aggregates": aggs}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oof", default=str(MODEL_DIR / "loso_oof.csv"),
                   help="Pfad zur OOF-CSV (default: models/loso_oof.csv).")
    p.add_argument("--out", default=str(MODEL_DIR / "regression_metrics.csv"),
                   help="Ziel-CSV für die Metriken.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    evaluate(oof_path=Path(args.oof), out_csv=Path(args.out))
