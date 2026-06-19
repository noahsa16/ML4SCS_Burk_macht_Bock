"""Sweep über die *Feature*-Window-Größe (nicht Burst-Decision-Window).

Frage: bringt ein längeres **Feature**-Fenster (z. B. 5 s statt 1 s, mit
längerem Stride) mehr als die bestehende Burst-Aggregation der 1-s-Window-
Predictions? Beides nutzt längeren Kontext, aber auf verschiedenen Wegen:

* **Burst** (heute): 1-s-Features → Prediction → kausales Rolling-Mean der
  *Wahrscheinlichkeiten* auf 5/10/30 s. Mittelt verrauschte Kurz-Kontext-
  Vorhersagen.
* **Längeres Feature-Window** (dieser Sweep): die 88 Features werden über
  5 s Roh-IMU gerechnet — feinere FFT-Auflösung (Δf = 1/T → 0.2 Hz statt
  1 Hz), stabilere Statistik über 250 statt 50 Samples. Mittelt das *Signal*
  vor der Vorhersage.

Reproduziert den N=14-Legacy-Pool exakt (gleiche 14 Folds wie die Headline):
pro Session wird ``*_merged_legacy.csv`` bevorzugt (Downsample-View der
Modern-Sessions), sonst ``*_merged.csv`` (native 50-Hz-Probanden). Die neuen
Windows landen in einem **separaten** Ordner ``data/processed/windows_sweep/``
— die kanonischen ``windows/50hz/``-Caches bleiben unangetastet.

``--pool modern`` fährt denselben Test auf den Gravity-Sessions (P12–P15,
92 Features, native 100 Hz) → Gravity-Robustheit. ``--models`` fährt ein
kuratiertes Modell-Panel (RF/ExtraTrees/HistGradBoost/LogReg) durch den
**kausalen** Eval-Pfad → Modell-Robustheit. Wichtig: NICHT
``compare_models._eval_fold`` benutzen — das glättet mit ``center=True``
(nicht-kausal, ~5–6 pp inflationiert). Hier wird ausschließlich der kausale
``train_loso._burst_metrics`` verwendet.

Ehrlicher Vergleich auf **fixer Decision-Latenz**: ein 5-s-natives Fenster
ist eine 5-s-Entscheidung — direkt vergleichbar mit 1-s-Features + Burst@5s.
Der gepaarte Wilcoxon-Test (``src/evaluation/significance.py``) ist das Gate:
bei Fold-σ ≈ 3.4 pp ist alles ohne p < 0.05 Rauschen.

Usage::

    python scripts/ml/sweep_window_size.py                       # Legacy, RF, volles Gitter
    python scripts/ml/sweep_window_size.py --models --config 1,0.5 --config 5,2.5
    python scripts/ml/sweep_window_size.py --pool modern --config 1,0.5 --config 5,2.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.significance import paired_fold_test  # noqa: E402
from src.features.gravity import GRAVITY_FEATURE_NAMES  # noqa: E402
from src.features.windows import build_windows  # noqa: E402
from src.training.train_loso import (  # noqa: E402
    _burst_metrics,
    _select_sessions,
    _zscore_per_session,
)

DATA_PROC = ROOT / "data" / "processed"
SWEEP_DIR = DATA_PROC / "windows_sweep"
MODEL_DIR = ROOT / "models"

# Default-Gitter: Baseline (= Headline-Legacy) + längere Fenster bei
# gehaltenem 50 % Overlap, plus eine dichte-Stride-Variante zum Vergleich.
_DEFAULT_GRID: tuple[tuple[float, float], ...] = (
    (1.0, 0.5),  # Baseline — reproduziert die N=14-Headline
    (3.0, 1.5),  # 50 % Overlap, FFT 3× feiner, bessere Label-Reinheit
    (5.0, 2.5),  # 50 % Overlap, native 5-s-Decision — Primärkandidat
    (5.0, 1.0),  # 80 % Overlap — testet mehr (redundante) Fenster
)

_META_COLS = {"label", "t_center_ms", "session_id", "person_id",
              "task_id", "task_category"}

_POOL_PROFILE = {"legacy": "50hz", "modern": "100hz_grav"}


def _label(window_sec: float, stride_sec: float) -> str:
    return f"w{window_sec:g}s{stride_sec:g}"


def _model_panel(with_panel: bool, select: list[str] | None = None) -> dict[str, object]:
    """RF-only (Default), kuratiertes Panel, oder gezielte Auswahl via select.

    Panel = Tree-Ensembles (RF, ExtraTrees), Boosting (HistGradBoost) und
    linear (LogReg). Hält der Window-Gewinn über alle, ist es ein
    Feature-Qualitäts-Effekt, kein RF-Artefakt. ``select`` zieht beliebige
    Namen aus dem vollen ``compare_models._models()``-Set (z. B. 'SVM-RBF' —
    bewusst nicht im Default-Panel, weil SVC mit probability=True auf den
    ~24k 1-s-Fenstern langsam ist).
    """
    from scripts.ml.compare_models import _models

    full = _models()
    if select:
        missing = [m for m in select if m not in full]
        if missing:
            raise SystemExit(
                f"Unbekannte Modelle {missing}; verfügbar: {list(full)}"
            )
        return {m: full[m] for m in select}
    if not with_panel:
        return {"RandomForest": full["RandomForest"]}
    return {k: full[k] for k in
            ("RandomForest", "ExtraTrees", "HistGradBoost", "LogReg")}


def _merged_source(sid: str, pool: str) -> Path:
    """Quell-merged-CSV je nach Pool.

    legacy: Legacy-View bevorzugen (Downsample der Modern-Sessions), sonst
    native — reproduziert exakt ``windows/50hz/``. modern: immer native
    ``*_merged.csv`` (100 Hz, mit Gravity).
    """
    if pool == "legacy":
        legacy = DATA_PROC / f"{sid}_merged_legacy.csv"
        if legacy.exists():
            return legacy
    return DATA_PROC / f"{sid}_merged.csv"


def _build_pool(
    sessions: pd.DataFrame,
    window_sec: float,
    stride_sec: float,
    max_gap_ms: float,
    pool: str,
    write: bool,
) -> pd.DataFrame:
    """Baue Windows für alle Pool-Sessions bei (window_sec, stride_sec)."""
    frames: list[pd.DataFrame] = []
    tag = _label(window_sec, stride_sec)
    out_dir = SWEEP_DIR / (tag if pool == "legacy" else f"{tag}_{pool}")
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
    for sid in sessions["session_id"]:
        merged = pd.read_csv(_merged_source(sid, pool))
        w = build_windows(
            merged,
            window_sec=window_sec,
            stride_sec=stride_sec,
            max_gap_ms=max_gap_ms,
        )
        if pool == "legacy":
            # Why: Legacy-Pool ist 88 Features — falls eine Quelle doch
            # Gravity trägt, hart auf den Legacy-Satz zwingen. Modern behält
            # Gravity (92 Features), das ist der Punkt des Gravity-Checks.
            w = w.drop(columns=[c for c in GRAVITY_FEATURE_NAMES if c in w.columns])
        w["session_id"] = sid
        if write:
            w.to_csv(out_dir / f"{sid}_windows.csv", index=False)
        frames.append(w)
    all_w = pd.concat(frames, ignore_index=True).merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )
    return all_w


def _eval_fold(
    builder: object,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    fcols: list[str],
) -> dict | None:
    """Ein Modell auf einem Fold; per-window + **kausale** Burst-Metriken.

    Modell-agnostisch (proba via predict_proba / decision_function / predict).
    Burst über ``train_loso._burst_metrics`` (kausal/trailing) — NICHT der
    center=True-Pfad aus compare_models.
    """
    y_test = test_df["label"].to_numpy()
    if len(np.unique(y_test)) < 2:
        return None
    try:
        model = clone(builder)
    except TypeError:
        model = builder
    model.fit(train_df[fcols].to_numpy(), train_df["label"].to_numpy())
    X_test = test_df[fcols].to_numpy()
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X_test)[:, 1]
    elif hasattr(model, "decision_function"):
        z = model.decision_function(X_test)
        proba = 1.0 / (1.0 + np.exp(-z))
    else:
        proba = model.predict(X_test).astype(float)
    pred = (proba >= 0.5).astype(int)
    try:
        auc = float(roc_auc_score(y_test, proba))
    except ValueError:
        auc = float("nan")
    bursts = _burst_metrics(proba, y_test, test_df)
    return {
        "accuracy": float((pred == y_test).mean()),
        "f1_writing": float(f1_score(y_test, pred, pos_label=1, zero_division=0)),
        "roc_auc": auc,
        "bursts": bursts,
    }


def run_config(
    window_sec: float,
    stride_sec: float,
    sessions: pd.DataFrame,
    max_gap_ms: float,
    pool: str,
    models: dict[str, object],
    write: bool,
) -> pd.DataFrame:
    """LOSO-by-person bei einer Feature-Window-Größe → per-(model,fold) Tabelle."""
    label = _label(window_sec, stride_sec)
    all_w = _build_pool(sessions, window_sec, stride_sec, max_gap_ms, pool, write)
    fcols = [
        c for c in all_w.select_dtypes("number").columns if c not in _META_COLS
    ]
    all_w = _zscore_per_session(all_w, fcols)

    persons = sorted(all_w["person_id"].dropna().unique())
    overlap = (window_sec - stride_sec) / window_sec
    print(
        f"\n=== {label}  (window={window_sec:g}s stride={stride_sec:g}s "
        f"overlap={overlap:.0%}, pool={pool}) — {len(fcols)} features, "
        f"{len(all_w)} windows, {len(persons)} folds ==="
    )

    rows: list[dict] = []
    for mname, builder in models.items():
        for held in persons:
            tr = all_w[all_w["person_id"] != held]
            te = all_w[all_w["person_id"] == held]
            m = _eval_fold(builder, tr, te, fcols)
            if m is None:
                continue
            b = m["bursts"]
            row = {
                "config": label, "model": mname, "held_out": held,
                "n_test": len(te), "accuracy": m["accuracy"],
                "f1_writing": m["f1_writing"], "roc_auc": m["roc_auc"],
            }
            for scale, bm in b.items():
                row[f"acc_{scale}"] = bm["accuracy"]
                row[f"f1_{scale}"] = bm["f1_writing"]
                row[f"auc_{scale}"] = bm["roc_auc"]
            rows.append(row)
        sub = pd.DataFrame([r for r in rows if r["model"] == mname])
        print(
            f"  {mname:>14}: win acc={sub.accuracy.mean():.3f} "
            f"auc={sub.roc_auc.mean():.3f} | 5s acc={sub.acc_5s.mean():.3f} "
            f"auc={sub.auc_5s.mean():.3f} | 10s acc={sub.acc_10s.mean():.3f} "
            f"| 30s acc={sub.acc_30s.mean():.3f}"
        )
    return pd.DataFrame(rows)


def _mean_std(s: pd.Series) -> str:
    return f"{s.mean():.3f}±{s.std():.3f}"


def summarize(all_rows: pd.DataFrame) -> None:
    print("\n=== Summary (mean ± std über Folds) ===")
    print(
        f"{'model':>14} {'config':>8} {'win-acc':>13} {'win-auc':>13} "
        f"{'5s-acc':>13} {'5s-auc':>13} {'10s-acc':>13} {'30s-acc':>13}"
    )
    for (mname, cfg), g in all_rows.groupby(["model", "config"], sort=False):
        print(
            f"{mname:>14} {cfg:>8} {_mean_std(g.accuracy):>13} "
            f"{_mean_std(g.roc_auc):>13} {_mean_std(g.acc_5s):>13} "
            f"{_mean_std(g.auc_5s):>13} {_mean_std(g.acc_10s):>13} "
            f"{_mean_std(g.acc_30s):>13}"
        )


def significance(all_rows: pd.DataFrame, baseline: str) -> None:
    """Gepaarter Wilcoxon je Modell: langes natives Window vs. Baseline+Burst.

    Pro Modell, fixe Decision-Latenz: natives Window (Spalte ``accuracy``)
    gegen die Baseline-1s-Features + Burst@<nächste Skala> (Spalte
    ``acc_<scale>s`` der Baseline desselben Modells), gepaart auf Folds.
    """
    print(f"\n=== Gepaarter Wilcoxon vs. Baseline {baseline!r} (pro Modell) ===")
    print("  <config> natives Window  vs  Baseline 1s-Features + Burst@<scale>")
    for mname, mrows in all_rows.groupby("model", sort=False):
        base = mrows[mrows["config"] == baseline]
        if base.empty:
            continue
        base = base.set_index("held_out")
        print(f"  — {mname} —")
        for cfg, g in mrows.groupby("config", sort=False):
            if cfg == baseline:
                continue
            win_sec = float(cfg.split("s")[0].lstrip("w"))
            scale = min((5, 10, 30), key=lambda s: abs(s - win_sec))
            g = g.set_index("held_out")
            idx = base.index.intersection(g.index)
            res = paired_fold_test(
                g.loc[idx, "accuracy"].to_numpy(),
                base.loc[idx, f"acc_{scale}s"].to_numpy(),
            )
            verdict = "SIGNIFIKANT" if res["significant"] else "n.s."
            print(
                f"    {cfg:>8} (native {win_sec:g}s) vs burst@{scale}s : "
                f"median Δ = {res['median_diff']:+.4f}  "
                f"p = {res['p_value']:.4f}  → {verdict}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config", action="append", default=None,
        help="'window_sec,stride_sec', mehrfach möglich. Default: "
        "1,0.5 / 3,1.5 / 5,2.5 / 5,1.0",
    )
    ap.add_argument("--pool", choices=["legacy", "modern"], default="legacy")
    ap.add_argument(
        "--models", action="store_true",
        help="Kuratiertes Modell-Panel statt nur RF (Modell-Robustheit).",
    )
    ap.add_argument(
        "--model", action="append", default=None,
        help="Gezielte Modell-Auswahl aus compare_models._models() "
        "(mehrfach), z. B. --model SVM-RBF. Überschreibt --models.",
    )
    ap.add_argument("--max-gap-ms", type=float, default=2500.0)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--baseline", default="w1s0.5")
    args = ap.parse_args()

    if args.config:
        grid = tuple((float(w), float(s))
                     for w, s in (c.split(",") for c in args.config))
    else:
        grid = _DEFAULT_GRID

    sessions = _select_sessions(
        include_all=False, min_windows=0, profile=_POOL_PROFILE[args.pool]
    )
    persons = sorted(sessions["person_id"].dropna().unique())
    print(
        f"Pool={args.pool}: {len(sessions)} Sessions, {len(persons)} Personen "
        f"— {persons}"
    )
    models = _model_panel(args.models, select=args.model)
    print(f"Modelle: {list(models)}")

    all_rows: list[pd.DataFrame] = []
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for window_sec, stride_sec in grid:
        all_rows.append(
            run_config(window_sec, stride_sec, sessions, args.max_gap_ms,
                       args.pool, models, not args.no_write)
        )
    combined = pd.concat(all_rows, ignore_index=True)
    suffix = "" if args.pool == "legacy" else f"_{args.pool}"
    if args.model:
        # Why: gezielte Auswahl bekommt einen eigenen Datei-Tag, damit der
        # kanonische RF-Sweep (window_sweep_cv.csv) nicht überschrieben wird.
        tag = "-".join(m.lower().replace("(", "").replace(")", "").replace(",", "")
                       for m in args.model)
        suffix += f"_{tag}"
    elif args.models:
        suffix += "_panel"
    out_csv = MODEL_DIR / f"window_sweep{suffix}_cv.csv"
    combined.to_csv(out_csv, index=False)

    summarize(combined)
    significance(combined, args.baseline)
    print(f"\n→ {out_csv}")


if __name__ == "__main__":
    main()
