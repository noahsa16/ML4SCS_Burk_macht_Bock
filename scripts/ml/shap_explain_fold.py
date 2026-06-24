"""SHAP-Erklärung einer LOSO-Fold — warum kippt sie, welche Features tragen?

Leakage-ehrlich: rekonstruiert die Headline-Pipeline (legacy-Pool, drawing
ausgeschlossen, per-Session-Z-Score), trainiert den RF auf allen **anderen**
Personen und erklärt die **Held-out**-Person mit ``shap.TreeExplainer`` (exakt
für Tree-Ensembles, kein Sampling). Damit sieht man pro Feature *Richtung* und
Stärke auf genau den Fenstern, die der RF im LOSO nie gesehen hat.

Ohne ``--held-out`` wird die schwächste Fold datengetrieben aus
``models/loso_oof.csv`` gewählt (niedrigste per-Person-1s-Accuracy).

CLI::

    python scripts/ml/shap_explain_fold.py
    python scripts/ml/shap_explain_fold.py --held-out P09 --top 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import shap  # noqa: E402

from src.training.train_loso import (  # noqa: E402
    _exclude_drawing_windows,
    _filter_pool,
    _load_windows,
    _make_classifier,
    _select_sessions,
    _zscore_per_session,
)

OOF = ROOT / "models" / "loso_oof.csv"
FIG_DIR = ROOT / "reports" / "figures"


def _weakest_person() -> str:
    """Per-Person-1s-Accuracy aus loso_oof.csv; gibt die schwächste zurück."""
    oof = pd.read_csv(OOF)
    oof["pred"] = (oof["proba_raw"] >= 0.5).astype(int)
    acc = oof.groupby("person_id").apply(
        lambda g: (g["pred"] == g["label"]).mean(), include_groups=False)
    weakest = acc.idxmin()
    print("Per-Person-1s-Accuracy (OOF):")
    for p, a in acc.sort_values().items():
        mark = "  ← schwächste" if p == weakest else ""
        print(f"  {p}: {a:.3f}{mark}")
    return weakest


def _build_windows() -> tuple[pd.DataFrame, list[str]]:
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


def run(held_out: str | None, top: int, seed: int) -> None:
    held_out = held_out or _weakest_person()
    aw, feature_cols = _build_windows()
    if held_out not in set(aw["person_id"]):
        raise SystemExit(f"Person {held_out!r} nicht in {sorted(set(aw['person_id']))}")

    test = aw[aw["person_id"] == held_out]
    train = aw[aw["person_id"] != held_out]
    clf = _make_classifier("rf", 200, seed)
    clf.fit(train[feature_cols].to_numpy(), train["label"].to_numpy())

    Xte = test[feature_cols].to_numpy()
    yte = test["label"].to_numpy()
    acc = float(((clf.predict(Xte)) == yte).mean())
    print(f"\nFold {held_out}: held-out RF-Accuracy={acc:.3f}  "
          f"(n={len(yte)}, %writing={yte.mean():.2f})")

    # Why: exaktes TreeSHAP ist O(Bäume·Blätter·Tiefe²) pro Sample — auf 200
    # voll ausgewachsenen RF-Bäumen × mehreren tausend Held-out-Fenstern Minuten.
    # Eine Stichprobe (~600) repräsentiert die Feature-Verteilung vollauf; die
    # Accuracy oben läuft weiter auf ALLEN Fenstern.
    rng = np.random.default_rng(seed)
    n_shap = min(600, len(Xte))
    sub = rng.choice(len(Xte), n_shap, replace=False)
    Xshap = Xte[sub]
    print(f"SHAP auf {n_shap}/{len(Xte)} Stichproben-Fenstern…")
    expl = shap.TreeExplainer(clf)
    sv = expl.shap_values(Xshap)
    # shap kann list[class0, class1] ODER (n, f, n_classes) liefern.
    if isinstance(sv, list):
        sv1 = sv[1]
    elif getattr(sv, "ndim", 2) == 3:
        sv1 = sv[..., 1]
    else:
        sv1 = sv

    mean_abs = np.abs(sv1).mean(axis=0)
    signed = sv1.mean(axis=0)  # >0 schiebt Richtung writing
    rank = np.argsort(mean_abs)[::-1][:top]
    print(f"\nTop {top} Features (mean|SHAP|, writing-Klasse) für Fold {held_out}:")
    print(f"  {'feature':<28} {'mean|SHAP|':>10} {'signed':>9}")
    for idx in rank:
        print(f"  {feature_cols[idx]:<28} {mean_abs[idx]:>10.4f} {signed[idx]:>+9.4f}")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"shap_{held_out}.png"
    shap.summary_plot(sv1, Xshap, feature_names=feature_cols, show=False, max_display=top)
    plt.title(f"SHAP — held-out {held_out} (writing-Klasse)")
    plt.tight_layout()
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"\n→ {out}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--held-out", default=None,
                   help="Person-ID; default = schwächste aus loso_oof.csv.")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.held_out, a.top, a.seed)
