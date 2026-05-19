"""SVM-RBF Entscheidungsgrenze im PCA-2D-Raum visualisieren.

Lädt alle trainierbaren Sessions wie compare_models.py, z-scored
per-session, projiziert auf 2 PCA-Komponenten, trainiert eine SVM-RBF
*im 2D-Raum* (nicht im 88-D-Feature-Raum — eine Boundary lässt sich nur
dort plotten, wo sie 2D ist) und rendert:

    Links:  Punkte nach writing/idle eingefärbt + SVM-decision-Region
    Rechts: gleiche Projektion, Punkte nach person_id — zeigt ob
            per-session-zscore den Subject-Shift entfernt.

CLI
---
    python scripts/plot_svm_pca.py
    python scripts/plot_svm_pca.py --subsample 5000   # weniger Punkte
    python scripts/plot_svm_pca.py --no-zscore        # ohne Normalisierung
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from sklearn.decomposition import PCA
from sklearn.svm import SVC

ROOT = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT / "data" / "processed"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"
OUT_PATH = ROOT / "reports" / "figures" / "svm_pca.png"
TRAINABLE = {"trainable", "usable"}


def _load_sessions(include_all: bool) -> pd.DataFrame:
    s = pd.read_csv(SESSIONS_CSV)
    if not include_all:
        if "verdict" in s.columns:
            s = s[s["verdict"].isin(TRAINABLE)]
        if "study_mode" in s.columns:
            s = s[s["study_mode"].fillna("") != "test"]
    s = s[s["session_id"].apply(
        lambda x: (DATA_PROC / f"{x}_windows.csv").exists()
    )]
    return s.reset_index(drop=True)


def _load_all_windows(sessions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for sid in sessions["session_id"]:
        df = pd.read_csv(DATA_PROC / f"{sid}_windows.csv")
        df["session_id"] = sid
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )


def _zscore_per_session(df: pd.DataFrame, feat_cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    g = out.groupby("session_id", sort=False)[feat_cols]
    mu = g.transform("mean")
    sigma = g.transform("std").replace(0.0, 1.0).fillna(1.0)
    out[feat_cols] = (out[feat_cols] - mu) / sigma
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true")
    ap.add_argument("--subsample", type=int, default=8000,
                    help="Max Punkte pro Klasse (für Tempo & Lesbarkeit).")
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--gamma", default="scale")
    args = ap.parse_args()

    sessions = _load_sessions(args.include_all)
    if sessions.empty:
        raise SystemExit("Keine trainierbaren Sessions gefunden.")
    all_w = _load_all_windows(sessions)

    feat_cols = [
        c for c in all_w.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    if not args.no_zscore:
        all_w = _zscore_per_session(all_w, feat_cols)

    print(f"Sessions: {len(sessions)}   Windows: {len(all_w)}   "
          f"Features: {len(feat_cols)}   zscore={not args.no_zscore}")

    rng = np.random.default_rng(42)
    parts = []
    for label_val, sub in all_w.groupby("label"):
        n = min(len(sub), args.subsample)
        idx = rng.choice(len(sub), size=n, replace=False)
        parts.append(sub.iloc[idx])
    sample = pd.concat(parts, ignore_index=True)
    print(f"Subsample: {len(sample)} Punkte "
          f"(writing={int((sample['label']==1).sum())}, "
          f"idle={int((sample['label']==0).sum())})")

    X = sample[feat_cols].to_numpy()
    y = sample["label"].to_numpy()
    persons = sample["person_id"].fillna("?").to_numpy()

    pca = PCA(n_components=2, random_state=42)
    Z = pca.fit_transform(X)
    var = pca.explained_variance_ratio_
    print(f"PCA explained variance: PC1={var[0]:.1%}, PC2={var[1]:.1%}, "
          f"total={var.sum():.1%}")

    # SVM in 2D-Raum, damit eine plottbare Entscheidungsgrenze entsteht.
    # Warnung: das ist NICHT das Headline-Modell aus compare_models.py
    # (das fittet in 88-D). Die Boundary ist ein Anschauungsobjekt.
    svm = SVC(kernel="rbf", C=args.C, gamma=args.gamma,
              class_weight="balanced")
    svm.fit(Z, y)
    train_acc = float((svm.predict(Z) == y).mean())
    print(f"SVM-RBF (in PCA-2D) train acc: {train_acc:.3f}   "
          f"(reine Visualisierung, kein LOSO!)")

    pad = 0.5
    x_min, x_max = Z[:, 0].min() - pad, Z[:, 0].max() + pad
    y_min, y_max = Z[:, 1].min() - pad, Z[:, 1].max() + pad
    xx, yy = np.meshgrid(
        np.linspace(x_min, x_max, 400),
        np.linspace(y_min, y_max, 400),
    )
    grid = np.c_[xx.ravel(), yy.ravel()]
    decision = svm.decision_function(grid).reshape(xx.shape)

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), sharex=True, sharey=True)

    # Panel 1: True label + SVM Entscheidungsregion
    ax = axes[0]
    region_cmap = ListedColormap(["#fde2c2", "#c8d8f0"])
    ax.contourf(xx, yy, (decision > 0).astype(int),
                levels=[-0.5, 0.5, 1.5], cmap=region_cmap, alpha=0.55)
    ax.contour(xx, yy, decision, levels=[0], colors="black",
               linewidths=1.5, linestyles="--")
    for lbl, color, name in [(0, "#d97706", "idle"), (1, "#1d4ed8", "writing")]:
        m = y == lbl
        ax.scatter(Z[m, 0], Z[m, 1], s=6, c=color, alpha=0.35,
                   label=f"{name} (n={m.sum()})", edgecolors="none")
    ax.set_title(
        f"SVM-RBF Entscheidungsgrenze in PCA-2D  "
        f"(C={args.C}, γ={args.gamma}, train acc={train_acc:.2f})",
        fontsize=11,
    )
    ax.set_xlabel(f"PC1 ({var[0]:.1%} Varianz)")
    ax.set_ylabel(f"PC2 ({var[1]:.1%} Varianz)")
    ax.legend(loc="upper right", framealpha=0.9, fontsize=9)
    ax.grid(alpha=0.2)

    # Panel 2: per Proband eingefärbt
    ax = axes[1]
    unique_persons = sorted(set(persons))
    cmap = plt.get_cmap("tab10", max(len(unique_persons), 3))
    for i, pid in enumerate(unique_persons):
        m = persons == pid
        ax.scatter(Z[m, 0], Z[m, 1], s=6, c=[cmap(i)], alpha=0.45,
                   label=f"{pid} (n={m.sum()})", edgecolors="none")
    ax.set_title(
        f"Gleiche Projektion, eingefärbt nach Proband  "
        f"({'mit' if not args.no_zscore else 'ohne'} per-session z-score)",
        fontsize=11,
    )
    ax.set_xlabel(f"PC1 ({var[0]:.1%} Varianz)")
    ax.legend(loc="upper right", framealpha=0.9, fontsize=8, ncol=2)
    ax.grid(alpha=0.2)

    fig.suptitle(
        f"SVM-RBF Visualisierung — {len(sessions)} Sessions, "
        f"{len(unique_persons)} Probanden, {len(feat_cols)} Features → PCA-2D",
        fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=140, bbox_inches="tight")
    print(f"→ {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
