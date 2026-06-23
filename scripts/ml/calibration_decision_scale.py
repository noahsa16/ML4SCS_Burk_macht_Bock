#!/usr/bin/env python
"""Kalibrierung auf der Decision-Scale (Phase 2).

Das bestehende Reliability-Diagramm misst die **1-s**-Proba. Dieses Skript
beantwortet die Produkt-Frage: sind die Wahrscheinlichkeiten ehrlich *auf der
Skala, die das Produkt tatsaechlich anzeigt*? Es bewertet ECE + Brier +
Reliability-Kurve fuer mehrere Decision-Scale-Probas, alle leakage-frei auf
``models/loso_oof.csv`` (``proba_cal`` ist bereits per-fold isoton kalibriert):

  - ``raw 1s``     — rohe RF-Proba (``proba_raw``); RFs sind notorisch mis-kalibriert
  - ``cal 1s``     — isoton kalibrierte 1-s-Proba (``proba_cal``); Baseline
  - ``burst {5,10,30}s`` — kausaler Rolling-Mean von ``proba_cal`` (Aggregat-Pfad;
    Mitteln zieht zur Mitte -> Verdacht: unter-konfident)
  - ``HMM-filter`` — kausaler Forward-Filter-Posterior (Deploy-Kandidat; sticky
    Prior -> Verdacht: ueber-konfident)

CLI
---
    python scripts/ml/calibration_decision_scale.py [--bins 10]

Output: ``reports/figures/calibration_decision_scale.png`` +
``reports/calibration_decision_scale.md``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import brier_score_loss  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.evaluation.calibration import (  # noqa: E402
    expected_calibration_error,
    reliability_curve,
)
from src.evaluation.hmm import (  # noqa: E402
    class_priors,
    estimate_transition_matrix,
    forward_filter,
    scaled_likelihoods,
)
from src.training.train_loso import _causal_rolling_mean  # noqa: E402

OOF_PATH = ROOT / "models" / "loso_oof.csv"
FIG_OUT = ROOT / "reports" / "figures" / "calibration_decision_scale.png"
REPORT_OUT = ROOT / "reports" / "calibration_decision_scale.md"

BURST_SCALES = (5, 10, 30)
# Welche Kurven in die Figur (lesbar halten): die Decision-Scale-Story.
FIG_METHODS = ["raw 1s", "cal 1s", "burst 5s", "burst 30s", "HMM-filter"]


def _stride_ms(t: np.ndarray) -> float:
    s = float(np.median(np.diff(t))) if len(t) >= 2 else 500.0
    return s or 500.0


def _burst_proba(oof: pd.DataFrame, scale_sec: int) -> tuple[np.ndarray, np.ndarray]:
    """Pooled (y, kausal geglaettete proba_cal) ueber alle Sessions, per Session."""
    ys, ps = [], []
    for _, g in oof.sort_values(["session_id", "t_center_ms"]).groupby(
            "session_id", sort=False):
        n = max(1, int(round(scale_sec * 1000.0 / _stride_ms(g["t_center_ms"].to_numpy()))))
        ps.append(_causal_rolling_mean(g["proba_cal"].to_numpy(), n))
        ys.append(g["label"].to_numpy())
    return np.concatenate(ys), np.concatenate(ps)


def _hmm_proba(oof: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Pooled (y, HMM-Filter-Posterior), leakage-frei per-Person-Holdout."""
    persons = list(dict.fromkeys(oof["person_id"]))
    ys, ps = [], []
    for H in persons:
        tr = oof[oof["person_id"] != H]
        te = (oof[oof["person_id"] == H]
              .sort_values(["session_id", "t_center_ms"]).reset_index(drop=True))
        A = estimate_transition_matrix(
            [g.sort_values("t_center_ms")["label"].to_numpy()
             for _, g in tr.groupby("session_id", sort=False)], smoothing=1.0)
        pri = class_priors(tr["label"].to_numpy())
        for _, g in te.groupby("session_id", sort=False):
            ps.append(forward_filter(scaled_likelihoods(g["proba_cal"].to_numpy(), pri), A, pri)[:, 1])
            ys.append(g["label"].to_numpy())
    return np.concatenate(ys), np.concatenate(ps)


def _collect(oof: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    y = oof["label"].to_numpy()
    out = {
        "raw 1s": (y, oof["proba_raw"].to_numpy()),
        "cal 1s": (y, oof["proba_cal"].to_numpy()),
    }
    for s in BURST_SCALES:
        out[f"burst {s}s"] = _burst_proba(oof, s)
    out["HMM-filter"] = _hmm_proba(oof)
    return out


def _metrics(data: dict, n_bins: int) -> dict[str, dict[str, float]]:
    return {
        name: {
            "ece": expected_calibration_error(y, p, n_bins),
            "brier": float(brier_score_loss(y, p)),
        }
        for name, (y, p) in data.items()
    }


def _figure(data: dict, n_bins: int) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.plot([0, 1], [0, 1], "--", color="#0f172a", lw=2, label="perfekt kalibriert")
    colors = plt.cm.viridis(np.linspace(0.0, 0.85, len(FIG_METHODS)))
    for name, c in zip(FIG_METHODS, colors):
        if name not in data:
            continue
        y, p = data[name]
        mp, fp, _ = reliability_curve(y, p, n_bins)
        m = ~np.isnan(mp)
        ece = expected_calibration_error(y, p, n_bins)
        ax.plot(mp[m], fp[m], "o-", color=c, lw=2, ms=5, label=f"{name}  (ECE {ece:.3f})")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect("equal", "box")
    ax.set_xlabel("Vorhergesagte Wahrscheinlichkeit P(writing)", fontweight="bold")
    ax.set_ylabel("Tatsaechlicher writing-Anteil", fontweight="bold")
    ax.set_title("Decision-Scale-Kalibrierung — sind die Probas ehrlich?", fontweight="bold")
    ax.legend(loc="upper left", framealpha=0.95)
    ax.grid(True, alpha=0.25)
    FIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_OUT, dpi=150, bbox_inches="tight")


def _build_report(m: dict, n: int, n_bins: int) -> str:
    L: list[str] = []
    L.append("# Decision-Scale-Kalibrierung (Phase 2)\n")
    L.append(
        f"Sind die Wahrscheinlichkeiten ehrlich auf der Skala, die das Produkt "
        f"anzeigt? ECE (Erwarteter Kalibrierungsfehler, < 0.05 = gut) + Brier "
        f"(niedriger = besser) je Decision-Scale-Proba, leakage-frei auf "
        f"`loso_oof.csv` (N={n}, `proba_cal` ist per-fold isoton). "
        f"Figur: `reports/figures/{FIG_OUT.name}`.\n")

    L.append("| Methode | ECE | Brier |")
    L.append("|---|---|---|")
    order = ["raw 1s", "cal 1s", "burst 5s", "burst 10s", "burst 30s", "HMM-filter"]
    for name in order:
        if name in m:
            L.append(f"| {name} | {m[name]['ece']:.4f} | {m[name]['brier']:.4f} |")
    L.append("")

    raw_e, cal_e = m["raw 1s"]["ece"], m["cal 1s"]["ece"]
    raw_b, cal_b = m["raw 1s"]["brier"], m["cal 1s"]["brier"]
    L.append("## Befunde\n")
    L.append(
        f"- **Die 1-s-RF-Proba ist schon ehrlich.** ECE roh `proba_raw` "
        f"{raw_e:.4f} (< 0.05 = gut); die isotone `proba_cal` — fuer die "
        f"Regressions-Stufe eingefuehrt — verbessert das **nicht** "
        f"(ECE {cal_e:.4f}, Brier {raw_b:.4f} → {cal_b:.4f}, beides minimal "
        f"schlechter). Das per-Session-Z-Score + `class_weight=balanced` liefert "
        f"von Haus aus brauchbare Wahrscheinlichkeiten — fuers Produkt ist die "
        f"rohe 1-s-Proba bereits kalibriert, keine Nach-Kalibrierung noetig.\n")

    b5, b10, b30 = (m[f"burst {s}s"]["ece"] for s in (5, 10, 30))
    bb5, bb30 = m["burst 5s"]["brier"], m["burst 30s"]["brier"]
    L.append(
        f"- **Burst-Aggregation verschlechtert die Kalibrierung.** ECE steigt "
        f"(cal-1s {cal_e:.4f} → burst-5s {b5:.4f} → -10s {b10:.4f} → -30s "
        f"{b30:.4f}; am schlechtesten bei 5 s), und der **Brier waechst monoton** "
        f"mit der Fensterlaenge ({cal_b:.4f} → {bb5:.4f} → {bb30:.4f}) — "
        f"Aufloesungsverlust, weil das Mitteln die Probas zur Basisrate zieht. "
        f"Die *thresholdete* Schreibzeit-Entscheidung bleibt davon unberuehrt; "
        f"nur ein als Konfidenz **angezeigter** Aggregat-Proba waere unter-konfident.\n")

    h_e, h_b = m["HMM-filter"]["ece"], m["HMM-filter"]["brier"]
    L.append(
        f"- **Der HMM-Filter ist die nuetzlichste Proba — aber leicht "
        f"ueber-konfident.** Bester Brier des Panels ({h_b:.4f} < roh {raw_b:.4f}: "
        f"schaerfste *und* im Schnitt treffsicherste Probas), aber erhoehte ECE "
        f"({h_e:.4f} > 0.05): der sticky Prior treibt die Konfidenz zu 0/1 — "
        f"leichte Ueber-Konfidenz, **Vorhersage bestaetigt**. Deployment: "
        f"1-s-RF+HMM liefert die beste Entscheidungs-Proba; soll die Pille einen "
        f"*ehrlichen Prozentwert* zeigen, lohnt eine leichte Nach-Kalibrierung des "
        f"Posteriors (Platt/isoton, per-fold).\n")

    L.append(
        "**Caveat:** ECE/Brier sind pooled ueber alle Folds; die Kalibrierung "
        "kann per Person streuen. Fuer Deployment-Konfidenz zaehlt der "
        "Decision-Scale-Wert, nicht die 1-s-Zahl.\n")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bins", type=int, default=10, help="Bins fuer ECE/Reliability")
    args = ap.parse_args()

    if not OOF_PATH.exists():
        raise SystemExit(f"OOF fehlt: {OOF_PATH} — erst train_loso --save-oof laufen lassen.")
    oof = pd.read_csv(OOF_PATH)
    n_persons = oof["person_id"].nunique()

    data = _collect(oof)
    m = _metrics(data, args.bins)
    _figure(data, args.bins)
    REPORT_OUT.write_text(_build_report(m, n_persons, args.bins), encoding="utf-8")

    print(f"Decision-Scale-Kalibrierung (N={n_persons}, bins={args.bins}):")
    for name in ["raw 1s", "cal 1s", "burst 5s", "burst 10s", "burst 30s", "HMM-filter"]:
        print(f"  {name:12s}  ECE {m[name]['ece']:.4f}  Brier {m[name]['brier']:.4f}")
    print(f"→ {FIG_OUT.relative_to(ROOT)}")
    print(f"→ {REPORT_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
