"""Render the paper-ready figures for report/figures/ from the N=32 artefacts.

Inputs (all read-only):
  models/runs/pod_20260825/results/loso_oof_legacy.csv   RF out-of-fold probabilities
  models/hmm_postprocess_detail.csv                      per-person decoder metrics (N=32)
  data/raw/markers/*.csv                                 task blocks for per-task error rates
  data/raw/{watch,pen}/S039_*.csv                        alignment example
  data/processed/S055_merged.csv + markers               raw-signal example

Usage: python scripts/plots/report_figures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "plots"))

from scripts.ml.marker_fpr import assign_task, parse_task_blocks  # noqa: E402
from src.alignment import pen_match  # noqa: E402
from plot_alignment import _load as _load_alignment, _variance_signal  # noqa: E402

OUT = ROOT / "report" / "figures"
OOF = ROOT / "models" / "runs" / "pod_20260825" / "results" / "loso_oof_legacy.csv"
DETAIL = ROOT / "models" / "hmm_postprocess_detail.csv"
MARKERS = ROOT / "data" / "raw" / "markers"

matplotlib.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.titlesize": 9.5,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
})
BLUE, ORANGE, GREY, GREEN, RED = "#1f4e79", "#c55a11", "#7f7f7f", "#2e7d32", "#b71c1c"

TASK_LABELS = {
    "keyboard_typing": "Tastatur tippen",
    "phone_typing": "Handy tippen",
    "pen_fidgeting": "Stift in der Hand",
    "phone_scrolling": "Handy scrollen",
    "pause": "Pause",
    "gesturing": "Gestikulieren",
    "abschreiben": "Abschreiben",
    "free_writing": "Freies Schreiben",
    "math": "Mathe",
    "soft_writing": "Leises Schreiben",
    "think_pause_writing": "Schreiben mit Denkpausen",
}


def _save(fig: plt.Figure, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf")
    fig.savefig(OUT / f"{name}.png", dpi=200)
    plt.close(fig)
    print(f"saved {name}.pdf + .png")


def fig_signal_example() -> None:
    merged = pd.read_csv(ROOT / "data" / "processed" / "S055_merged.csv")
    markers = parse_task_blocks(pd.read_csv(MARKERS / "S055_markers.csv"))
    merged = merged.sort_values("ts", kind="stable")
    merged["acc"] = np.sqrt(merged[["ax", "ay", "az"]].pow(2).sum(axis=1))
    merged["gyro"] = np.sqrt(merged[["rx", "ry", "rz"]].pow(2).sum(axis=1))

    def block(task_id: str, offset_s: float, length_s: float = 12.0) -> pd.DataFrame:
        b = markers[markers.task_id == task_id].iloc[0]
        t0 = b.start_ms + offset_s * 1000
        seg = merged[(merged.ts >= t0) & (merged.ts < t0 + length_s * 1000)].copy()
        seg["t"] = (seg.ts - t0) / 1000
        return seg

    panels = [
        ("abschreiben", 40, "Schreiben (Abschreiben)"),
        ("pause", 10, "Pause"),
        ("keyboard_typing", 40, "Tastatur tippen"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 3.4), sharex=True, sharey="row")
    for col, (task, off, title) in enumerate(panels):
        seg = block(task, off)
        axes[0, col].plot(seg.t, seg.acc, color=BLUE, lw=0.6)
        axes[1, col].plot(seg.t, seg.gyro, color=ORANGE, lw=0.6)
        axes[0, col].set_title(title)
        if "label_writing" in seg:
            on = seg.label_writing.values.astype(bool)
            axes[0, col].fill_between(seg.t, 0, 1, where=on, transform=axes[0, col].get_xaxis_transform(),
                                      color=GREEN, alpha=0.18, lw=0)
        axes[1, col].set_xlabel("Zeit [s]")
    axes[0, 0].set_ylabel(r"$\|a\|$ [g]")
    axes[1, 0].set_ylabel(r"$\|\omega\|$ [rad/s]")
    axes[0, 0].set_ylim(0, None)
    axes[1, 0].set_ylim(0, None)
    fig.tight_layout(h_pad=0.6, w_pad=0.8)
    _save(fig, "signal_example")


def fig_alignment(session: str = "S039") -> None:
    watch, strokes = _load_alignment(session)
    var_sig = _variance_signal(watch)
    (coarse_d, _), coarse = pen_match(watch, strokes, -20.0, 20.0, 0.5)
    (fine_d, fine_min), fine = pen_match(watch, strokes, coarse_d - 5.0, coarse_d + 5.0, 0.01)
    sigma = float((fine_min - fine.mean()) / fine.std())
    print(f"{session}: delta={fine_d:.3f}s sigma={sigma:.2f}")

    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.3))
    t0 = watch["timestamp"].iloc[0]
    t_rel = (watch["timestamp"] - t0).dt.total_seconds()
    # Why: pick a 30-s excerpt inside a dense writing stretch so the mask is visible.
    stroke_mid = strokes.groupby("StrokeID")["timestamp"].min().sort_values()
    lo = float((stroke_mid.iloc[len(stroke_mid) // 3] - t0).total_seconds())
    hi = lo + 30
    m = (t_rel >= lo) & (t_rel < hi)
    ax = axes[0]
    ax.plot(t_rel[m], var_sig[m].values, color=GREY, lw=0.6)
    shift = pd.Timedelta(seconds=fine_d)
    for _, row in strokes.groupby("StrokeID")["timestamp"].agg(["min", "max"]).iterrows():
        a = (row["min"] + shift - t0).total_seconds()
        b = (row["max"] + shift - t0).total_seconds()
        if b < lo or a > hi:
            continue
        ax.axvspan(max(a, lo), min(b, hi), color=GREEN, alpha=0.25, lw=0)
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, float(np.nanpercentile(var_sig[m], 99)) * 1.1)
    ax.set_xlabel("Watch-Zeit [s]")
    ax.set_ylabel("Varianz $v(t)$ (norm.)")
    ax.set_title(r"Strichmaske bei $\delta^*$")

    ax = axes[1]
    ax.plot(coarse.index, coarse.values, color=BLUE, lw=1)
    ax.axvline(coarse_d, color="k", ls="--", lw=0.8)
    ax.set_xlabel(r"$\delta$ [s]")
    ax.set_ylabel(r"$J(\delta)$")
    ax.set_title("Grobsuche (0,5 s Schritt)")

    ax = axes[2]
    ax.plot(fine.index, fine.values, color=ORANGE, lw=1)
    ax.axvline(fine_d, color="k", ls="--", lw=0.8)
    ax.set_xlabel(r"$\delta$ [s]")
    ax.set_title(f"Feinsuche (10 ms), $\\sigma$ = {sigma:.2f}")
    ax.annotate(f"$\\delta^*$ = {fine_d:.2f} s", xy=(fine_d, fine_min), xytext=(10, 25),
                textcoords="offset points", fontsize=8,
                arrowprops=dict(arrowstyle="-", lw=0.6))
    fig.tight_layout(w_pad=1.0)
    _save(fig, "alignment_example")


# Why: the two authors are stored under their first names in sessions.csv;
# the report only ever shows pseudonyms, matching the partner data export.
# The name-to-pseudonym mapping stays out of git (the repo is public) and is
# read from a gitignored JSON file; without it the names are shown unchanged.
PSEUDONYMS_FILE = ROOT / "data" / "author_pseudonyms.json"


def _author_pseudonyms() -> dict[str, str]:
    if not PSEUDONYMS_FILE.exists():
        print(f"warning: {PSEUDONYMS_FILE.name} missing, author names not pseudonymised")
        return {}
    return json.loads(PSEUDONYMS_FILE.read_text())


def fig_per_person() -> None:
    d = pd.read_csv(DETAIL).sort_values("rf1s_acc").reset_index(drop=True)
    d["held_out"] = d.held_out.replace(_author_pseudonyms())
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    ax.bar(x, d.rf1s_acc, color=BLUE, width=0.7, label="RF, 1-s-Fenster")
    ax.scatter(x, d.hmm_filter_acc, color=ORANGE, s=16, zorder=3, label="RF + HMM-Filter (kausal)")
    ax.scatter(x, d.hmm_smooth_acc, color=GREEN, s=16, marker="^", zorder=3, label="RF + HMM-Smoother")
    ax.axhline(d.rf1s_acc.mean(), color=BLUE, lw=0.8, ls=":")
    ax.set_xticks(x)
    ax.set_xticklabels(d.held_out, rotation=90, fontsize=7)
    ax.set_ylim(0.7, 1.0)
    ax.set_ylabel("Accuracy (ausgelassene Person)")
    ax.legend(loc="upper left", ncol=3, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    _save(fig, "per_person_n32")


def fig_decoders() -> None:
    d = pd.read_csv(DETAIL)
    rows = [
        ("RF 1 s", "rf1s_acc", "1 s", BLUE),
        ("Burst 5 s", "burst5cal_acc", "5 s", GREY),
        ("Burst 10 s", "burst10cal_acc", "10 s", GREY),
        ("Burst 30 s", "burst30cal_acc", "30 s", GREY),
        ("HMM-Filter", "hmm_filter_acc", "~18 s", ORANGE),
        ("HMM-Smoother", "hmm_smooth_acc", "offline", GREEN),
        ("Viterbi", "hmm_viterbi_acc", "offline", GREEN),
    ]
    fig, ax = plt.subplots(figsize=(4.6, 2.6))
    x = np.arange(len(rows))
    means = [d[c].mean() for _, c, _, _ in rows]
    stds = [d[c].std() for _, c, _, _ in rows]
    ax.bar(x, means, yerr=stds, color=[c for *_, c in rows], width=0.65, capsize=2,
           error_kw=dict(lw=0.7))
    for i, (m, (_, _, lat, _)) in enumerate(zip(means, rows)):
        ax.text(i, 0.705, lat, ha="center", va="bottom", fontsize=7, color="white")
        ax.text(i, m + stds[i] + 0.004, f"{m:.3f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([r[0] for r in rows], rotation=30, ha="right")
    ax.set_ylim(0.7, 0.97)
    ax.set_ylabel("Accuracy (Mittel ± SD)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    _save(fig, "decoders_n32")


def fig_task_errors() -> None:
    oof = pd.read_csv(OOF)
    rows = []
    for sid, g in oof.groupby("session_id"):
        m = MARKERS / f"{sid}_markers.csv"
        if not m.exists():
            continue
        rows.append(assign_task(g, parse_task_blocks(pd.read_csv(m))))
    a = pd.concat(rows)
    a["pred"] = (a.proba_cal >= 0.5).astype(int)
    idle_tasks = ["keyboard_typing", "phone_typing", "pen_fidgeting", "phone_scrolling", "gesturing", "pause"]
    write_tasks = ["soft_writing", "math", "abschreiben", "free_writing", "think_pause_writing"]
    fpr = {t: (a[(a.label == 0) & (a.task_id == t)].pred == 1).mean() for t in idle_tasks}
    fnr = {t: (a[(a.label == 1) & (a.task_id == t)].pred == 0).mean() for t in write_tasks}

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.4), gridspec_kw=dict(width_ratios=[6, 5]))
    ax = axes[0]
    ax.barh([TASK_LABELS[t] for t in idle_tasks][::-1], [fpr[t] for t in idle_tasks][::-1], color=RED, height=0.6)
    ax.set_xlabel("Falsch-positiv-Rate")
    ax.set_title("Nicht-Schreib-Aufgaben")
    ax.set_xlim(0, 0.3)
    ax = axes[1]
    ax.barh([TASK_LABELS[t] for t in write_tasks][::-1], [fnr[t] for t in write_tasks][::-1], color=BLUE, height=0.6)
    ax.set_xlabel("Falsch-negativ-Rate")
    ax.set_title("Schreib-Aufgaben")
    ax.set_xlim(0, 0.3)
    for ax in axes:
        ax.grid(axis="x", alpha=0.3)
    fig.tight_layout(w_pad=2.0)
    _save(fig, "task_errors_n32")
    print("FPR", {k: round(v, 3) for k, v in fpr.items()})
    print("FNR", {k: round(v, 3) for k, v in fnr.items()})


def fig_cohort_scaling() -> None:
    n = [20, 22, 32]
    rf = [0.869, 0.863, 0.865]
    tcn6 = [None, 0.9086, 0.9154]
    bigru = [None, 0.9114, 0.9209]
    fig, ax = plt.subplots(figsize=(3.6, 2.5))
    ax.plot(n, rf, "o-", color=BLUE, label="Random Forest (1 s)")
    ax.plot(n[1:], tcn6[1:], "s-", color=GREY, label="tcn6 (5 s)")
    ax.plot(n[1:], bigru[1:], "^-", color=ORANGE, label="tcn_bigru (5 s)")
    ax.set_xlabel("Personen im Datensatz")
    ax.set_ylabel("Accuracy")
    ax.set_xticks(n)
    ax.set_ylim(0.84, 0.94)
    ax.legend(frameon=False, loc="center right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    _save(fig, "cohort_scaling")


if __name__ == "__main__":
    fig_signal_example()
    fig_alignment()
    fig_per_person()
    fig_decoders()
    fig_task_errors()
    fig_cohort_scaling()
