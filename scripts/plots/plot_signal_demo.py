"""Präsentationsfiguren: Watch-IMU bei Schreiben vs. Idle.

Zwei 28-s-Ausschnitte aus einer Session — Schreiben vs. geplante Pause —
mit gemeinsamer y-Achse, plus Pen-Truth-Streifen. Rendert je eine Figur
für Accelerometer- und Gyroskop-Magnitude.

Aufruf::

    python scripts/plots/plot_signal_demo.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_PROC = ROOT / "data" / "processed"
FIG_DIR = ROOT / "reports" / "figures"

SESSION = "S007"
WRITE_WINDOW = (93.0, 121.0)   # abschreiben
IDLE_WINDOW = (325.0, 353.0)   # geplante Pause


def _slice(df: pd.DataFrame, t0: float, t1: float) -> pd.DataFrame:
    win = df[(df["t"] >= t0) & (df["t"] < t1)].copy()
    win["t_rel"] = win["t"] - t0
    return win


def _render(w: pd.DataFrame, i: pd.DataFrame, col: str,
            ylabel: str, title: str, out: Path) -> None:
    ymax = max(w[col].max(), i[col].max()) * 1.05
    ymin = min(w[col].min(), i[col].min()) * 0.95

    fig, axes = plt.subplots(
        2, 2, figsize=(14, 5), sharex="col",
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.12, "wspace": 0.13},
    )
    panels = [
        (axes[0, 0], axes[1, 0], w, "Schreiben", "tab:green"),
        (axes[0, 1], axes[1, 1], i, "Idle (Pause)", "tab:blue"),
    ]
    for ax_sig, ax_lab, win, ptitle, color in panels:
        ax_sig.plot(win["t_rel"], win[col], lw=0.7, color="black")
        ax_sig.set_ylim(ymin, ymax)
        ax_sig.set_title(ptitle, fontsize=12, fontweight="bold", pad=8)
        ax_sig.grid(alpha=0.3)

        lab = win["label_writing"].to_numpy().astype(int)
        ax_lab.fill_between(win["t_rel"], 0, lab, step="post",
                            color=color, alpha=0.6)
        ax_lab.set_ylim(0, 1)
        ax_lab.set_yticks([0, 1])
        ax_lab.set_yticklabels(["idle", "write"], fontsize=8)
        ax_lab.set_xlabel("Zeit  [s]")
        ax_lab.grid(alpha=0.3)

    axes[0, 0].set_ylabel(ylabel)
    axes[1, 0].set_ylabel("Pen-Truth")
    axes[0, 1].tick_params(labelleft=False)

    fig.suptitle(title, fontsize=12.5, fontweight="bold", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    print(f"Plot gespeichert: {out}")


def main() -> None:
    path = DATA_PROC / f"{SESSION}_merged.csv"
    if not path.exists():
        raise SystemExit(f"{path} fehlt.")
    df = pd.read_csv(path).sort_values("local_ts_ms").reset_index(drop=True)
    df["t"] = (df["local_ts_ms"] - df["local_ts_ms"].iloc[0]) / 1000.0
    df["acc_mag"] = np.linalg.norm(df[["ax", "ay", "az"]].to_numpy(), axis=1)
    df["gyro_mag"] = np.linalg.norm(df[["rx", "ry", "rz"]].to_numpy(), axis=1)

    w = _slice(df, *WRITE_WINDOW)
    i = _slice(df, *IDLE_WINDOW)

    _render(w, i, "acc_mag", "‖acc‖  [g]",
            f"Apple Watch ‖acc‖  —  Schreiben vs. Idle  (Session {SESSION})",
            FIG_DIR / "signal_demo.png")
    _render(w, i, "gyro_mag", "‖gyro‖  [rad/s]",
            f"Apple Watch ‖gyro‖  —  Schreiben vs. Idle  (Session {SESSION})",
            FIG_DIR / "signal_demo_gyro.png")


if __name__ == "__main__":
    main()
