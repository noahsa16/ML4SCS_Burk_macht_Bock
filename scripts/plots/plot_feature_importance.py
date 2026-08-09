"""Welche Features trägt der Writing-Detektor? — erklärende Präsi-Abbildung.

Rekonstruiert die Headline-Pipeline (legacy-Pool, drawing ausgeschlossen,
per-Session-Z-Score), fittet den RF auf ALLEN Legacy-Personen und liest die
Impurity-Feature-Importance. Ausgabe ist eine zweiteilige Abbildung:

  Links:  Top-N Einzel-Features als horizontale Balken, farbcodiert nach der
          semantischen Gruppe, zu der das Feature gehört.
  Rechts: die 6 Feature-GRUPPEN, aufsummiert — das ist die belastbare Kern-
          aussage (robust gegen die Impurity-Aufteilung zwischen korrelierten
          Einzel-Features).

Methodik-Hinweis (für die Präsi ehrlich): Impurity-Importance ist der Standard-
„feature importance"-Wert eines Random Forest. Bei stark korrelierten Features
verteilt er den Beitrag zwischen den Partnern — deshalb ist die GRUPPEN-Summe
die vertrauenswürdige Ebene, das Einzel-Ranking illustrativ. Der Fit läuft auf
allen Daten (kein Held-out): es ist eine Interpretations-Frage („worauf schaut
das Modell"), keine Generalisierungs-Behauptung.

CLI::

    python scripts/plots/plot_feature_importance.py
    python scripts/plots/plot_feature_importance.py --top 20 --seed 42
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from src.training.train_loso import (  # noqa: E402
    _exclude_drawing_windows,
    _filter_pool,
    _load_windows,
    _make_classifier,
    _select_sessions,
    _zscore_per_session,
)

OUT = ROOT / "reports" / "figures" / "feature_importance.png"

# Semantische Gruppen + Präsi-Farben (deuteranopie-freundliche Palette).
GROUPS: dict[str, str] = {
    "time_stats": "#4F8FCF",    # blau
    "spectral": "#E08A3C",      # orange
    "jerk": "#C0392B",          # rot
    "zcr": "#27AE60",           # grün
    "magnitude": "#8E44AD",     # violett
    "correlation": "#7F8C8D",   # grau
}
GROUP_LABEL_DE = {
    "time_stats": "Zeit-Statistik (mean/std/min/max/rms/range)",
    "spectral": "Spektral (Dom.-Freq., Zentroid, Entropie, 3–8 Hz)",
    "jerk": "Jerk (Ruck = d/dt der Beschleunigung)",
    "zcr": "Nulldurchgangsrate (ZCR)",
    "magnitude": "Magnitude (Betrag Accel/Gyro: mean/std/energy)",
    "correlation": "Kreuzachsen-Korrelation",
}


def feature_group(name: str) -> str:
    """Ordne einen Feature-Namen einer der 6 semantischen Gruppen zu."""
    if "jerk" in name:
        return "jerk"
    if name.startswith("corr_"):
        return "correlation"
    if name.endswith("_zcr"):
        return "zcr"
    if any(k in name for k in ("dom_freq", "spec_centroid", "spec_entropy", "band_3_8")):
        return "spectral"
    if "_mag_" in name:  # acc_mag_mean/std/energy, gyro_mag_… (jerk schon oben abgefangen)
        return "magnitude"
    return "time_stats"


def build_windows() -> tuple[pd.DataFrame, list[str]]:
    """Headline-identischer all_windows-Frame (legacy, drawing raus, z-score)."""
    sessions = _select_sessions(include_all=False, min_windows=0, profile="50hz")
    frames = [_load_windows(s, "50hz") for s in sessions["session_id"]]
    aw = pd.concat(frames, ignore_index=True).merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left")
    aw = _exclude_drawing_windows(aw)
    aw = _filter_pool(aw, "legacy")
    feature_cols = [c for c in aw.columns if c not in {
        "label", "t_center_ms", "session_id", "person_id",
        "task_id", "task_category"}]
    aw = _zscore_per_session(aw, feature_cols)
    return aw, feature_cols


def run(top: int, seed: int) -> None:
    aw, feature_cols = build_windows()
    n_persons = aw["person_id"].nunique()
    print(f"Legacy-Pool: {len(aw)} Fenster, {n_persons} Personen, {len(feature_cols)} Features")

    clf = _make_classifier("rf", 200, seed)
    clf.fit(aw[feature_cols].to_numpy(), aw["label"].to_numpy())
    imp = clf.feature_importances_

    df = pd.DataFrame({"feature": feature_cols, "importance": imp})
    df["group"] = df["feature"].map(feature_group)
    df = df.sort_values("importance", ascending=False).reset_index(drop=True)

    gsum = df.groupby("group")["importance"].sum().reindex(list(GROUPS)).fillna(0.0)
    gcnt = df.groupby("group")["importance"].size().reindex(list(GROUPS)).fillna(0).astype(int)
    gmean = (gsum / gcnt.replace(0, np.nan)).fillna(0.0)   # Importance pro Feature (fair)
    gmean = gmean.sort_values(ascending=False)

    print(f"\nTop {top} Einzel-Features:")
    for _, r in df.head(top).iterrows():
        print(f"  {r['feature']:<22} {r['importance']:.4f}  [{r['group']}]")
    print("\nGruppen — Importance pro Feature (fair) | Gesamt-Anteil:")
    for g in gmean.index:
        print(f"  {g:<14} pro-Feat {gmean[g]:.4f}  | Summe {gsum[g]*100:4.1f} %  ({gcnt[g]} Features)")

    # ---- Figure -----------------------------------------------------------
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(15, 8.8), gridspec_kw={"width_ratios": [1.35, 1]})
    fig.suptitle(
        f"Feature-Wichtigkeit des Writing-Detektors  ·  RF · Legacy-Pool "
        f"(N={n_persons}, 88 Features)",
        fontweight="bold", fontsize=13)

    # Linkes Panel: Top-N Einzel-Features, nach Gruppe eingefärbt.
    topdf = df.head(top).iloc[::-1]  # kleinster oben → größter unten umgedreht für barh
    colors = [GROUPS[g] for g in topdf["group"]]
    axL.barh(range(len(topdf)), topdf["importance"], color=colors, edgecolor="white", linewidth=0.5)
    axL.set_yticks(range(len(topdf)))
    axL.set_yticklabels(topdf["feature"], fontsize=8.5)
    axL.set_xlabel("Impurity-Importance (Anteil)")
    axL.set_title(f"① Top-{top} Einzel-Features")
    axL.grid(axis="x", alpha=0.25)

    # Rechtes Panel: Importance PRO Feature (fair gegen Gruppengröße) — die
    # belastbare Kernaussage. Annotiert mit Feature-Anzahl + Gesamt-Anteil.
    gcolors = [GROUPS[g] for g in gmean.index]
    gpos = list(range(len(gmean)))[::-1]
    axR.barh(gpos, gmean.values, color=gcolors, edgecolor="white", linewidth=0.5)
    axR.set_yticks(gpos)
    axR.set_yticklabels([g for g in gmean.index], fontsize=10, fontweight="bold")
    for y, g in zip(gpos, gmean.index):
        axR.text(gmean[g] + 0.0004, y, f"{gcnt[g]} Feat · Σ {gsum[g]*100:.0f} %",
                 va="center", fontsize=8.5)
    axR.set_xlabel("Ø Importance pro Feature")
    axR.set_title("② Gruppen — normiert pro Feature")
    axR.set_xlim(0, float(gmean.max()) * 1.32)
    axR.grid(axis="x", alpha=0.25)

    # Fußbereich: erst die Panels layouten, dann Methodik-Zeile + Legende
    # klar getrennt darunter setzen (verhindert das Überlappen).
    fig.tight_layout(rect=(0, 0.14, 1, 0.96))

    fig.text(0.5, 0.105,
             "Impurity-Importance eines Random Forest, gefittet auf allen Legacy-Personen. "
             "② normiert pro Feature (fair gegen Gruppengröße): Jerk ist einzeln am stärksten — die Fein-Motorik-Signatur des Schreibens.",
             ha="center", fontsize=8, style="italic", color="#444")

    # Legende (Gruppen-Beschriftung) ganz unten, deutlich unter der Methodik-Zeile.
    handles = [plt.Rectangle((0, 0), 1, 1, color=GROUPS[g]) for g in GROUPS]
    labels = [GROUP_LABEL_DE[g] for g in GROUPS]
    fig.legend(handles, labels, loc="lower center", ncol=2, fontsize=8.5,
               frameon=False, bbox_to_anchor=(0.5, 0.005))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"\n→ {OUT}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top", type=int, default=18)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.top, a.seed)
