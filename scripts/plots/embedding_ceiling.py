"""2D-Embedding des Feature-Raums — die Signal-Ambiguitäts-Decke als Bild.

Projiziert die 88 Headline-Features (legacy-Pool, drawing ausgeschlossen,
per-Session-Z-Score) mit UMAP — oder t-SNE als Fallback ohne ``umap-learn`` —
in 2D und färbt jedes Fenster nach writing/idle. Aussage: in der
Überlappungszone liegen writing- und idle-Fenster räumlich aufeinander; die
schwächsten LOSO-Folds (datengetrieben aus ``loso_oof.csv``) konzentrieren sich
genau dort. Damit ist die Decke kein Modell-Defizit, sondern fehlende
Trennbarkeit *im Signal* — sichtbar statt nur als Fehler-Korrelation.

Zwei Panels:
  A) alle Personen, gefärbt writing vs idle — die globale Überlappung.
  B) dieselbe Projektion, die schwächsten Folds hervorgehoben — sie sitzen
     in der Überlappung, die starken Folds in den reinen Clustern.

CLI::

    python scripts/plots/embedding_ceiling.py
    python scripts/plots/embedding_ceiling.py --method tsne --n 6000
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

from src.training.train_loso import (  # noqa: E402
    _exclude_drawing_windows,
    _filter_pool,
    _load_windows,
    _select_sessions,
    _zscore_per_session,
)

OOF = ROOT / "models" / "loso_oof.csv"
FIG_DIR = ROOT / "reports" / "figures"

# Ruhige, themenahe Palette: writing = warmes Gold, idle = Indigo/Schiefer.
C_WRITING = "#B07A2C"
C_IDLE = "#3B3A6B"
C_REST = "#C9C4D6"


def _weakest_folds(k: int = 3) -> list[str]:
    """Die k schwächsten Personen nach per-Person-1s-Accuracy aus loso_oof.csv."""
    oof = pd.read_csv(OOF)
    oof["pred"] = (oof["proba_raw"] >= 0.5).astype(int)
    acc = oof.groupby("person_id").apply(
        lambda g: (g["pred"] == g["label"]).mean(), include_groups=False)
    order = acc.sort_values()
    print("Per-Person-1s-Accuracy (OOF, aufsteigend):")
    for p, a in order.items():
        print(f"  {p}: {a:.3f}")
    weak = list(order.index[:k])
    print(f"→ schwächste {k}: {weak}")
    return weak


def _build_windows() -> tuple[pd.DataFrame, list[str]]:
    """Headline-identischer all-windows-Frame (legacy, drawing raus, z-score)."""
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


def _subsample(aw: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Stratifiziert nach (person, label) auf ~n Zeilen — erhält Klassen- und
    Fold-Anteile, hält t-SNE/UMAP schnell und den Plot lesbar."""
    if len(aw) <= n:
        return aw.reset_index(drop=True)
    frac = n / len(aw)
    rng = np.random.default_rng(seed)
    parts = []
    for _, g in aw.groupby(["person_id", "label"], sort=False):
        take = max(1, int(round(len(g) * frac)))
        idx = rng.choice(len(g), min(take, len(g)), replace=False)
        parts.append(g.iloc[idx])
    return pd.concat(parts, ignore_index=True)


def _embed(X: np.ndarray, method: str, seed: int) -> tuple[np.ndarray, str]:
    """2D-Embedding; UMAP wenn verfügbar, sonst t-SNE. Returns (coords, label)."""
    if method == "umap":
        try:
            import umap  # noqa: PLC0415
            print("Embedding via UMAP …")
            emb = umap.UMAP(n_neighbors=30, min_dist=0.1, random_state=seed)
            return emb.fit_transform(X), "UMAP"
        except ModuleNotFoundError:
            print("umap-learn nicht installiert → Fallback t-SNE "
                  "(pip install umap-learn für UMAP).")
    from sklearn.manifold import TSNE  # noqa: PLC0415
    print("Embedding via t-SNE …")
    ts = TSNE(n_components=2, init="pca", perplexity=30,
              random_state=seed, n_jobs=-1)
    return ts.fit_transform(X), "t-SNE"


def run(method: str, n: int, seed: int, k_weak: int) -> None:
    weak = _weakest_folds(k_weak)
    aw, feature_cols = _build_windows()
    print(f"Fenster gesamt: {len(aw)} ({len(feature_cols)} Features, "
          f"{aw['person_id'].nunique()} Personen)")
    sub = _subsample(aw, n, seed)
    print(f"Embedding auf {len(sub)} stratifizierten Fenstern …")

    X = sub[feature_cols].to_numpy()
    coords, name = _embed(X, method, seed)
    sub = sub.assign(_x=coords[:, 0], _y=coords[:, 1])
    is_w = sub["label"].to_numpy() == 1
    is_weak = sub["person_id"].isin(weak).to_numpy()

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(13, 6.2))

    # Panel A — globale Klassen-Überlappung.
    axA.scatter(sub["_x"][~is_w], sub["_y"][~is_w], s=4, c=C_IDLE,
                alpha=0.35, linewidths=0, label="idle")
    axA.scatter(sub["_x"][is_w], sub["_y"][is_w], s=4, c=C_WRITING,
                alpha=0.35, linewidths=0, label="writing")
    axA.set_title("Feature-Raum, alle 15 Personen\nwriting vs idle", fontsize=12)
    leg = axA.legend(loc="upper right", markerscale=3, framealpha=0.9)
    for h in leg.legend_handles:
        h.set_alpha(1.0)

    # Panel B — schwache Folds sitzen in der Überlappung.
    axB.scatter(sub["_x"][~is_weak], sub["_y"][~is_weak], s=4, c=C_REST,
                alpha=0.30, linewidths=0, label="starke Folds")
    axB.scatter(sub["_x"][is_weak & ~is_w], sub["_y"][is_weak & ~is_w], s=6,
                c=C_IDLE, alpha=0.7, linewidths=0,
                label=f"schwach · idle")
    axB.scatter(sub["_x"][is_weak & is_w], sub["_y"][is_weak & is_w], s=6,
                c=C_WRITING, alpha=0.7, linewidths=0,
                label=f"schwach · writing")
    axB.set_title(f"Schwächste Folds ({', '.join(weak)})\n"
                  "liegen in der Überlappungszone", fontsize=12)
    leg = axB.legend(loc="upper right", markerscale=3, framealpha=0.9)
    for h in leg.legend_handles:
        h.set_alpha(1.0)

    for ax in (axA, axB):
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_xlabel(f"{name} 1"); ax.set_ylabel(f"{name} 2")

    fig.suptitle("Signal-Ambiguitäts-Decke im Feature-Raum", fontsize=14, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"embedding_ceiling_{name.lower().replace('-', '')}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n→ {out}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--method", choices=["umap", "tsne"], default="umap",
                   help="umap (Fallback t-SNE wenn nicht installiert) oder tsne.")
    p.add_argument("--n", type=int, default=8000,
                   help="Stratifizierte Stichprobe fürs Embedding (Default 8000).")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--k-weak", type=int, default=3,
                   help="Wie viele schwächste Folds hervorheben (Default 3).")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.method, a.n, a.seed, a.k_weak)
