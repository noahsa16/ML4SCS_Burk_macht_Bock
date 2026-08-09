"""HP-Grid-Leaderboard (Legacy-Pool) als praesentations-fertige Folie.

Liest die von scripts/ml/pull_wandb_runs.py gezogene wandb-CSV, filtert auf
den Legacy-Pool (50 Hz, 88 Features, Cross-Subject grouped-5-fold), rankt je
Architektur den besten Config und rendert einen horizontalen Balken-Leaderboard
mit RF-Referenz-Leiter (roh-1s -> +HMM kausal -> +HMM nicht-kausal).

Design nach dem dataviz-Skill: Familien-Farben aus der validierten Referenz-
Palette (CVD-safe), direkte Wertelabels (Relief-Regel), eine Achse, RF als
Referenzlinien statt Balken. Ehrlichkeits-Layer: 3-Seed-Mittel als Diamant, wo
ein sauberes Multi-Seed vorliegt (deckt die Selektions-Inflation auf), plus
Seed-Rausch-Band-Note.

CLI: python scripts/plots/plot_hp_leaderboard.py [--csv PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = ROOT / "models" / "hp_grid" / "wandb_runs_fresh.csv"
OUT_DIR = ROOT / "reports" / "figures"

# --- Referenz-Palette (dataviz, validiert CVD-safe light-mode) --------------
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

# Architektur-Familien -> (Slot-Farbe, Sortier-Rang fuer Legende)
FAMILY_COLOR = {
    "TCN+RNN Hybrid":   "#2a78d6",   # blau  (Slot 1)
    "TCN (pur)":        "#1baf7a",   # aqua  (Slot 2)
    "RNN (pur)":        "#eda100",   # gelb  (Slot 3)
    "CNN (Inception)":  "#4a3aa7",   # violett (Slot 5)
    "Transformer":      "#e34948",   # rot   (Slot 6)
    "TCN+Transformer":  "#eb6834",   # orange (Slot 8)
}

# model-id -> Familie
FAMILY_OF = {
    "tcn_gru": "TCN+RNN Hybrid", "tcn_bigru": "TCN+RNN Hybrid",
    "tcn_bigru_attn": "TCN+RNN Hybrid", "tcn_gru_attn": "TCN+RNN Hybrid",
    "tcn_bigru_w32_24": "TCN+RNN Hybrid", "tcn_bigru_w64_16": "TCN+RNN Hybrid",
    "tcn": "TCN (pur)", "tcn6": "TCN (pur)", "tcn6ap": "TCN (pur)",
    "tcn6k5": "TCN (pur)", "tcn6se": "TCN (pur)", "tcn6w32": "TCN (pur)",
    "tcn6wn": "TCN (pur)", "tcn8": "TCN (pur)",
    "gru2": "RNN (pur)", "bigru": "RNN (pur)",
    "inception": "CNN (Inception)",
    "transformer": "Transformer", "transformer_p5": "Transformer",
    "tcn_transformer": "TCN+Transformer",
}

# RF-Referenz-Leiter (Legacy). Deep = grouped-5-fold; HMM = LOSO-20 (≈ 5-fold,
# 0.867 vs 0.871). Nicht-kausaler Smoother = Offline-Obergrenze (Tagestracker).
RF_LADDER = [
    ("RF · 1s-Fenster (roh)",              0.867, ":",  MUTED),
    ("RF-1s + HMM (kausal, live)",         0.899, "--", "#256abf"),
    ("RF-1s + HMM (nicht-kausal, offline)", 0.918, "-.", "#104281"),
]
SEED_NOISE_PP = 0.017  # GPU-Nichtdeterminismus-Floor, CLAUDE.md


def build_leaderboard(csv: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(csv)
    leg = df[df["pool"] == "legacy"].copy()
    # Nur Runs mit N=20 Probanden einbeziehen (Läufe vor dem N=22 Quality Refresh am 07.07.2026)
    if "created_at" in leg.columns:
        leg = leg[leg["created_at"] < "2026-07-07"].copy()

    rows = []
    for model, g in leg.groupby("model"):
        best = g.loc[g["cv_mean_acc"].idxmax()]
        rows.append({
            "model": model,
            "family": FAMILY_OF.get(model, "Transformer"),
            "acc": float(best["cv_mean_acc"]),
            "auc": float(best["cv_mean_auc"]),
            "cfg": best["cfg_id"],
            "n_cfg": len(g),
        })
    lb = pd.DataFrame(rows).sort_values("acc", ascending=True).reset_index(drop=True)
    meta = {"n_models": len(lb), "n_runs": len(leg)}
    return lb, meta


def render(lb: pd.DataFrame, meta: dict, out_stem: Path) -> None:
    n = len(lb)
    fig, ax = plt.subplots(figsize=(11, 8.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    y = np.arange(n)
    colors = [FAMILY_COLOR[f] for f in lb["family"]]
    ax.barh(y, lb["acc"], height=0.66, color=colors, zorder=3,
            edgecolor=SURFACE, linewidth=1.2)

    # direkte Wertelabels (Relief-Regel + Lesbarkeit)
    for yi, (acc, auc) in enumerate(zip(lb["acc"], lb["auc"])):
        ax.text(acc + 0.0015, yi, f"{acc:.3f}", va="center", ha="left",
                fontsize=9.5, color=INK, fontweight="bold")
        ax.text(acc - 0.004, yi, f"AUC {auc:.3f}", va="center", ha="right",
                fontsize=7.6, color="#f4f7fb")



    ax.set_yticks(y)
    ax.set_yticklabels(lb["model"], fontsize=10, color=INK)
    ax.set_xlim(0.855, 0.945)
    ax.set_xlabel("Grouped-5-fold Accuracy (Cross-Subject, Legacy-Pool · nativ 5 s)",
                  fontsize=10.5, color=INK2)

    # RF-Referenz-Leiter
    for label, val, ls, col in RF_LADDER:
        ax.axvline(val, ls=ls, lw=1.5, color=col, zorder=2, alpha=0.8)
        # Kurze, saubere Beschriftung über der oberen Achsenbegrenzung (keine Überlappung mit Balken)
        short_label = "roh" if "roh" in label else ("live" if "live" in label else "offline")
        ax.text(val, 1.01, f"{val:.3f} ({short_label})", transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=8, color=col, fontweight="bold")

    # Seed-Rausch-Band um den Spitzenreiter
    top = lb["acc"].max()
    ax.axvspan(top - SEED_NOISE_PP, top, color="#2a78d6", alpha=0.06, zorder=1)

    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(length=0, colors=MUTED)

    ax.set_title("Deep-Architektur-Leaderboard vs. RF-Baseline",
                 fontsize=16, color=INK, fontweight="bold", loc="left", pad=40)
    ax.text(0, 1.055, f"HP-Grid, {meta['n_runs']} Legacy-Runs · N=20 Probanden · "
            "bester Config je Architektur (bester Seed)",
            transform=ax.transAxes, fontsize=10, color=INK2)

    # Familien-Legende + Marker-Erklaerung
    fam_order = [f for f in FAMILY_COLOR if f in set(lb["family"])]
    handles = [Patch(facecolor=FAMILY_COLOR[f], label=f) for f in fam_order]
    handles += [
        Patch(facecolor="#2a78d6", alpha=0.14, label="Seed-Rausch-Band ±1.7 pp"),
    ]
    # RF-Referenz-Leiter in die Legende einfügen
    for label, val, ls, col in RF_LADDER:
        clean_label = label.replace("RF · 1s-Fenster (roh)", "RF (roh) · 1s-Fenster") \
                           .replace("RF-1s + HMM (kausal, live)", "RF-1s + HMM (kausal, live)") \
                           .replace("RF-1s + HMM (nicht-kausal, offline)", "RF-1s + HMM (nicht-kausal, offline)")
        handles.append(Line2D([0], [0], color=col, linestyle=ls, lw=1.5,
                              label=f"{clean_label} ({val:.3f})"))

    # Zweispaltige, übersichtliche Legende im leeren Bereich unten rechts
    ax.legend(handles=handles, loc="lower right", fontsize=8.0, frameon=False,
              ncol=2, handlelength=1.5, labelspacing=0.5, columnspacing=1.5)

    cap = ("Deep: grouped-5-fold (≈ LOSO, 0.867 vs 0.871).  RF+HMM: LOSO-20; "
           "nicht-kausaler Smoother = Offline-Obergrenze (Tagestracker), nicht live.  "
           "Eine Decke, mehrere Straßen: RF-1s+HMM ≈ nativer Deep-5s — "
           "der HMM- und der 5s-Kontext-Gewinn sind derselbe, nicht stapelbar.")
    fig.text(0.012, 0.008, cap, fontsize=7.6, color=MUTED, wrap=True)

    fig.subplots_adjust(left=0.17, right=0.965, top=0.86, bottom=0.11)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(out_stem.with_suffix(f".{ext}"), facecolor=SURFACE,
                    bbox_inches="tight")
    print(f"gespeichert -> {out_stem.with_suffix('.png')}  (+ .svg)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = p.parse_args()
    lb, meta = build_leaderboard(args.csv)
    print(lb.to_string(index=False))
    render(lb, meta, OUT_DIR / "hp_leaderboard_legacy")


if __name__ == "__main__":
    main()
