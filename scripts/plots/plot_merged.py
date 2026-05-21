"""Visualisiere ein watch-base gemergtes Session-CSV.

Zeigt Accelerometer-Magnitude, Gyro-Magnitude und das ``label_writing``
über die Zeit. Schreib-Phasen werden als grüne Hintergrundbänder
hinterlegt — so sieht man auf einen Blick, wie die IMU-Signatur in
Schreib- vs. Idle-Momenten aussieht.

Aufruf::

    python scripts/plots/plot_merged.py            # neueste merged CSV
    python scripts/plots/plot_merged.py S029       # spezifische Session
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.features.windows import smooth_labels  # noqa: E402
DATA_PROC = ROOT / "data" / "processed"
_MERGED_RE = re.compile(r"^(S\d+)_merged\.csv$")


def _latest_session() -> str:
    sessions = sorted(
        m.group(1)
        for p in DATA_PROC.glob("S*_merged.csv")
        if (m := _MERGED_RE.match(p.name))
    )
    if not sessions:
        raise SystemExit("Keine *_merged.csv unter data/processed/.")
    return sessions[-1]


def _writing_segments(t: np.ndarray, label: np.ndarray) -> list[tuple[float, float]]:
    """Return [(t_start, t_end), …] für zusammenhängende Schreib-Bereiche."""
    segs: list[tuple[float, float]] = []
    in_run = False
    start = 0.0
    for i, lab in enumerate(label):
        if lab == 1 and not in_run:
            in_run = True
            start = t[i]
        elif lab == 0 and in_run:
            in_run = False
            segs.append((start, t[i]))
    if in_run:
        segs.append((start, t[-1]))
    return segs


def plot_session(
    sid: str,
    out: Path | None = None,
    max_gap_ms: float = 0.0,
    max_spike_ms: float = 0.0,
) -> Path:
    path = DATA_PROC / f"{sid}_merged.csv"
    if not path.exists():
        raise SystemExit(f"{path} fehlt — vorher `python -m src.merge {sid}` laufen lassen.")
    df = pd.read_csv(path)

    df = df.sort_values("local_ts_ms").reset_index(drop=True)
    t = (df["local_ts_ms"] - df["local_ts_ms"].iloc[0]) / 1000.0  # → sec
    t = t.to_numpy()
    acc_mag = np.linalg.norm(df[["ax", "ay", "az"]].to_numpy(), axis=1)
    gyro_mag = np.linalg.norm(df[["rx", "ry", "rz"]].to_numpy(), axis=1)
    label = df["label_writing"].to_numpy().astype(int)
    t_ms = df["local_ts_ms"].to_numpy().astype(float)
    if max_gap_ms > 0 or max_spike_ms > 0:
        label = smooth_labels(
            label, t_ms, max_gap_ms=max_gap_ms, max_spike_ms=max_spike_ms,
        )

    segs = _writing_segments(t, label)
    n_writing = int((label == 1).sum())
    n_idle = len(label) - n_writing

    fig, axes = plt.subplots(3, 1, figsize=(13, 7), sharex=True)

    for ax_, ydata, title, ylabel in [
        (axes[0], acc_mag, f"Session {sid} — Watch IMU mit Pen-Label-Overlay",
         "‖acc‖  [g]"),
        (axes[1], gyro_mag, "", "‖gyro‖  [rad/s]"),
    ]:
        for s, e in segs:
            ax_.axvspan(s, e, color="tab:green", alpha=0.15, lw=0)
        ax_.plot(t, ydata, lw=0.6, color="black")
        ax_.set_ylabel(ylabel)
        if title:
            ax_.set_title(title)
        ax_.grid(alpha=0.3)

    axes[2].fill_between(t, 0, label, step="post", color="tab:green", alpha=0.6)
    axes[2].set_ylabel("label_writing")
    axes[2].set_yticks([0, 1])
    axes[2].set_xlabel("Zeit seit Session-Start  [s]")
    axes[2].grid(alpha=0.3)

    pct = n_writing / len(label) * 100 if len(label) else 0.0
    axes[0].legend(
        [plt.Rectangle((0, 0), 1, 1, fc="tab:green", alpha=0.3)],
        [f"writing — {n_writing} samples ({pct:.0f}%) | idle — {n_idle}"],
        loc="upper right",
        framealpha=0.9,
    )

    fig.tight_layout()
    out = out or (DATA_PROC / f"{sid}_merged.png")
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"Plot gespeichert: {out}")
    print(
        f"Session {sid}: {len(df)} Watch-Samples | "
        f"{n_writing} writing / {n_idle} idle | "
        f"{len(segs)} Schreib-Segmente"
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="plot_merged.py")
    parser.add_argument("session", nargs="?", help="z. B. S029 — default: neueste Session")
    parser.add_argument("--out", type=Path, help="Ausgabepfad")
    parser.add_argument("--max-gap-ms", type=float, default=0.0,
                        help="Label-Glättung: Idle-Lücken ≤ X ms zwischen writing → writing.")
    parser.add_argument("--max-spike-ms", type=float, default=0.0,
                        help="Label-Glättung: writing-Spitzen ≤ X ms zwischen idle → idle.")
    args = parser.parse_args()
    sid = args.session or _latest_session()
    plot_session(sid, args.out, args.max_gap_ms, args.max_spike_ms)


if __name__ == "__main__":
    main()
