"""Ghost-Replay — Tinte, Handgelenk-Bewegung und Modell-Proba synchron.

Spielt eine echte Aufnahme als Animation ab: oben erscheint die Handschrift
Strich für Strich (Pen ``x/y``), unten laufen Beschleunigungs-Magnitude und die
Live-Schreib-Proba des Modells mit, plus die Pen-Wahrheit als Band. Pen und
Watch werden über das **δ aus der Varianz-Ausrichtung** (``estimate_pen_imu_offset``,
identisch zum Merge) auf dieselbe Capture-Uhr gelegt — die Synchronität ist also
die echte, nicht geschönt.

Wozu: die Signal-Ambiguität wird anfassbar. In einer Denkpause hebt sich der
Stift (oben wächst keine Tinte), aber das Handgelenk bewegt sich weiter wie beim
Schreiben — die Proba bleibt oben. Man *sieht*, warum das Modell dort nicht
trennen kann.

Ausgabe: animiertes GIF (kein ffmpeg nötig).

CLI::

    python scripts/plots/ghost_replay.py
    python scripts/plots/ghost_replay.py --session S019 --start-sec 90 --seconds 36
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
from matplotlib.animation import FuncAnimation, PillowWriter  # noqa: E402

from src.merge.merge import estimate_pen_imu_offset  # noqa: E402

WATCH_DIR = ROOT / "data" / "raw" / "watch"
PEN_DIR = ROOT / "data" / "raw" / "pen"
OOF = ROOT / "models" / "loso_oof.csv"
FIG_DIR = ROOT / "reports" / "figures"

C_WRITING = "#B07A2C"
C_IDLE = "#3B3A6B"
C_INK = "#23202B"
C_TRUTH = "#E7D9B8"
WRITING_DOTS = {"PEN_DOWN", "PEN_MOVE"}


def _load(session: str):
    raw_watch = pd.read_csv(WATCH_DIR / f"{session}_watch.csv")
    raw_pen = pd.read_csv(PEN_DIR / f"{session}_pen.csv")

    res = estimate_pen_imu_offset(raw_pen, raw_watch)
    delta = 0.0
    if res is not None and np.isfinite(res.sigma_minimal_variance) \
            and res.sigma_minimal_variance <= -2.0:
        delta = res.delta_sec
    sigma = res.sigma_minimal_variance if res else float("nan")
    print(f"{session}: δ={delta:+.3f}s  σ={sigma:.2f} "
          f"({'angewandt' if delta else 'σ zu schwach → δ=0'})")

    w = raw_watch.copy()
    w["ts"] = pd.to_numeric(w["ts"], errors="coerce")
    for c in ("ax", "ay", "az"):
        w[c] = pd.to_numeric(w[c], errors="coerce")
    w = w.dropna(subset=["ts", "ax", "ay", "az"]).sort_values("ts")
    w_t = w["ts"].to_numpy()
    acc = np.sqrt(w["ax"] ** 2 + w["ay"] ** 2 + w["az"] ** 2).to_numpy()

    p = raw_pen.copy()
    p["local_ts_ms"] = pd.to_numeric(p["local_ts_ms"], errors="coerce")
    p["x"] = pd.to_numeric(p["x"], errors="coerce")
    p["y"] = pd.to_numeric(p["y"], errors="coerce")
    p = p.dropna(subset=["local_ts_ms", "x", "y"])
    p = p[(p["x"] > -1) & (p["y"] > -1)]            # Framing-Events raus
    p["wall"] = p["local_ts_ms"] + delta * 1000.0
    p = p.sort_values("wall")

    proba_t = proba = label = None
    if OOF.exists():
        oof = pd.read_csv(OOF)
        s = oof[oof["session_id"] == session].sort_values("t_center_ms")
        if not s.empty:
            proba_t = s["t_center_ms"].to_numpy()
            proba = s["proba_raw"].to_numpy()
            label = s["label"].to_numpy()
    return w_t, acc, p, proba_t, proba, label


def _pen_polyline(p: pd.DataFrame):
    """Pen-Down-Punkte als (t, x, y) mit NaN-Brüchen an Stift-Hebungen/Lücken."""
    is_w = p["dot_type"].isin(WRITING_DOTS).to_numpy()
    x = p["x"].to_numpy().astype(float)
    y = p["y"].to_numpy().astype(float)
    t = p["wall"].to_numpy().astype(float)
    x = np.where(is_w, x, np.nan)
    y = np.where(is_w, y, np.nan)
    # Zusätzlich an großen Zeitlücken brechen (neuer Strich nach Pause).
    gap = np.concatenate([[False], np.diff(t) > 400])
    x[gap] = np.nan
    y[gap] = np.nan
    return t, x, y


def _auto_window(label, proba_t, start_sec, seconds):
    """Falls start-sec<0: erstes Fenster mit gemischter Aktivität (Tinte + Pause)."""
    if start_sec >= 0 or proba_t is None:
        return max(start_sec, 0.0)
    t0 = proba_t.min()
    rel = (proba_t - t0) / 1000.0
    for c in np.arange(20, rel.max() - seconds, 4):
        m = (rel >= c) & (rel <= c + seconds)
        if m.sum() > 5 and 0.3 < label[m].mean() < 0.85:
            return float(c)
    return 30.0


def run(session: str, start_sec: float, seconds: float, fps: int,
        step_ms: float) -> None:
    w_t, acc, p, proba_t, proba, label = _load(session)
    pt, px, py = _pen_polyline(p)

    t0 = w_t.min() if proba_t is None else min(w_t.min(), proba_t.min())
    start_sec = _auto_window(label, proba_t, start_sec, seconds)
    lo = t0 + start_sec * 1000.0
    hi = lo + seconds * 1000.0
    print(f"Fenster: {start_sec:.0f}–{start_sec + seconds:.0f}s")

    # Canvas-Grenzen aus den Strichen im Fenster.
    wm = (pt >= lo) & (pt <= hi) & ~np.isnan(px)
    if wm.sum() < 3:
        raise SystemExit("Kaum Tinte im Fenster — anderes start-sec wählen.")
    xlo, xhi = np.nanmin(px[wm]), np.nanmax(px[wm])
    ylo, yhi = np.nanmin(py[wm]), np.nanmax(py[wm])
    xpad, ypad = (xhi - xlo) * 0.08 + 1, (yhi - ylo) * 0.08 + 1

    frames = int(seconds * 1000.0 / step_ms)
    print(f"{frames} Frames @ {fps} fps …")

    fig, (axI, axT) = plt.subplots(
        2, 1, figsize=(9, 8), gridspec_kw={"height_ratios": [3, 1.3]})

    def frame(k):
        tf = lo + k * step_ms
        axI.cla(); axT.cla()

        # --- oben: Handschrift bis tf ---
        upto = pt <= tf
        axI.plot(px[upto & (pt >= lo)], py[upto & (pt >= lo)],
                 color=C_INK, lw=1.6, solid_capstyle="round")
        # aktuelle Stiftspitze
        live = upto & (pt >= lo) & ~np.isnan(px)
        if live.any():
            i = np.where(live)[0][-1]
            recent = (tf - pt[i]) < 250  # Stift gerade aktiv?
            axI.scatter([px[i]], [py[i]], s=40,
                        color=C_WRITING if recent else "#bbb", zorder=5)
        axI.set_xlim(xlo - xpad, xhi + xpad)
        axI.set_ylim(yhi + ypad, ylo - ypad)  # Pen-y nach unten
        axI.set_xticks([]); axI.set_yticks([])

        p_now = float(np.interp(tf, proba_t, proba)) if proba_t is not None else 0.0
        l_now = int(np.interp(tf, proba_t, label) >= 0.5) if proba_t is not None else 0
        pen_active = bool((np.abs(pt - tf) < 200).any() and
                          (live.any() and (tf - pt[i]) < 250))
        state = "schreibt" if p_now >= 0.5 else "idle"
        note = ""
        if l_now == 1 and not pen_active:
            note = "   ✎ Stift angehoben — Modell hält „writing“"
        axI.set_title(f"{session} · t={(tf - lo) / 1000:4.1f}s    "
                      f"P(writing)={p_now:.2f} · {state}{note}",
                      fontsize=11, color=C_WRITING if p_now >= 0.5 else C_IDLE)

        # --- unten: Proba + IMU + Wahrheit + Playhead ---
        if proba_t is not None:
            mask = (proba_t >= lo) & (proba_t <= hi)
            rel = (proba_t[mask] - lo) / 1000.0
            axT.fill_between(rel, 0, 1, where=label[mask] == 1, step="mid",
                             color=C_TRUTH, alpha=0.9, linewidth=0,
                             label="Pen: schreibt")
            axT.plot(rel, proba[mask], color=C_IDLE, lw=1.6, label="P(writing)")
        am = (w_t >= lo) & (w_t <= hi)
        if am.any():
            a = acc[am]
            a = (a - a.min()) / (np.ptp(a) + 1e-9)
            axT.plot((w_t[am] - lo) / 1000.0, a, color="#bbb", lw=0.7,
                     alpha=0.8, label="‖acc‖ (norm.)")
        axT.axvline((tf - lo) / 1000.0, color=C_WRITING, lw=1.5)
        axT.axhline(0.5, color="#999", lw=0.7, ls="--")
        axT.set_xlim(0, seconds); axT.set_ylim(0, 1)
        axT.set_xlabel("Sekunden"); axT.set_yticks([0, 0.5, 1])
        axT.legend(loc="upper right", ncol=3, fontsize=8, framealpha=0.9)
        return []

    anim = FuncAnimation(fig, frame, frames=frames, interval=1000 / fps, blit=False)
    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"ghost_replay_{session}.gif"
    anim.save(out, writer=PillowWriter(fps=fps))
    plt.close(fig)
    print(f"\n→ {out}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session", default="S019",
                   help="Session mit Pen + Watch + OOF (Default S019/P07).")
    p.add_argument("--start-sec", type=float, default=-1.0,
                   help="Startsekunde; <0 = automatisch (gemischte Aktivität).")
    p.add_argument("--seconds", type=float, default=36.0)
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--step-ms", type=float, default=400.0,
                   help="Reale Zeit pro Frame (kleiner = flüssiger, größeres GIF).")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.session, a.start_sec, a.seconds, a.fps, a.step_ms)
