"""Run the Swiss pen↔IMU alignment on a session and produce an explanatory plot.

The figure has 4 panels:

  Top row:    IMU acceleration-variance v(t) over time, with the pen stroke
              intervals overlaid — left: raw (δ=0), right: shifted by δ*.
              The visual story: at the right δ, the stroke bands sit in the
              low-variance valleys (wrist still while writing). At the wrong
              δ they sit on top of high-variance arm motion.

  Bottom row: J(δ) = mean variance under the shifted stroke mask, the
              objective the algorithm minimises. Left: coarse search;
              right: fine search around the coarse minimum. A clear narrow
              well = strong alignment; a flat curve = weak alignment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.alignment import (
    pen_match,
    reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)

DATA_RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "alignment"

COARSE_START, COARSE_END, COARSE_STEP = -25.0, 25.0, 0.5
FINE_HALF, FINE_STEP = 5.0, 0.01
VAR_WINDOW_SEC = 0.2
SIGMA_THRESHOLD = -2.0


def _load(session: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_pen = pd.read_csv(DATA_RAW / "pen" / f"{session}_pen.csv")
    raw_watch = pd.read_csv(DATA_RAW / "watch" / f"{session}_watch.csv")
    pen_ts = pd.to_datetime(pd.to_numeric(raw_pen["local_ts_ms"], errors="coerce"), unit="ms", utc=True)
    pen_for = pd.DataFrame({
        "timestamp": pen_ts,
        "dot_type": raw_pen.get("dot_type", ""),
        "x": pd.to_numeric(raw_pen.get("x"), errors="coerce"),
        "y": pd.to_numeric(raw_pen.get("y"), errors="coerce"),
    }).dropna(subset=["timestamp"])
    strokes = strokes_from_dot_types(pen_for)
    watch_ts = reconstruct_watch_wall_clock(raw_watch)
    watch = pd.DataFrame({
        "timestamp": watch_ts,
        "ax": pd.to_numeric(raw_watch.get("ax"), errors="coerce"),
        "ay": pd.to_numeric(raw_watch.get("ay"), errors="coerce"),
        "az": pd.to_numeric(raw_watch.get("az"), errors="coerce"),
    }).dropna().sort_values("timestamp").reset_index(drop=True)
    return watch, strokes


def _variance_signal(watch: pd.DataFrame) -> pd.Series:
    diffs = watch["timestamp"].diff().dropna()
    fs = 1.0 / diffs.median().total_seconds()
    W = max(2, int(VAR_WINDOW_SEC * fs))
    acc = watch[["ax", "ay", "az"]].astype(np.float32)
    g_norm = float(np.sqrt((acc ** 2).sum(axis=1)).median()) or 1.0
    v = acc.rolling(window=W, center=True).var()
    return np.sqrt((v ** 2).sum(axis=1)) / g_norm


def _draw_strokes(ax, watch_t: pd.Series, strokes: pd.DataFrame, delta_sec: float, color: str) -> None:
    """Shade in-stroke regions on the watch timeline after shifting strokes by δ."""
    t0 = watch_t.iloc[0]
    t_end = watch_t.iloc[-1]
    shift = pd.Timedelta(seconds=delta_sec)
    drawn = 0
    for _, row in strokes.groupby("StrokeID")["timestamp"].agg(["min", "max"]).iterrows():
        a = row["min"] + shift
        b = row["max"] + shift
        if b < t0 or a > t_end:
            continue
        a_s = (max(a, t0) - t0).total_seconds()
        b_s = (min(b, t_end) - t0).total_seconds()
        ax.axvspan(a_s, b_s, color=color, alpha=0.25, linewidth=0)
        drawn += 1
    return drawn


def _plot_variance_panel(ax, watch: pd.DataFrame, var_sig: pd.Series, strokes: pd.DataFrame,
                         delta_sec: float, title: str, stroke_color: str) -> None:
    t0 = watch["timestamp"].iloc[0]
    t_rel = (watch["timestamp"] - t0).dt.total_seconds()
    ax.plot(t_rel, var_sig.values, color="#2C3E50", linewidth=0.6, alpha=0.85, label="v(t)")
    n_drawn = _draw_strokes(ax, watch["timestamp"], strokes, delta_sec, stroke_color)
    ax.set_xlabel("Watch time (s, session-relative)")
    ax.set_ylabel("Normalized variance v(t)")
    ax.set_title(title)
    ax.grid(alpha=0.25)
    p99 = float(np.nanpercentile(var_sig, 99))
    ax.set_ylim(0, p99 * 1.1 if np.isfinite(p99) and p99 > 0 else None)
    handles = [plt.Line2D([0], [0], color="#2C3E50", linewidth=0.6, label="IMU variance v(t)"),
               plt.Rectangle((0, 0), 1, 1, color=stroke_color, alpha=0.4,
                             label=f"pen strokes ({n_drawn})")]
    ax.legend(handles=handles, loc="upper right", fontsize=8)


def _plot_objective(ax, series: pd.Series, best_delta: float, color: str, title: str,
                    annotate_extra: str = "") -> None:
    ax.plot(series.index, series.values, color=color, linewidth=1.1)
    ax.axvline(best_delta, color="black", linestyle="--", linewidth=1)
    ymin, ymax = ax.get_ylim()
    ax.annotate(f"δ* = {best_delta:.3f} s\n{annotate_extra}",
                xy=(best_delta, series.min()),
                xytext=(8, 12), textcoords="offset points",
                fontsize=9, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="black", alpha=0.85))
    ax.set_xlabel("Pen shift δ (s)")
    ax.set_ylabel("J(δ) = mean variance in stroke mask")
    ax.set_title(title)
    ax.grid(alpha=0.25)


def run(session: str, out_path: Path) -> dict:
    watch, strokes = _load(session)
    var_sig = _variance_signal(watch)

    print(f"[{session}] coarse search …")
    (coarse_d, _), coarse = pen_match(watch, strokes, COARSE_START, COARSE_END, COARSE_STEP)
    print(f"[{session}] fine search around {coarse_d:.2f}s …")
    (fine_d, fine_min), fine = pen_match(watch, strokes, coarse_d - FINE_HALF, coarse_d + FINE_HALF, FINE_STEP)
    sigma = float((fine_min - fine.mean()) / fine.std())
    verdict = "STRONG (trusted)" if sigma <= SIGMA_THRESHOLD else "WEAK (rejected)"
    print(f"[{session}] δ* = {fine_d:.3f}s | σ = {sigma:.2f} → {verdict}")

    fig, axes = plt.subplots(2, 2, figsize=(15, 9))
    quality = "good" if sigma <= SIGMA_THRESHOLD else "bad"
    fig.suptitle(
        f"Pen ↔ IMU alignment · session {session} · σ = {sigma:.2f} · {verdict}",
        fontweight="bold", fontsize=13,
    )

    _plot_variance_panel(
        axes[0][0], watch, var_sig, strokes, delta_sec=0.0,
        title="① Raw: stroke mask at δ = 0  (before alignment)",
        stroke_color="#C0392B",
    )
    _plot_variance_panel(
        axes[0][1], watch, var_sig, strokes, delta_sec=fine_d,
        title=f"② Aligned: stroke mask shifted by δ* = {fine_d:.2f} s",
        stroke_color="#27AE60",
    )

    _plot_objective(
        axes[1][0], coarse, coarse_d, "#4F8FCF",
        title=f"③ Coarse search J(δ)  ({COARSE_START:.0f}…{COARSE_END:.0f}s, step {COARSE_STEP}s)",
        annotate_extra="coarse min",
    )
    _plot_objective(
        axes[1][1], fine, fine_d, "#E08A3C",
        title=f"④ Fine search J(δ)  (±{FINE_HALF:.0f}s, step {FINE_STEP}s)",
        annotate_extra=f"σ = {sigma:.2f}",
    )

    fig.text(
        0.5, 0.005,
        "Algorithmus: für jeden Kandidaten-Shift δ wird der Stroke-Mask um δ verschoben und der Mittelwert von v(t) "
        "innerhalb des Masks berechnet. δ* = argmin J(δ).  Tiefes, schmales Tal in J → vertrauenswürdig (σ ≤ -2).",
        ha="center", fontsize=8.5, style="italic", color="#444",
    )

    fig.tight_layout(rect=(0, 0.025, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"[{session}] saved → {out_path}")
    return {"session": session, "delta_sec": fine_d, "sigma": sigma, "quality": quality}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sessions", nargs="*", help="z. B. S016 S017 — default: S016 S017")
    args = parser.parse_args()
    sessions = args.sessions or ["S016", "S017"]
    for s in sessions:
        run(s, OUT_DIR / f"{s}_alignment.png")


if __name__ == "__main__":
    main()
