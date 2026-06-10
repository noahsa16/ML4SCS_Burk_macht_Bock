"""SVM-RBF Entscheidungsgrenze im PCA-3D-Raum visualisieren.

Analog zu plot_svm_pca.py, aber 3 PCA-Komponenten. Die SVM-Boundary
ist in 3D eine 2D-Fläche (Isosurface `decision_function == 0`), die
via Marching Cubes aus einem 3D-Decision-Grid extrahiert wird.

Zwei 3D-Panels: links Punkte nach writing/idle + Isosurface, rechts
gleiche Projektion nach person_id (Subject-Shift-Diagnose).

CLI
---
    python scripts/plots/plot_svm_pca_3d.py
    python scripts/plots/plot_svm_pca_3d.py --grid 60 --subsample 5000
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from skimage import measure
from sklearn.decomposition import PCA
from sklearn.svm import SVC

from src.profiles import find_windows

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"
OUT_PATH = ROOT / "reports" / "figures" / "svm_pca_3d.png"
OUT_GIF = ROOT / "reports" / "figures" / "svm_pca_3d.gif"
OUT_MP4 = ROOT / "reports" / "figures" / "svm_pca_3d.mp4"
TRAINABLE = {"trainable", "usable"}


def _gif_to_mp4(gif_path: Path, mp4_path: Path, fps: int) -> None:
    # Why: libx264 verlangt gerade Pixel-Höhe; matplotlib-Frames sind oft
    # ungerade (z.B. 675 px) und würden den Encoder mit Invalid-Argument
    # killen. Eine schwarze Pixelzeile padden ist verlustlos und unsichtbar.
    import imageio.v3 as iio

    frames = np.asarray(iio.imread(gif_path, index=None))
    n, h, w, c = frames.shape
    if h % 2 == 1:
        frames = np.concatenate(
            [frames, np.zeros((n, 1, w, c), dtype=frames.dtype)], axis=1
        )
    if w % 2 == 1:
        frames = np.concatenate(
            [frames, np.zeros((n, frames.shape[1], 1, c), dtype=frames.dtype)],
            axis=2,
        )
    iio.imwrite(
        mp4_path, frames, fps=fps, codec="libx264",
        quality=9, macro_block_size=1,
    )


def _load_sessions(include_all: bool) -> pd.DataFrame:
    s = pd.read_csv(SESSIONS_CSV)
    if not include_all:
        if "verdict" in s.columns:
            s = s[s["verdict"].isin(TRAINABLE)]
        if "study_mode" in s.columns:
            s = s[s["study_mode"].fillna("") != "test"]
    s = s[s["session_id"].apply(
        lambda x: find_windows(x) is not None
    )]
    return s.reset_index(drop=True)


def _load_all_windows(sessions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for sid in sessions["session_id"]:
        df = pd.read_csv(find_windows(sid))
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


def _svm_isosurface(svm: SVC, lo: np.ndarray, hi: np.ndarray, n: int):
    """Marching-Cubes-Extraktion von decision_function == 0 in 3D."""
    xs = np.linspace(lo[0], hi[0], n)
    ys = np.linspace(lo[1], hi[1], n)
    zs = np.linspace(lo[2], hi[2], n)
    grid = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), axis=-1)
    flat = grid.reshape(-1, 3)
    vol = svm.decision_function(flat).reshape(n, n, n)
    try:
        verts, faces, _, _ = measure.marching_cubes(vol, level=0.0)
    except (ValueError, RuntimeError):
        return None
    # Verts sind in Voxel-Indizes — zurück in Welt-Koordinaten skalieren.
    scale = (hi - lo) / (n - 1)
    verts = verts * scale + lo
    return verts, faces


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true")
    ap.add_argument("--subsample", type=int, default=6000)
    ap.add_argument("--grid", type=int, default=55,
                    help="Auflösung des 3D-Decision-Grids (n³ Punkte).")
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--gamma", default="scale")
    ap.add_argument("--no-surface", action="store_true",
                    help="Isosurface weglassen (nur Scatter).")
    ap.add_argument("--rotate-gif", action="store_true",
                    help="Zusätzlich rotierendes GIF rendern.")
    ap.add_argument("--gif-frames", type=int, default=60)
    ap.add_argument("--gif-fps", type=int, default=20)
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
    for _, sub in all_w.groupby("label"):
        n = min(len(sub), args.subsample)
        idx = rng.choice(len(sub), size=n, replace=False)
        parts.append(sub.iloc[idx])
    sample = pd.concat(parts, ignore_index=True)
    print(f"Subsample: {len(sample)} "
          f"(writing={int((sample['label']==1).sum())}, "
          f"idle={int((sample['label']==0).sum())})")

    X = sample[feat_cols].to_numpy()
    y = sample["label"].to_numpy()
    persons = sample["person_id"].fillna("?").to_numpy()

    pca = PCA(n_components=3, random_state=42)
    Z = pca.fit_transform(X)
    var = pca.explained_variance_ratio_
    print(f"PCA: PC1={var[0]:.1%}, PC2={var[1]:.1%}, PC3={var[2]:.1%}, "
          f"total={var.sum():.1%}")

    svm = SVC(kernel="rbf", C=args.C, gamma=args.gamma,
              class_weight="balanced")
    svm.fit(Z, y)
    train_acc = float((svm.predict(Z) == y).mean())
    print(f"SVM-RBF (PCA-3D) train acc: {train_acc:.3f} (Visualisierung!)")

    pad = 0.5
    lo = Z.min(axis=0) - pad
    hi = Z.max(axis=0) + pad

    surf = None
    if not args.no_surface:
        print(f"Marching cubes auf {args.grid}³ Grid …")
        surf = _svm_isosurface(svm, lo, hi, args.grid)
        if surf is None:
            print("  (keine Isosurface gefunden — vermutlich einseitige Decision)")

    fig = plt.figure(figsize=(16, 7.5))
    ax1 = fig.add_subplot(1, 2, 1, projection="3d")
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")

    # Panel 1: True-Label + SVM Isosurface
    if surf is not None:
        verts, faces = surf
        mesh = Poly3DCollection(verts[faces], alpha=0.18,
                                facecolor="#9ca3af", edgecolor="none")
        ax1.add_collection3d(mesh)

    for lbl, color, name in [(0, "#d97706", "idle"), (1, "#1d4ed8", "writing")]:
        m = y == lbl
        ax1.scatter(Z[m, 0], Z[m, 1], Z[m, 2], s=4, c=color, alpha=0.4,
                    label=f"{name} (n={m.sum()})", depthshade=True,
                    edgecolors="none")
    ax1.set_title(
        f"SVM-RBF Isosurface (decision=0) in PCA-3D\n"
        f"C={args.C}, γ={args.gamma}, train acc={train_acc:.2f}",
        fontsize=11,
    )
    ax1.set_xlabel(f"PC1 ({var[0]:.1%})")
    ax1.set_ylabel(f"PC2 ({var[1]:.1%})")
    ax1.set_zlabel(f"PC3 ({var[2]:.1%})")
    ax1.legend(loc="upper left", framealpha=0.9, fontsize=9)
    ax1.view_init(elev=22, azim=-58)

    # Panel 2: nach Proband
    unique_persons = sorted(set(persons))
    cmap = plt.get_cmap("tab10", max(len(unique_persons), 3))
    for i, pid in enumerate(unique_persons):
        m = persons == pid
        ax2.scatter(Z[m, 0], Z[m, 1], Z[m, 2], s=4, c=[cmap(i)],
                    alpha=0.5, label=f"{pid} (n={m.sum()})",
                    depthshade=True, edgecolors="none")
    ax2.set_title(
        f"Gleiche Projektion, nach Proband\n"
        f"({'mit' if not args.no_zscore else 'ohne'} per-session z-score)",
        fontsize=11,
    )
    ax2.set_xlabel(f"PC1 ({var[0]:.1%})")
    ax2.set_ylabel(f"PC2 ({var[1]:.1%})")
    ax2.set_zlabel(f"PC3 ({var[2]:.1%})")
    ax2.legend(loc="upper left", framealpha=0.9, fontsize=8, ncol=2)
    ax2.view_init(elev=22, azim=-58)

    fig.suptitle(
        f"SVM-RBF 3D-Visualisierung — {len(sessions)} Sessions, "
        f"{len(unique_persons)} Probanden, {len(feat_cols)} Features → PCA-3D "
        f"(Var. erklärt: {var.sum():.1%})",
        fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=140, bbox_inches="tight")
    print(f"→ {OUT_PATH.relative_to(ROOT)}")

    if args.rotate_gif:
        # Why: 3D-Boundary lebt von Parallaxe — eine Rotation zeigt, dass
        # die Isosurface eine echte 3D-Hülle ist und kein 2D-Artefakt.
        print(f"Rendere rotierendes GIF ({args.gif_frames} Frames "
              f"@ {args.gif_fps} fps) …")
        azim0 = -58

        def _update(frame):
            angle = azim0 + (360.0 * frame / args.gif_frames)
            ax1.view_init(elev=22, azim=angle)
            ax2.view_init(elev=22, azim=angle)
            return ()

        anim = animation.FuncAnimation(
            fig, _update, frames=args.gif_frames,
            interval=1000 / args.gif_fps, blit=False,
        )
        writer = animation.PillowWriter(fps=args.gif_fps)
        anim.save(OUT_GIF, writer=writer, dpi=90)
        print(f"→ {OUT_GIF.relative_to(ROOT)}")

        try:
            _gif_to_mp4(OUT_GIF, OUT_MP4, fps=args.gif_fps)
            print(f"→ {OUT_MP4.relative_to(ROOT)}")
        except Exception as e:
            print(f"  (MP4-Export übersprungen: {e})")


if __name__ == "__main__":
    main()
