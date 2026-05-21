"""Per-Block-Accuracy-Heatmap für die Präsentation.

Trainiert den Headline-RF in einer LOSO-by-person-Schleife, sammelt
auf jedem held-out Fold die Predictions, mappt sie über die
Marker-CSVs auf die 5 Block-Kategorien des Studienprotokolls
(`Mathe-Aufgaben`, `Text abschreiben`, `Freies Schreiben`,
`Pause 1`, `Pause 2`) und rendert für jede Decision-Window-Skala
(1 s / 5 s / 10 s / 30 s) eine 10×5-Heatmap.

Bei Skalen > 1 s wird per-session ein Rolling-Mean über die
Wahrscheinlichkeiten geglättet und bei 0.5 re-threshold (identisch
zur Burst-Aggregation in `train_loso._burst_metrics`).

CLI
---
    python scripts/plots/plot_per_block_heatmap.py                # alle 4 Skalen
    python scripts/plots/plot_per_block_heatmap.py --scales 1 30  # nur ausgewählte
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.training.train_loso import (  # noqa: E402
    _load_windows,
    _select_sessions,
    _zscore_per_session,
)

MARKERS_DIR = ROOT / "data" / "raw" / "markers"
OUT_DIR = ROOT / "reports" / "figures"

WRITING_TASKS = ["Mathe-Aufgaben", "Text abschreiben", "Freies Schreiben"]
PAUSE_LABELS = ["Pause 1", "Pause 2"]
ALL_BLOCKS = WRITING_TASKS + PAUSE_LABELS


def _extract_blocks(markers_path: Path) -> list[dict]:
    """Read markers CSV, return ordered list of {label, start, end} blocks.

    Pauses use task_id='pause' (event=task_start/task_end like writing tasks);
    differentiate them and assign a temporal index ("Pause 1", "Pause 2").
    """
    m = pd.read_csv(markers_path)
    events = m[m["event"].isin(["task_start", "task_end"])].copy()
    blocks: list[dict] = []
    open_b: dict | None = None
    pause_idx = 0
    for _, r in events.iterrows():
        if r["event"] == "task_start":
            if str(r.get("task_id", "")) == "pause":
                pause_idx += 1
                label = f"Pause {pause_idx}"
            else:
                label = r.get("task_name") or ""
            open_b = {"label": label, "start": r["timestamp_ms"]}
        elif r["event"] == "task_end" and open_b:
            open_b["end"] = r["timestamp_ms"]
            blocks.append(open_b)
            open_b = None
    return blocks


def _smooth_proba_per_session(df: pd.DataFrame, scale_sec: float) -> np.ndarray:
    """Per-session rolling mean of `proba` for the given decision-window scale.

    Mirrors `train_loso._burst_metrics`: stride from median Δt_center_ms,
    centered rolling mean, threshold at 0.5 happens downstream.
    """
    if scale_sec <= 1.0:
        return df["proba"].to_numpy()
    out = np.empty(len(df), dtype=float)
    for _, g in df.groupby("session_id", sort=False):
        t = g["t_center_ms"].to_numpy()
        stride_ms = float(np.median(np.diff(t))) if len(t) >= 2 else 500.0
        n = max(1, int(round(scale_sec * 1000.0 / (stride_ms or 500.0))))
        smoothed = g["proba"].rolling(n, center=True, min_periods=1).mean()
        out[g.index.to_numpy()] = smoothed.to_numpy()
    return out


def _render(
    acc: np.ndarray,
    persons: list[str],
    scale_sec: float,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 6.5))
    cmap = plt.get_cmap("RdYlGn")
    # Why: clip to [0.5, 1.0] — below chance is structurally impossible here
    # (RF + balanced classes), and stretching the gradient over the meaningful
    # range makes failure modes pop visually.
    im = ax.imshow(acc, cmap=cmap, vmin=0.5, vmax=1.0, aspect="auto")

    ax.set_xticks(np.arange(len(ALL_BLOCKS)))
    ax.set_xticklabels(ALL_BLOCKS, rotation=20, ha="right")
    ax.set_yticks(np.arange(len(persons)))
    ax.set_yticklabels(persons)

    sep_x = len(WRITING_TASKS) - 0.5
    ax.axvline(sep_x, color="black", linewidth=2.0)
    ax.text(sep_x / 2, -0.7, "writing tasks", ha="center",
            fontsize=10, fontweight="bold", color="#1f2937")
    ax.text(sep_x + 1.5, -0.7, "idle (pauses)", ha="center",
            fontsize=10, fontweight="bold", color="#1f2937")

    for i in range(acc.shape[0]):
        for j in range(acc.shape[1]):
            v = acc[i, j]
            if np.isnan(v):
                ax.text(j, i, "—", ha="center", va="center",
                        color="#6b7280", fontsize=12)
                continue
            color = "white" if v < 0.70 or v > 0.93 else "#0f172a"
            ax.text(j, i, f"{v:.2f}",
                    ha="center", va="center", color=color, fontsize=13,
                    fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Accuracy", fontsize=10)

    ax.set_xlabel("Block (Study Protocol v1)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Held-out Proband (LOSO)", fontsize=11, fontweight="bold")
    scale_str = f"{int(scale_sec)} s" if scale_sec >= 1 else f"{scale_sec} s"
    ax.set_title(
        f"Per-Block Accuracy across LOSO Folds — Decision Window: {scale_str}\n"
        f"Random Forest, per-session z-score, N={len(persons)} Probanden",
        fontsize=12, fontweight="bold", pad=18,
    )

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"→ {out_path.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true")
    ap.add_argument("--scales", type=float, nargs="+", default=[1, 5, 10, 30],
                    help="Decision-Window-Skalen in Sekunden (default: 1 5 10 30)")
    args = ap.parse_args()

    sessions = _select_sessions(args.include_all, 0)
    if sessions.empty:
        raise SystemExit("Keine trainierbaren Sessions gefunden.")

    frames = []
    for _, row in sessions.iterrows():
        df = _load_windows(row["session_id"])
        df["session_id"] = row["session_id"]
        df["person_id"] = row["person_id"]
        frames.append(df)
    all_windows = pd.concat(frames, ignore_index=True)

    feature_cols = [
        c for c in all_windows.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    if not args.no_zscore:
        all_windows = _zscore_per_session(all_windows, feature_cols)

    persons = sorted(sessions["person_id"].dropna().unique())
    print(f"Probanden: {len(persons)}   Sessions: {len(sessions)}   "
          f"Windows: {len(all_windows)}")

    # Collect proba + true label per held-out person
    test_dfs: list[pd.DataFrame] = []
    for held in persons:
        test_mask = all_windows["person_id"] == held
        train = all_windows.loc[~test_mask]
        test = all_windows.loc[test_mask].copy().reset_index(drop=True)
        clf = RandomForestClassifier(
            n_estimators=200, class_weight="balanced",
            n_jobs=-1, random_state=42,
        )
        clf.fit(train[feature_cols], train["label"])
        test["proba"] = clf.predict_proba(test[feature_cols])[:, 1]
        test_dfs.append(test)
        print(f"  trained fold {held:6s}  n_test={len(test):5d}")

    # Render one heatmap per scale
    for scale_sec in args.scales:
        acc = np.full((len(persons), len(ALL_BLOCKS)), np.nan)
        for i, (held, test) in enumerate(zip(persons, test_dfs)):
            smoothed = _smooth_proba_per_session(test, scale_sec)
            pred = (smoothed >= 0.5).astype(int)
            t = test.copy()
            t["pred"] = pred

            sid = t["session_id"].iloc[0]
            mp = MARKERS_DIR / f"{sid}_markers.csv"
            if not mp.exists():
                continue
            for b in _extract_blocks(mp):
                if b["label"] not in ALL_BLOCKS:
                    continue
                j = ALL_BLOCKS.index(b["label"])
                m = (t["t_center_ms"] >= b["start"]) & (t["t_center_ms"] < b["end"])
                rows = t.loc[m]
                if len(rows) == 0:
                    continue
                acc[i, j] = float((rows["pred"] == rows["label"]).mean())

        out_path = OUT_DIR / f"per_block_heatmap_{int(scale_sec)}s.png"
        _render(acc, persons, scale_sec, out_path)


if __name__ == "__main__":
    main()
