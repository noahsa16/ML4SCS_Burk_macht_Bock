"""Windowing-Übersicht für den RF-Writing-Detektor — erklärende Präsi-Abbildung.

Zwei verschiedene "Fenster"-Achsen, die oft verwechselt werden:

  ① FEATURE-Fenster (nativ): über wie viele Sekunden Roh-IMU werden die 88
     Features gerechnet? Getestet per Sweep (1 s / 3 s / 5 s, versch. Stride).
     Gezeigt werden die NATIVEN per-Window-Metriken (kein Glätten) — sie sind
     vom kausal/nicht-kausal-Thema unberührt und damit direkt vergleichbar.

  ② DECISION-Fenster (kausaler Burst): das 1-s-Feature-Fenster bleibt, aber die
     1-s-Wahrscheinlichkeiten werden per Session TRAILING (kausal, kein
     Look-ahead) über 1…30 s gemittelt und neu geschwellt. Frisch aus
     ``models/loso_oof_legacy.csv`` (N=20) mit dem kanonischen
     ``_causal_rolling_mean`` — NICHT die deprecateten ``center=True``-Zahlen.

Kernaussage: mehr Roh-Kontext PRO Feature-Fenster hilft (Plateau ~5 s);
nachträgliches Glätten kurzer Fenster (②) hebt die Genauigkeit unter kausaler
Auswertung nicht — es tauscht nur Auflösung gegen Stabilität.

CLI::  python scripts/plots/plot_windowing_overview.py
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
from sklearn.metrics import roc_auc_score  # noqa: E402

from src.training.train_loso import _causal_rolling_mean  # noqa: E402

OOF = ROOT / "models" / "loso_oof_legacy.csv"
OUT = ROOT / "reports" / "figures" / "windowing_overview.png"

# Native RF-Sweep (aus models/window_sweep_w*_cv.csv, N=14, ungeglättet).
SWEEP_FILES = {
    "1 s\n(Stride 0.5)": "models/window_sweep_w1s0.5_cv.csv",
    "3 s\n(Stride 1.5)": "models/window_sweep_w3s1.5_cv.csv",
    "5 s\n(Stride 1)": "models/window_sweep_w5s1_cv.csv",
    "5 s\n(Stride 2.5)": "models/window_sweep_w5s2.5_cv.csv",
}
DECISION_SCALES = [1, 2, 3, 5, 10, 30]

ACC_C, AUC_C = "#4F8FCF", "#E08A3C"


def native_sweep() -> pd.DataFrame:
    rows = []
    for label, f in SWEEP_FILES.items():
        d = pd.read_csv(ROOT / f)
        if "model" in d.columns:
            d = d[d.model == "RandomForest"]
        rows.append({
            "label": label, "n": len(d),
            "acc": d.accuracy.mean(), "acc_sd": d.accuracy.std(),
            "auc": d.roc_auc.mean(), "auc_sd": d.roc_auc.std(),
        })
    return pd.DataFrame(rows)


def causal_decision() -> pd.DataFrame:
    """Kausaler Burst pro Skala aus dem OOF, per Person gemittelt (± Fold-σ)."""
    oof = pd.read_csv(OOF).sort_values(["session_id", "t_center_ms"]).reset_index(drop=True)
    out = []
    for scale in DECISION_SCALES:
        # Per Session glätten (t_center_ms nur innerhalb einer Session monoton).
        sm = np.empty(len(oof))
        for _, idx in oof.groupby("session_id", sort=False).groups.items():
            g = oof.loc[idx]
            t = g["t_center_ms"].to_numpy()
            stride_ms = float(np.median(np.diff(t))) if len(t) >= 2 else 500.0
            n = max(1, int(round(scale * 1000.0 / (stride_ms or 500.0))))
            sm[g.index] = _causal_rolling_mean(g["proba_cal"].to_numpy(), n)
        tmp = oof.copy()
        tmp["_sm"] = sm
        # Pro Person Accuracy + AUC, dann Fold-Mittel ± σ (wie die Headline).
        accs, aucs = [], []
        for _, gp in tmp.groupby("person_id"):
            y = gp["label"].to_numpy()
            p = gp["_sm"].to_numpy()
            accs.append(((p >= 0.5).astype(int) == y).mean())
            try:
                aucs.append(roc_auc_score(y, p))
            except ValueError:
                pass
        out.append({"scale": scale, "acc": np.mean(accs), "acc_sd": np.std(accs),
                    "auc": np.mean(aucs), "auc_sd": np.std(aucs)})
    return pd.DataFrame(out)


def run() -> None:
    sw = native_sweep()
    dc = causal_decision()
    print("① Native FEATURE-window sweep (N=%d):" % sw.n.iloc[0])
    for _, r in sw.iterrows():
        print(f"   {r.label.replace(chr(10),' '):18s} acc {r.acc:.4f}±{r.acc_sd:.4f}  AUC {r.auc:.4f}")
    print("② Kausaler DECISION-window Burst (N=20 OOF):")
    for _, r in dc.iterrows():
        print(f"   {int(r.scale):3d}s  acc {r.acc:.4f}±{r.acc_sd:.4f}  AUC {r.auc:.4f}")

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 6.6))
    fig.suptitle("Windowing des RF-Writing-Detektors — zwei Zeitfenster-Achsen",
                 fontweight="bold", fontsize=13)

    # ---- Panel ①: native feature-window (grouped bars acc + AUC) ----------
    x = np.arange(len(sw))
    w = 0.38
    axL.bar(x - w / 2, sw.acc, w, yerr=sw.acc_sd, capsize=3, color=ACC_C,
            label="Accuracy (per Window)", edgecolor="white")
    axL.bar(x + w / 2, sw.auc, w, yerr=sw.auc_sd, capsize=3, color=AUC_C,
            label="ROC-AUC (per Window)", edgecolor="white")
    for xi, a, u in zip(x, sw.acc, sw.auc):
        axL.text(xi - w / 2, a + 0.004, f"{a:.3f}", ha="center", fontsize=8)
        axL.text(xi + w / 2, u + 0.004, f"{u:.3f}", ha="center", fontsize=8)
    axL.set_xticks(x)
    axL.set_xticklabels(sw.label, fontsize=9)
    axL.set_ylim(0.82, 0.97)
    axL.set_ylabel("LOSO-Metrik (Fold-Mittel ± σ)")
    axL.set_xlabel("Feature-Fenstergröße (Roh-IMU pro Fenster)")
    axL.set_title(f"① FEATURE-Fenster — nativ gerechnet (N={sw.n.iloc[0]})")
    axL.grid(axis="y", alpha=0.25)
    axL.legend(loc="lower right", fontsize=8.5)
    axL.annotate("1 s → 3 s: +1.6 pp\n3 s → 5 s: Plateau",
                 xy=(1.0, 0.871), xytext=(1.6, 0.832),
                 fontsize=8.5, fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.3", fc="#FDF6E3", ec="#999", alpha=0.9))

    # ---- Panel ②: causal decision-window (lines w/ band) ------------------
    xs = dc.scale.to_numpy()
    axR.plot(xs, dc.acc, "-o", color=ACC_C, label="Accuracy")
    axR.fill_between(xs, dc.acc - dc.acc_sd, dc.acc + dc.acc_sd, color=ACC_C, alpha=0.15)
    axR.plot(xs, dc.auc, "-s", color=AUC_C, label="ROC-AUC")
    axR.fill_between(xs, dc.auc - dc.auc_sd, dc.auc + dc.auc_sd, color=AUC_C, alpha=0.15)
    for xv, a in zip(xs, dc.acc):
        axR.annotate(f"{a:.3f}", (xv, a), textcoords="offset points", xytext=(6, 5),
                     ha="left", fontsize=7.5, color=ACC_C)
    axR.set_xscale("log")
    axR.set_xticks(xs)
    axR.set_xticklabels([f"{int(s)}s" for s in xs])
    axR.set_ylim(0.75, 0.97)
    axR.set_xlabel("Decision-Fenster (kausale Glättung der 1-s-Probas)")
    axR.set_title("② DECISION-Fenster — kausaler Burst (N=20)")
    axR.grid(alpha=0.25)
    axR.legend(loc="lower left", fontsize=8.5)
    axR.annotate("kausal (kein Look-ahead): Glätten hebt die\nGenauigkeit nicht über das 1-s-Level — es tauscht\nnur Auflösung gegen Stabilität",
                 xy=(5, dc.acc.iloc[3]), xytext=(2.0, 0.775),
                 fontsize=8.5, fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.3", fc="#FDF6E3", ec="#999", alpha=0.9))

    fig.text(0.5, 0.01,
             "① = über wie viele Sekunden ein Feature gerechnet wird (native Metrik, ungeglättet).  "
             "② = wie lange 1-s-Entscheidungen kausal gemittelt werden.  Live läuft 1-s-RF + HMM.",
             ha="center", fontsize=8, style="italic", color="#444")

    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    run()
