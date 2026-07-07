"""Demo: Handschrift vs. Tastatur-Tippen — Apple-Watch-IMU-Schreiberkennung.

Zwei 15-s-Clips aus S050 (Noah), gleiches Layout, für die Abschlusspräsentation:

  * links   — die Watch als **gerendertes PBR-3D-Modell** (pyvista/VTK,
              ``wrist_replay_3d``), das sich live per Attitude-Quaternion neigt;
              ein goldenes Signallicht „zündet", sobald das Modell Schreiben
              erkennt
  * darunter — die Live-Modell-Entscheidung als großer Verdict-Readout
  * rechts   — „Was geschrieben wird": der δ-ausgerichtete Pen-Ink-Trace (Gold)
  * Mitte    — zwei Detektions-Spuren: WAHRHEIT (Stift-Ground-Truth, Anthrazit)
              vs. MODELL (generisch, Proband ungesehen, Gold) + Konfidenz-Kurve
  * unten    — die IMU-Telemetrie (Beschleunigung + Drehrate) mit Playhead

Das Modell ist das **Headline-LOSO** (``models/loso_oof_legacy.csv``, N=20,
Noah als Held-out-Fold → Fenster-Acc 0.890, konsistent mit der 0.869-Headline);
kausaler HMM-Filter aus ``models/hmm_live.json`` @1 Hz für die Entscheidung.

Braucht pyvista (im ``.venv``): ``.venv/bin/python scripts/plots/demo_video.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FFMpegWriter, FuncAnimation  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import wrist_replay_3d as wr  # noqa: E402  (pyvista Watch-Szene)
from src.evaluation.hmm import OnlineForwardFilter  # noqa: E402
from src.features.windows import smooth_labels  # noqa: E402
from src.merge.merge import estimate_pen_imu_offset  # noqa: E402
from src.merge.prep import load_csv  # noqa: E402

SESSION = "S050"
OOF_PATH = ROOT / "models" / "loso_oof_legacy.csv"   # N=20 Headline, Noah held-out
HMM_PATH = ROOT / "models" / "hmm_live.json"
OUT_DIR = ROOT / "reports" / "figures"

SEGMENTS = {
    "writing": {"task": "abschreiben", "start": 1782317802097, "end": 1782317965927,
                "title": "Handschrift", "sub": "Text abschreiben", "select": "ink"},
    "keyboard": {"task": "keyboard_typing", "start": 1782318751617, "end": 1782318871576,
                 "title": "Tastatur tippen", "sub": "dieselbe Hand, keine Tinte",
                 "select": "motion"},
}

# ── Design-Tokens: „Sensor-Telemetrie auf Papier" ────────────────────────────
PAPER = "#EAE7E0"      # warmes Papier (= Watch-Studio-Boden → Watch schwebt darauf)
PAPER_HI = "#F1EEE7"
INK = "#1C1B20"        # Tinten-Schwarz
MUTED = "#6E6A60"      # warmes Grau (Labels)
HAIR = "#CFC9BC"       # Haarlinien
GOLD = "#C6881B"       # DAS Signal: Schreiben (= Watch-Display-Gold)
GOLD_FILL = "#E3AC43"
SLATE = "#8A94A0"      # ruhig / kein Schreiben
ACC_COLORS = ["#A23B2C", "#8A5A2B", "#4C6B2F"]   # ax/ay/az — warme Darks
GYR_COLORS = ["#2E5C7E", "#5B4E8C", "#2E7A6E"]   # rx/ry/rz — kühle Darks

# Font: Mono-Utility (Telemetrie) + saubere Sans (Titel) — kein Editorial-Serif.
_AVAIL = {f.name for f in fm.fontManager.ttflist}
MONO = next((f for f in ("Menlo", "SF Mono", "DejaVu Sans Mono", "Courier New")
             if f in _AVAIL), "monospace")
SANS = next((f for f in ("Helvetica Neue", "Avenir Next", "Helvetica", "Arial",
                         "DejaVu Sans") if f in _AVAIL), "sans-serif")
plt.rcParams.update({
    "font.family": SANS, "text.color": INK, "axes.edgecolor": HAIR,
    "figure.facecolor": PAPER, "savefig.facecolor": PAPER,
})


# ── Daten ────────────────────────────────────────────────────────────────────
def load_session():
    merged = pd.read_csv(ROOT / "data" / "processed" / f"{SESSION}_merged.csv")
    merged = merged.sort_values("ts", kind="stable").reset_index(drop=True)
    raw_pen = load_csv(ROOT / "data" / "raw" / "pen" / f"{SESSION}_pen.csv")
    raw_watch = load_csv(ROOT / "data" / "raw" / "watch" / f"{SESSION}_watch.csv")
    res = estimate_pen_imu_offset(raw_pen, raw_watch)
    delta = res.delta_sec if (res is not None
                              and np.isfinite(res.sigma_minimal_variance)
                              and res.sigma_minimal_variance <= -2.0) else 0.0
    print(f"  Pen↔Watch δ = {delta:+.3f}s")
    return merged, raw_pen, delta


def aligned_ink(raw_pen, delta):
    p = raw_pen.copy()
    p["wt"] = pd.to_numeric(p["local_ts_ms"], errors="coerce") + delta * 1000.0
    p = p[(p["dot_type"] == "PEN_MOVE") & (p["x"] != -1) & (p["y"] != -1)]
    return p.dropna(subset=["wt", "x", "y"]).sort_values("wt")[["wt", "x", "y"]]


def model_series(merged):
    oof = pd.read_csv(OOF_PATH)
    s = oof[oof["session_id"] == SESSION].sort_values("t_center_ms").reset_index(drop=True)
    if s.empty:
        raise SystemExit(f"S050 fehlt in {OOF_PATH}.")
    hp = json.loads(HMM_PATH.read_text())
    flt = OnlineForwardFilter(np.array(hp["transition"]), np.array(hp["priors"]))
    hmm = np.full(len(s), np.nan)
    last = -1e18
    for i, (t, pr) in enumerate(zip(s["t_center_ms"], s["proba_raw"])):
        if t - last >= 900.0:
            hmm[i] = flt.step(float(pr))
            last = t
    s["proba_hmm"] = pd.Series(hmm).ffill()
    s["writing"] = (s["proba_hmm"] >= 0.5).astype(int)
    return s


def pick_start(merged, ink, seg, seconds, override):
    lo, hi, win = seg["start"], seg["end"], seconds * 1000.0
    if override is not None:
        return int(override)
    starts = np.arange(lo + 2000.0, hi - win - 2000.0, 500.0)
    if len(starts) == 0:
        return int(lo)
    if seg["select"] == "ink":
        t = ink["wt"].to_numpy()
        score = [np.sum((t >= st) & (t < st + win)) for st in starts]
    else:
        g = np.sqrt(merged["rx"] ** 2 + merged["ry"] ** 2 + merged["rz"] ** 2).to_numpy()
        ts = merged["ts"].to_numpy()
        score = [g[(ts >= st) & (ts < st + win)].sum() for st in starts]
    return int(starts[int(np.argmax(score))])


# ── Watch-Renderer (pyvista, wiederverwendet aus wrist_replay_3d) ────────────
class WatchRenderer:
    """Persistenter Offscreen-Plotter: setzt pro Frame die Orientierung und die
    Intensität eines goldenen Signallichts (Schreib-„Zündung")."""

    def __init__(self, px=760):
        import pyvista as pv
        self.pv = pv
        pv.OFF_SCREEN = True
        self.p = pv.Plotter(off_screen=True, window_size=(px, px), lighting="none")
        self.p.set_background(PAPER, top=PAPER_HI)
        wr._ensure_studio_env()
        try:
            self.p.set_environment_texture(pv.read_texture(str(wr.STUDIO_ENV)))
        except Exception:  # noqa: BLE001
            pass
        body = wr._load_watch_scene(wr.ARM_RADIUS)
        if body is None:
            raise SystemExit("Watch-Mesh fehlt (scripts/plots/assets/…).")
        self.actor = self.p.add_mesh(body, pbr=True, smooth_shading=True, **wr.CASE_PBR)
        self.p.add_light(pv.Light(position=(5, -4, 7), color="#fff4e6", intensity=1.0))
        self.p.add_light(pv.Light(position=(-6, -2, 3), color="#e8ecff", intensity=0.45))
        self.p.add_light(pv.Light(position=(-3, 5, 5), color="#ffffff", intensity=0.5))
        self.signal = pv.Light(position=(0.5, -2.0, 3.0), color=GOLD_FILL, intensity=0.0)
        self.p.add_light(self.signal)
        self.p.enable_shadows()
        try:
            self.p.enable_ssao(radius=0.12)
        except Exception:  # noqa: BLE001
            pass
        self.p.enable_anti_aliasing("ssaa")
        self.p.camera.SetParallelProjection(False)
        self.p.camera_position = [(1.85, -2.10, 1.5), (0, 0, 0.0), (0, 0, 1)]
        self.p.camera.view_angle = 28
        self.R_align = wr._r_align()

    def render(self, R, glow):
        M = np.eye(4)
        M[:3, :3] = R @ self.R_align
        self.actor.user_matrix = M
        self.signal.intensity = float(2.6 * glow)
        return self.p.screenshot(return_img=True)


# ── Render eines Clips ───────────────────────────────────────────────────────
def render(segment, seconds, fps, override, merged, raw_pen, delta, model, watch):
    seg = SEGMENTS[segment]
    ink_all = aligned_ink(raw_pen, delta)
    start = pick_start(merged, ink_all, seg, seconds, override)
    end = start + int(seconds * 1000)
    print(f"[{segment}] ts=[{start}..{end}]")

    w = merged[(merged["ts"] >= start) & (merged["ts"] <= end)].reset_index(drop=True)
    ts = w["ts"].to_numpy()
    tsec = (ts - start) / 1000.0
    acc = w[["ax", "ay", "az"]].to_numpy()
    gyr = w[["rx", "ry", "rz"]].to_numpy()

    # Watch-Orientierungen (gravity-geeichte Quaternion-Konvention).
    q = w[["qx", "qy", "qz", "qw"]].to_numpy()
    q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12)
    g = w[["gx", "gy", "gz"]].to_numpy()
    g = g / (np.linalg.norm(g, axis=1, keepdims=True) + 1e-12)
    R_all = wr._orientations_from_quaternion(q, g)

    # TRUTH (per-sample closed labels über volle Session, dann slicen).
    full_ts = merged["ts"].to_numpy().astype(float)
    closed = smooth_labels(merged["label_writing"].to_numpy().astype(int), full_ts, 2500.0)
    truth = closed[(merged["ts"] >= start) & (merged["ts"] <= end)]

    # MODEL (Fenster).
    mw = model[(model["t_center_ms"] >= start) & (model["t_center_ms"] <= end)]
    m_t = (mw["t_center_ms"].to_numpy() - start) / 1000.0
    m_raw = mw["proba_raw"].to_numpy()
    m_hmm = mw["proba_hmm"].to_numpy()
    m_dec = mw["writing"].to_numpy()

    # Ink-Fenster → Strokes.
    iw = ink_all[(ink_all["wt"] >= start) & (ink_all["wt"] <= end)]
    strokes = []
    if len(iw) >= 2:
        idx = iw.index.to_numpy()
        cuts = np.where(np.diff(iw["wt"].to_numpy()) > 250.0)[0] + 1
        for chunk in np.split(np.arange(len(iw)), cuts):
            if len(chunk) >= 2:
                sub = iw.iloc[chunk]
                strokes.append((sub["wt"].to_numpy(), sub[["x", "y"]].to_numpy()))
    bbox = iw[["x", "y"]].to_numpy() if len(iw) else np.zeros((0, 2))

    # ── Figure ──
    fig = plt.figure(figsize=(16, 9), facecolor=PAPER)
    gs = fig.add_gridspec(4, 2, height_ratios=[3.1, 0.9, 0.9, 2.0],
                          width_ratios=[1.0, 1.28],
                          left=0.045, right=0.972, top=0.9, bottom=0.075,
                          hspace=0.45, wspace=0.13)
    ax_watch = fig.add_subplot(gs[0, 0])
    ax_ink = fig.add_subplot(gs[0, 1])
    ax_truth = fig.add_subplot(gs[1, :])
    ax_model = fig.add_subplot(gs[2, :])
    gs_imu = gs[3, :].subgridspec(2, 1, hspace=0.12)
    ax_acc = fig.add_subplot(gs_imu[0])
    ax_gyr = fig.add_subplot(gs_imu[1], sharex=ax_acc)

    # Titelzeile.
    fig.text(0.045, 0.945, seg["title"], color=INK, fontsize=30, fontweight="bold",
             family=SANS)
    fig.text(0.045, 0.915, seg["sub"].upper(), color=MUTED, fontsize=12.5, family=MONO)
    fig.text(0.972, 0.945, "APPLE WATCH · NUR IMU", color=MUTED, fontsize=12.5,
             family=MONO, ha="right")
    fig.text(0.972, 0.917, "GENERISCHES MODELL · PROBAND UNGESEHEN + HMM",
             color=MUTED, fontsize=11, family=MONO, ha="right")

    # ── Watch ──
    ax_watch.set_axis_off()
    watch_im = ax_watch.imshow(np.zeros((10, 10, 3), np.uint8))

    # Verdict-Readout unter der Watch (an das Watch-Panel verankert).
    vtxt = ax_watch.text(0.5, 0.18, "", transform=ax_watch.transAxes, ha="center",
                         va="center", fontsize=24, fontweight="bold", family=SANS)
    vsub = ax_watch.text(0.5, 0.07, "", transform=ax_watch.transAxes, ha="center",
                         va="center", fontsize=13, family=MONO, color=MUTED)

    # ── Ink ──
    ax_ink.set_facecolor(PAPER_HI)
    for s in ax_ink.spines.values():
        s.set_color(HAIR)
    ax_ink.set_xticks([]); ax_ink.set_yticks([])
    ax_ink.text(0.02, 1.05, "WAS GESCHRIEBEN WIRD", transform=ax_ink.transAxes,
                color=MUTED, fontsize=12.5, family=MONO, va="bottom")
    ink_lc = LineCollection([], colors=GOLD, linewidths=2.6, capstyle="round")
    ax_ink.add_collection(ink_lc)
    empty = ax_ink.text(0.5, 0.5, "", ha="center", va="center", color=SLATE,
                        fontsize=17, style="italic", transform=ax_ink.transAxes)
    if len(bbox) >= 2:
        x0, y0 = bbox.min(0); x1, y1 = bbox.max(0)
        mx = (x1 - x0) * 0.08 + 1; my = (y1 - y0) * 0.10 + 1
        ax_ink.set_xlim(x0 - mx, x1 + mx); ax_ink.set_ylim(y1 + my, y0 - my)
        ax_ink.set_aspect("equal", adjustable="box")
    else:
        ax_ink.set_xlim(0, 1); ax_ink.set_ylim(0, 1)
        empty.set_text("Stift ruht — keine Tinte")

    # ── Detektions-Spuren ──
    def lane(ax, label):
        ax.set_xlim(0, seconds); ax.set_ylim(0, 1)
        ax.set_yticks([]); ax.set_xticks([])
        for k in ("top", "right", "left", "bottom"):
            ax.spines[k].set_visible(False)
        ax.axvspan(0, seconds, 0.12, 0.88, color="#DCD7C9", lw=0, zorder=0)  # Track
        ax.text(-0.008, 1.28, label, transform=ax.transAxes, ha="left", va="top",
                color=INK, fontsize=12.5, family=MONO, fontweight="bold")

    def bands(ax, t_arr, binary, color):
        b = np.asarray(binary)
        if not len(b):
            return
        edges = np.where(np.diff(b) != 0)[0] + 1
        for chunk in np.split(np.arange(len(b)), edges):
            if b[chunk[0]]:
                ax.axvspan(t_arr[chunk[0]], t_arr[chunk[-1]], 0.12, 0.88,
                           color=color, lw=0)

    lane(ax_truth, "WAHRHEIT · STIFT")
    lane(ax_model, "MODELL · GENERISCH")
    bands(ax_truth, tsec, truth, INK)
    if len(m_t):
        bands(ax_model, m_t, m_dec, GOLD_FILL)
        ax_model.plot(m_t, m_hmm, color=INK, lw=1.5, alpha=0.55)
        ax_model.axhline(0.5, color=HAIR, lw=0.8, ls=(0, (2, 3)))

    # ── IMU-Telemetrie ──
    def telem(ax, arr, cols, names, label):
        for k in range(3):
            ax.plot(tsec, arr[:, k], color=cols[k], lw=1.15)
        ax.set_xlim(0, seconds)
        ax.set_facecolor(PAPER)
        ax.tick_params(colors=MUTED, labelsize=9)
        for k in ("top", "right"):
            ax.spines[k].set_visible(False)
        for k in ("left", "bottom"):
            ax.spines[k].set_color(HAIR)
        chip = dict(facecolor=PAPER, edgecolor="none", alpha=0.78,
                    boxstyle="round,pad=0.2")
        ax.text(0.004, 0.94, label, transform=ax.transAxes, color=MUTED,
                fontsize=11, family=MONO, va="top", bbox=chip)
        for k, nm in enumerate(names):
            ax.text(0.85 + k * 0.045, 0.94, nm, transform=ax.transAxes,
                    color=cols[k], fontsize=11, family=MONO, va="top",
                    fontweight="bold", bbox=chip)
        ax.margins(x=0)

    telem(ax_acc, acc, ACC_COLORS, ["ax", "ay", "az"], "BESCHLEUNIGUNG  g")
    telem(ax_gyr, gyr, GYR_COLORS, ["rx", "ry", "rz"], "DREHRATE  rad/s")
    ax_gyr.set_xlabel("Zeit  ·  Sekunden", color=MUTED, fontsize=11, family=MONO)
    plt.setp(ax_acc.get_xticklabels(), visible=False)

    # ── Playheads ──
    ph = [ax.axvline(0, color=INK, lw=1.3, alpha=0.8)
          for ax in (ax_truth, ax_model, ax_acc, ax_gyr)]

    n_frames = int(seconds * fps)

    def update(frame):
        t = start + (frame / fps) * 1000.0
        rel = (t - start) / 1000.0
        i = min(int(np.searchsorted(ts, t)), len(R_all) - 1)
        # aktueller Modell-Zustand
        j = min(max(int(np.searchsorted(m_t, rel)) - 1, 0), len(m_dec) - 1) if len(m_t) else 0
        wr_now = bool(m_dec[j]) if len(m_t) else False
        p_now = float(m_hmm[j]) if len(m_t) else 0.0
        watch_im.set_data(watch.render(R_all[i], glow=(p_now if wr_now else 0.0)))
        # Ink
        paths = [xy[t_arr <= t] for t_arr, xy in strokes if (t_arr <= t).sum() >= 2]
        ink_lc.set_segments(paths)
        # Verdict
        col = GOLD if wr_now else SLATE
        vtxt.set_text("●  SCHREIBEN" if wr_now else "●  kein Schreiben")
        vtxt.set_color(col)
        vsub.set_text(f"KONFIDENZ  {p_now:4.2f}")
        for line in ph:
            line.set_xdata([rel, rel])
        return [watch_im, ink_lc, vtxt, vsub, *ph]

    anim = FuncAnimation(fig, update, frames=n_frames, interval=1000 / fps, blit=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"demo_{segment}_{int(seconds)}s.mp4"
    print(f"[{segment}] rendere {n_frames} Frames → {out} …")
    anim.save(out, writer=FFMpegWriter(fps=fps, bitrate=8000), dpi=120)
    plt.close(fig)
    print(f"[{segment}] fertig: {out}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--segment", choices=["writing", "keyboard"], default=None)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--start-ms", type=int, default=None)
    args = ap.parse_args()

    print("Lade Session S050 …")
    merged, raw_pen, delta = load_session()
    model = model_series(merged)
    watch = WatchRenderer()
    for s in ([args.segment] if args.segment else ["writing", "keyboard"]):
        render(s, args.seconds, args.fps, args.start_ms, merged, raw_pen, delta,
               model, watch)


if __name__ == "__main__":
    main()
