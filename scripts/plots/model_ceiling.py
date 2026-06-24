"""Die Decke auf einen Blick — eine Familie, eine Decke, zwei Straßen hindurch.

Sammelt die per-Fold-Accuracy mehrerer Modellfamilien aus den kanonischen
LOSO-CV-CSVs (alle N=15, legacy, post-Capture-Clock-Fix, kausal) und stellt sie
auf ihrer **nativen Decision-Skala** als horizontale Balken dar — sortiert,
mit ±Std-Fehlerbalken, schattierter „Decken"-Band um den 1-s-Cluster und
gepaartem Wilcoxon-Signifikanztest gegen den RF-1-s-Floor (Stern = p<0.05).

Aussage in einem Bild:
  * Bei **1 s** treffen drei mechanistisch unverwandte Familien (RF / MiniRocket
    / TCN) dieselbe ~0,88-Decke — Signal-Ambiguität, kein Modellproblem.
  * Zwei **Straßen hindurch**: nativer Längskontext (TCN auf 5-s-Fenstern,
    0,91–0,92) und ein post-hoc **HMM** auf der 1-s-RF-Proba (0,905) — beide
    holen denselben Zeit-Struktur-Gewinn, ohne die 1-s-Decke zu „brechen".

Reproduzierbar: liest nur committete CV-CSVs, rechnet Mittel/Std/Signifikanz
selbst. Fehlt eine CSV, wird die Zeile mit Hinweis übersprungen (kein Crash).

CLI::

    python scripts/plots/model_ceiling.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from src.evaluation.significance import paired_fold_test  # noqa: E402

MODELS = ROOT / "models"
FIG_DIR = ROOT / "reports" / "figures"

# Farb-Gruppen (Erzählung):
C_1S = "#8A88A8"     # 1-s-Decke (gedämpftes Indigo)
C_5S = "#2E7D6B"     # nativer 5-s-Kontext, RF-Familie (Teal)
C_ROAD = "#B07A2C"   # die Straßen hindurch (Gold) — Deep-5s + HMM
C_FLOOR = "#3B3A6B"  # RF-1s-Floor (Referenz, tiefes Indigo)

# Manifest: (Label, native Skala, CSV, Filter-dict|None, Gruppe).
# accuracy-Spalte = native per-window-Decision auf der jeweiligen Skala.
GROUP_FLOOR, GROUP_1S, GROUP_5S, GROUP_ROAD = "floor", "1s", "5s", "road"
SPECS = [
    ("RF · 88 Features",            "1 s",  "loso_cv_legacy.csv",     None,                              GROUP_FLOOR),
    ("MiniRocket · random conv",    "1 s",  "minirocket_win1_cv.csv", None,                              GROUP_1S),
    ("TCN · learned conv",          "1 s",  "deep_loso_legacy.csv",   {"model": "tcn", "window_sec": 1}, GROUP_1S),
    ("RF · 5-s-Fenster",            "5 s",  "rf_win5_cv_legacy.csv",  None,                              GROUP_5S),
    ("MiniRocket · 5-s-Fenster",    "5 s",  "minirocket_win5_cv.csv", None,                              GROUP_5S),
    ("RF-1s + HMM-Filter",          "~16 s","hmm_postprocess_cv.csv", None,                              GROUP_ROAD),
    ("TCN · 5-s-Fenster",           "5 s",  "deep_tcn5_legacy.csv",   {"model": "tcn", "window_sec": 5}, GROUP_ROAD),
    ("tcn6 · 5-s-Fenster",          "5 s",  "deep_tcn6_legacy.csv",   {"model": "tcn6", "window_sec": 5},GROUP_ROAD),
]

GROUP_COLOR = {GROUP_FLOOR: C_FLOOR, GROUP_1S: C_1S, GROUP_5S: C_5S, GROUP_ROAD: C_ROAD}


def _load(csv: str, flt: dict | None):
    path = MODELS / csv
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if flt:
        for k, v in flt.items():
            df = df[df[k] == v]
    if df.empty or "accuracy" not in df or "held_out" not in df:
        return None
    return df[["held_out", "accuracy"] + (["roc_auc"] if "roc_auc" in df else [])].copy()


def run() -> None:
    floor = _load("loso_cv_legacy.csv", None)
    if floor is None:
        raise SystemExit("RF-1s-Floor (loso_cv_legacy.csv) fehlt — Basis für die Signifikanz.")
    floor_acc = floor.set_index("held_out")["accuracy"]

    rows = []
    for label, scale, csv, flt, group in SPECS:
        df = _load(csv, flt)
        if df is None:
            print(f"  [skip] {label}: {csv} fehlt")
            continue
        acc = df.set_index("held_out")["accuracy"]
        auc = (df.set_index("held_out")["roc_auc"].mean()
               if "roc_auc" in df else float("nan"))
        # Signifikanz gegen den RF-1s-Floor auf gemeinsamen Folds.
        common = floor_acc.index.intersection(acc.index)
        if group == GROUP_FLOOR or len(common) < 3:
            p, sig = float("nan"), False
        else:
            t = paired_fold_test(acc.loc[common].to_numpy(), floor_acc.loc[common].to_numpy())
            p, sig = t["p_value"], t["significant"]
        rows.append({
            "label": label, "scale": scale, "group": group,
            "mean": float(acc.mean()), "std": float(acc.std()),
            "auc": auc, "n": len(acc), "p": p, "sig": sig,
        })
        star = "  *" if sig else ""
        print(f"  {label:26s} @{scale:5s} N={len(acc):2d}  acc={acc.mean():.3f}±{acc.std():.3f}"
              f"  AUC={auc:.3f}  p={p:.4f}{star}")

    rows.sort(key=lambda r: r["mean"])  # aufsteigend → Krone oben
    labels = [f"{r['label']}  ·  {r['scale']}" for r in rows]
    means = np.array([r["mean"] for r in rows])
    stds = np.array([r["std"] for r in rows])
    colors = [GROUP_COLOR[r["group"]] for r in rows]
    y = np.arange(len(rows))

    fig, ax = plt.subplots(figsize=(11, 6.2))

    # Decken-Band: Spannweite der 1-s-Familie (Floor + 1s-Gruppe).
    band = [r["mean"] for r in rows if r["group"] in (GROUP_FLOOR, GROUP_1S)]
    if band:
        ax.axvspan(min(band), max(band), color="#cfcadf", alpha=0.35, zorder=0)
        ax.text(min(band), len(rows) - 0.35, " 1-s-Decke ", fontsize=9,
                color="#5a5780", va="center", ha="left", style="italic")

    bars = ax.barh(y, means, color=colors, height=0.62, zorder=3,
                   xerr=stds, error_kw=dict(ecolor="#00000055", elinewidth=1.1, capsize=3))

    for yi, r, b in zip(y, rows, bars):
        txt = f"{r['mean']:.3f}"
        if r["sig"]:
            txt += " *"
        ax.text(b.get_width() + r["std"] + 0.004, yi, txt, va="center",
                ha="left", fontsize=10,
                fontweight="bold" if r["group"] == GROUP_ROAD else "normal",
                color="#222")

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    lo = min(means) - max(stds) - 0.02
    ax.set_xlim(max(0.80, lo), 0.95)
    ax.set_xlabel("LOSO-Accuracy (cross-subject, N=15, kausal)", fontsize=11)
    ax.set_title("Eine Decke, zwei Straßen hindurch — Modellfamilien auf nativer Decision-Skala",
                 fontsize=13.5, pad=14)
    ax.axvline(float(floor_acc.mean()), color=C_FLOOR, lw=1.0, ls="--", alpha=0.6, zorder=2)

    legend = [
        Patch(facecolor=C_FLOOR, label="RF-1s-Floor (Referenz)"),
        Patch(facecolor=C_1S, label="1-s-Decke (RF / MiniRocket / TCN)"),
        Patch(facecolor=C_5S, label="nativer 5-s-Kontext, RF-Familie"),
        Patch(facecolor=C_ROAD, label="Straßen hindurch: Deep-5s + HMM"),
    ]
    ax.legend(handles=legend, loc="lower right", fontsize=8.5, framealpha=0.92)
    ax.text(0.012, -0.115, "*  gepaarter Wilcoxon p<0,05 gegen den RF-1s-Floor "
            "(dieselben 15 Folds)", transform=ax.transAxes, fontsize=8.5,
            color="#555", style="italic")
    ax.grid(axis="x", color="#00000010", zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / "model_ceiling.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"\n→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    run()
