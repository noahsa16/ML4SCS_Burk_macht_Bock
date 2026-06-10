"""Leave-One-Out cross-validation für die Schreib-Erkennung.

**Headline-Metrik für das Projekt-Ziel.** Pendant zu
:mod:`src.training.within_session.train_rf` — statt eines within-session
80/20-Splits hält dieses Skript pro Fold eine *ganze Einheit* zurück
(Person oder Session) und trainiert auf allen übrigen.

Default ist **LOSO-by-person** (Leave-One-Subject-Out): die ehrliche
Generalisierungs-Metrik für das Projekt-Ziel ("general writing detector,
unabhängig von wer die Watch trägt"). Mit ``--by session`` fällt das
Skript auf Leave-One-Session-Out zurück — sinnvoll solange nur ein
Subjekt aufgenommen wurde, da Person-LOSO mit n=1 degeneriert.

Session-Auswahl: nur Sessions mit ``verdict ∈ {trainable, usable}`` aus
``data/sessions.csv`` (siehe CLAUDE.md, σ-Threshold-Gate). Override mit
``--include-all``. Zusätzlich kann ``--min-windows`` Sessions mit zu
wenigen Fenstern ausschließen.

Optional kann nach der CV ein **finales Deployment-Modell** auf allen
Daten trainiert und gedumpt werden (``--save-final-model``), und die
per-fold Metriken als CSV gesichert werden (``--save-cv-csv``).

Random Forest

CLI
---
::

    python -m src.training.train_loso                          # by person
    python -m src.training.train_loso --by session             # LOSO-session10
    python -m src.training.train_loso --include-all            # ohne verdict-gate
    python -m src.training.train_loso --min-windows 200        # zusätzlicher size-filter
    python -m src.training.train_loso --save-final-model       # → models/rf_all.joblib
    python -m src.training.train_loso --save-cv-csv            # → models/loso_cv.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)

from src.features.gravity import GRAVITY_FEATURE_NAMES
from src.features.windows import load_session_windows

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"

TRAINABLE_VERDICTS = {"trainable", "usable"}

# Decision-Window-Skalen für Burst-Aggregation (Sekunden). Die 1-s-Per-Window
# Metriken sind sub-optimal für User-facing Use-Cases — Tagestracker / Phasen-
# erkennung arbeiten implizit auf längeren Skalen. Wir reporten 5/10/30 s
# zusätzlich, um den Modell-Rauschen-Anteil sichtbar zu machen.
BURST_SCALES_SEC: tuple[float, ...] = (5.0, 10.0, 30.0)


def _filter_pool(
    all_windows: pd.DataFrame, pool: str, drop_gravity: bool = False
) -> pd.DataFrame:
    """Filter sessions and gravity columns based on pool selection.

    pool ∈ {"auto", "legacy", "modern"}:
    - "auto": include all sessions. If any session is legacy (NaN gravity
      after concat), drop gravity columns globally so RF doesn't see NaN.
      All-modern: keep gravity.
    - "legacy": include only sessions that are inherently legacy
      (no gravity capture). Gravity columns dropped from output.
    - "modern": include only sessions with valid (non-NaN, all-rows)
      gravity. Gravity columns kept.

    drop_gravity=True removes the gravity columns from the output while
    keeping the session selection unchanged — the paired ablation arm
    (same sessions/folds, minus gravity features).

    Why this matters: pd.concat over mixed pools pads missing columns
    with NaN. RF.fit crashes on NaN. _zscore_per_session would also
    propagate NaN as division warnings.
    """
    if pool not in {"auto", "legacy", "modern"}:
        raise ValueError(
            f"pool must be 'auto'|'legacy'|'modern', got {pool!r}"
        )

    grav_present = [c for c in GRAVITY_FEATURE_NAMES if c in all_windows.columns]
    if not grav_present:
        # No gravity columns at all: everything is legacy by definition.
        if pool == "modern":
            raise RuntimeError(
                "pool='modern' requested but no sessions have gravity features"
            )
        return all_windows

    # Per-session: modern iff all gravity values for that session are non-NaN.
    sentinel = grav_present[0]
    session_is_modern = (
        all_windows.groupby("session_id")[sentinel].apply(lambda s: s.notna().all())
    )
    modern_sids = session_is_modern[session_is_modern].index
    legacy_sids = session_is_modern[~session_is_modern].index

    if pool == "modern":
        if len(modern_sids) == 0:
            raise RuntimeError("pool='modern' requested but no modern sessions found")
        out = all_windows[all_windows["session_id"].isin(modern_sids)].copy()
        return out.drop(columns=grav_present) if drop_gravity else out

    if pool == "legacy":
        if len(legacy_sids) == 0:
            raise RuntimeError("pool='legacy' requested but no legacy sessions found")
        out = all_windows[all_windows["session_id"].isin(legacy_sids)].copy()
        return out.drop(columns=grav_present)

    # auto: keep all sessions; drop gravity columns iff any legacy session present.
    if len(legacy_sids) > 0 or drop_gravity:
        return all_windows.drop(columns=grav_present)
    return all_windows


def _load_windows(session_id: str) -> pd.DataFrame:
    cached = DATA_PROC / f"{session_id}_windows.csv"
    if cached.exists():
        df = pd.read_csv(cached)
    else:
        df = load_session_windows(session_id)
    df = df.copy()
    df["session_id"] = session_id
    return df


def _select_sessions(include_all: bool, min_windows: int) -> pd.DataFrame:
    """Read sessions.csv and apply verdict + min-windows quality gates."""
    sessions = pd.read_csv(SESSIONS_CSV)
    if not include_all:
        if "verdict" in sessions.columns:
            sessions = sessions[sessions["verdict"].isin(TRAINABLE_VERDICTS)]
        # Why: study_mode='test' = pilot/dry-run, laut CLAUDE.md aus default-
        # LOSO ausgeschlossen. verdict allein filtert das nicht.
        if "study_mode" in sessions.columns:
            sessions = sessions[sessions["study_mode"].fillna("") != "test"]
    # Why: ohne windows-CSV kein training — skip statt fail.
    sessions = sessions[
        sessions["session_id"].apply(
            lambda s: (DATA_PROC / f"{s}_windows.csv").exists()
        )
    ]
    if min_windows > 0:
        kept = []
        for sid in sessions["session_id"]:
            n = sum(1 for _ in open(DATA_PROC / f"{sid}_windows.csv")) - 1
            if n >= min_windows:
                kept.append(sid)
            else:
                print(f"  skip {sid}  (n_windows={n} < {min_windows})")
        sessions = sessions[sessions["session_id"].isin(kept)]
    return sessions.reset_index(drop=True)


def _burst_metrics(
    proba: np.ndarray,
    y_true: np.ndarray,
    test_df: pd.DataFrame,
    scales_sec: tuple[float, ...] = BURST_SCALES_SEC,
) -> dict[str, dict[str, float]]:
    """Per-Session Rolling-Mean-Smoothing der Wahrscheinlichkeiten, ausgewertet pro Skala.

    Per Session, nicht über Session-Grenzen hinweg: ``t_center_ms`` ist nur
    innerhalb einer Session monoton; ein Rolling-Window über mehrere Sessions
    würde Predictions vermischen, die Stunden oder Tage auseinanderliegen.

    Stride-Annahme wird per Session aus dem Median-Δ(t_center_ms) abgeleitet,
    fällt auf 500 ms zurück (Default in ``build_windows``).
    """
    df = test_df.reset_index(drop=True).copy()
    df["_proba"] = proba
    df["_y"] = y_true
    df = df.sort_values(["session_id", "t_center_ms"]).reset_index(drop=True)

    out: dict[str, dict[str, float]] = {}
    for scale in scales_sec:
        smoothed_chunks: list[np.ndarray] = []
        for _, g in df.groupby("session_id", sort=False):
            t = g["t_center_ms"].to_numpy()
            if len(t) >= 2:
                stride_ms = float(np.median(np.diff(t))) or 500.0
            else:
                stride_ms = 500.0
            n = max(1, int(round(scale * 1000.0 / stride_ms)))
            s = g["_proba"].rolling(n, center=True, min_periods=1).mean().to_numpy()
            smoothed_chunks.append(s)
        smoothed = np.concatenate(smoothed_chunks)
        y_sorted = df["_y"].to_numpy()
        pred = (smoothed >= 0.5).astype(int)
        try:
            auc_b = float(roc_auc_score(y_sorted, smoothed))
        except ValueError:
            auc_b = float("nan")
        out[f"{int(scale)}s"] = {
            "accuracy": float((pred == y_sorted).mean()),
            "f1_writing": float(f1_score(y_sorted, pred, pos_label=1, zero_division=0)),
            "roc_auc": auc_b,
        }
    return out


def _zscore_per_session(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    # Why: subject-dependent baselines (wrist size, handedness, tremor) shift the
    # absolute feature distribution; per-session standardization brings every
    # subject onto a common relative scale so the RF learns "above this person's
    # typical level" rather than "above the training-pool's absolute level".
    # σ=0 in a session (constant column) → replaced with 1.0 to keep finite values.
    out = df.copy()
    grouped = out.groupby("session_id", sort=False)[feature_cols]
    mu = grouped.transform("mean")
    sigma = grouped.transform("std").replace(0.0, 1.0).fillna(1.0)
    out[feature_cols] = (out[feature_cols] - mu) / sigma
    return out


def _fit_eval_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    n_estimators: int,
    random_state: int,
) -> dict | None:
    """Train on train_df, evaluate on test_df. Returns None if test is single-class."""
    y_test = test_df["label"].to_numpy()
    if len(np.unique(y_test)) < 2:
        return None

    X_train = train_df[feature_cols].to_numpy()
    y_train = train_df["label"].to_numpy()
    X_test = test_df[feature_cols].to_numpy()

    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=random_state,
        class_weight="balanced",
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    # Isotonische Kalibrierung für die Schreib-Prozent-Regression (Stufe 1).
    # Why: cv=3 splittet die Trainings-Folds NICHT personen-gruppiert —
    # bei N=10 und monotoner Kalibrierung vertretbar (bekannte Vereinfachung,
    # siehe docs/specs/2026-05-21-regression-schreibprozent-design.md).
    # Eigene Estimator-Instanz, damit der Headline-clf unangetastet bleibt.
    cal = CalibratedClassifierCV(
        RandomForestClassifier(
            n_estimators=n_estimators,
            random_state=random_state,
            class_weight="balanced",
            n_jobs=-1,
        ),
        method="isotonic",
        cv=3,
    )
    cal.fit(X_train, y_train)
    y_proba_cal = cal.predict_proba(X_test)[:, 1]

    oof = pd.DataFrame({
        "session_id": test_df["session_id"].to_numpy(),
        "person_id": test_df["person_id"].to_numpy(),
        "t_center_ms": test_df["t_center_ms"].to_numpy(),
        "label": y_test,
        "proba_raw": y_proba,
        "proba_cal": y_proba_cal,
    })

    try:
        auc = roc_auc_score(y_test, y_proba)
    except ValueError:
        auc = float("nan")

    bursts = _burst_metrics(y_proba, y_test, test_df)

    return {
        "n_train": len(train_df),
        "n_test": len(test_df),
        "train_label_balance": np.bincount(y_train, minlength=2).tolist(),
        "test_label_balance": np.bincount(y_test, minlength=2).tolist(),
        "test_pct_writing": float(y_test.mean()),
        "accuracy": float((y_pred == y_test).mean()),
        "f1_writing": float(f1_score(y_test, y_pred, pos_label=1, zero_division=0)),
        "roc_auc": auc,
        "confusion_matrix": confusion_matrix(y_test, y_pred, labels=[0, 1]),
        "report": classification_report(y_test, y_pred, digits=3, zero_division=0),
        "bursts": bursts,
        "oof": oof,
    }


def _train_final_model(
    all_windows: pd.DataFrame,
    feature_cols: list[str],
    sessions: pd.DataFrame,
    n_estimators: int,
    random_state: int,
    save_to: Path,
) -> None:
    """Re-train on every available window and dump the deployment model."""
    print("\nTraining final model on all sessions…")
    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=random_state,
        class_weight="balanced",
        n_jobs=-1,
    )
    clf.fit(all_windows[feature_cols].to_numpy(), all_windows["label"].to_numpy())
    save_to.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": clf,
            "feature_cols": feature_cols,
            "trained_on": sorted(sessions["session_id"].tolist()),
            "n_windows": len(all_windows),
        },
        save_to,
    )
    print(f"→ {save_to}")


def train_loso(
    by: str = "person",
    include_all: bool = False,
    min_windows: int = 0,
    n_estimators: int = 200,
    random_state: int = 42,
    save_final_model: Path | None = None,
    save_cv_csv: Path | None = None,
    save_oof: Path | None = None,
    zscore_per_session: bool = True,
    pool: str = "auto",
    drop_gravity: bool = False,
) -> dict:
    if by not in {"person", "session"}:
        raise ValueError(f"--by must be 'person' or 'session', got {by!r}")

    sessions = _select_sessions(include_all=include_all, min_windows=min_windows)
    if sessions.empty:
        raise RuntimeError(
            "No eligible sessions found. Try --include-all to bypass the verdict gate."
        )

    group_col = "person_id" if by == "person" else "session_id"
    if group_col not in sessions.columns:
        raise RuntimeError(f"sessions.csv has no column {group_col!r}")

    groups = sessions[group_col].dropna().unique().tolist()
    if len(groups) < 2:
        print(
            f"[warn] Only {len(groups)} unique {by}(s) found ({groups}). "
            f"LOSO needs ≥ 2 to hold one out. "
            + ("Try --by session." if by == "person" else "Add more sessions.")
        )
        return {"folds": [], "summary": {}}

    print(
        f"LOSO-by-{by}: {len(groups)} folds over "
        f"{len(sessions)} session(s) — groups: {groups}"
    )

    all_windows = pd.concat(
        [_load_windows(s) for s in sessions["session_id"].tolist()],
        ignore_index=True,
    )
    all_windows = all_windows.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )

    pre_filter_cols = set(all_windows.columns)
    pre_filter_n = len(all_windows)
    pre_filter_sessions = all_windows["session_id"].nunique()
    all_windows = _filter_pool(all_windows, pool, drop_gravity=drop_gravity)
    grav_kept = any(c in all_windows.columns for c in GRAVITY_FEATURE_NAMES)
    kept_sessions = all_windows["session_id"].nunique()
    # Why: always print pool info so user can verify which features were
    # included — silent column-only drops are easy to miss otherwise.
    print(
        f"pool={pool}: {kept_sessions}/{pre_filter_sessions} sessions, "
        f"{len(all_windows)}/{pre_filter_n} windows, "
        f"gravity_features={'kept' if grav_kept else 'dropped'}"
    )

    feature_cols = [
        c
        for c in all_windows.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    if zscore_per_session:
        all_windows = _zscore_per_session(all_windows, feature_cols)

    print(
        f"Total: {len(all_windows)} windows; {len(feature_cols)} features"
        f"  | zscore_per_session={zscore_per_session}\n"
    )

    fold_results: list[dict] = []
    for held_out in groups:
        test_mask = all_windows[group_col] == held_out
        train_df = all_windows[~test_mask]
        test_df = all_windows[test_mask]

        held_out_sessions = sessions.loc[
            sessions[group_col] == held_out, "session_id"
        ].tolist()

        print(f"\n--- Fold: held-out {by}={held_out} (sessions={held_out_sessions}) ---")
        res = _fit_eval_fold(
            train_df, test_df, feature_cols, n_estimators, random_state
        )
        if res is None:
            print(f"  skipped — test fold has only one class")
            continue

        res["held_out"] = held_out
        res["held_out_sessions"] = held_out_sessions

        print(
            f"Windows: train={res['n_train']} test={res['n_test']}  "
            f"train-balance={res['train_label_balance']}  "
            f"test-balance={res['test_label_balance']}  "
            f"%writing={res['test_pct_writing']:.2f}"
        )
        print(res["report"])
        print("Confusion matrix [rows=true 0/1, cols=pred 0/1]:")
        print(res["confusion_matrix"])
        print(
            f"Accuracy: {res['accuracy']:.3f}   "
            f"F1(writing): {res['f1_writing']:.3f}   "
            f"ROC-AUC: {res['roc_auc']:.3f}"
        )
        burst_line = "  ".join(
            f"{scale} acc={m['accuracy']:.3f} f1={m['f1_writing']:.3f} auc={m['roc_auc']:.3f}"
            for scale, m in res["bursts"].items()
        )
        print(f"Burst-aggregated:  1s acc={res['accuracy']:.3f} f1={res['f1_writing']:.3f} auc={res['roc_auc']:.3f}  {burst_line}")
        fold_results.append(res)

    if not fold_results:
        print("\n[warn] All folds skipped (single-class tests). Nothing to summarise.")
        return {"folds": [], "summary": {}}

    aucs = np.array([r["roc_auc"] for r in fold_results], dtype=float)
    accs = np.array([r["accuracy"] for r in fold_results], dtype=float)
    f1s = np.array([r["f1_writing"] for r in fold_results], dtype=float)
    n_tests = np.array([r["n_test"] for r in fold_results], dtype=float)
    weighted_acc = float((accs * n_tests).sum() / n_tests.sum())

    summary = {
        "n_folds": len(fold_results),
        "mean_accuracy": float(np.nanmean(accs)),
        "std_accuracy": float(np.nanstd(accs)),
        "weighted_accuracy": weighted_acc,
        "mean_f1_writing": float(np.nanmean(f1s)),
        "mean_roc_auc": float(np.nanmean(aucs)),
        "std_roc_auc": float(np.nanstd(aucs)),
    }

    burst_summary: dict[str, dict[str, float]] = {}
    burst_scale_keys = list(fold_results[0]["bursts"].keys())
    for scale in burst_scale_keys:
        scale_accs = np.array([r["bursts"][scale]["accuracy"] for r in fold_results], dtype=float)
        scale_f1s = np.array([r["bursts"][scale]["f1_writing"] for r in fold_results], dtype=float)
        scale_aucs = np.array([r["bursts"][scale]["roc_auc"] for r in fold_results], dtype=float)
        burst_summary[scale] = {
            "mean_accuracy": float(np.nanmean(scale_accs)),
            "std_accuracy": float(np.nanstd(scale_accs)),
            "mean_f1_writing": float(np.nanmean(scale_f1s)),
            "mean_roc_auc": float(np.nanmean(scale_aucs)),
            "std_roc_auc": float(np.nanstd(scale_aucs)),
        }
    summary["bursts"] = burst_summary

    print("\n=== LOSO summary ===")
    print(
        f"Folds: {summary['n_folds']}\n"
        f"Accuracy: {summary['mean_accuracy']:.3f} ± {summary['std_accuracy']:.3f}   "
        f"(weighted by n_test: {summary['weighted_accuracy']:.3f})\n"
        f"F1(writing): {summary['mean_f1_writing']:.3f}\n"
        f"ROC-AUC:  {summary['mean_roc_auc']:.3f} ± {summary['std_roc_auc']:.3f}"
    )
    print("\n--- Burst-aggregated (Decision-Window) ---")
    print(f"{'scale':>6}  {'acc':>14}  {'f1':>8}  {'auc':>14}")
    print(f"{'1s':>6}  {summary['mean_accuracy']:.3f} ± {summary['std_accuracy']:.3f}  "
          f"{summary['mean_f1_writing']:>8.3f}  "
          f"{summary['mean_roc_auc']:.3f} ± {summary['std_roc_auc']:.3f}")
    for scale, m in burst_summary.items():
        print(f"{scale:>6}  {m['mean_accuracy']:.3f} ± {m['std_accuracy']:.3f}  "
              f"{m['mean_f1_writing']:>8.3f}  "
              f"{m['mean_roc_auc']:.3f} ± {m['std_roc_auc']:.3f}")

    def _fold_row(r: dict) -> dict:
        row = {
            "held_out": r["held_out"],
            "n_test": r["n_test"],
            "test_pct_writing": r["test_pct_writing"],
            "accuracy": r["accuracy"],
            "f1_writing": r["f1_writing"],
            "roc_auc": r["roc_auc"],
        }
        for scale, m in r["bursts"].items():
            row[f"acc_{scale}"] = m["accuracy"]
            row[f"f1_{scale}"] = m["f1_writing"]
            row[f"auc_{scale}"] = m["roc_auc"]
        return row

    per_fold_table = pd.DataFrame([_fold_row(r) for r in fold_results])
    print("\nPer-fold:")
    print(per_fold_table.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    if save_oof is not None:
        oof_all = pd.concat(
            [r["oof"] for r in fold_results], ignore_index=True
        )
        save_oof.parent.mkdir(parents=True, exist_ok=True)
        oof_all.to_csv(save_oof, index=False)
        print(f"\n→ {save_oof}  ({len(oof_all)} OOF-Zeilen)")

    if save_cv_csv is not None:
        save_cv_csv.parent.mkdir(parents=True, exist_ok=True)
        per_fold_table.to_csv(save_cv_csv, index=False)
        print(f"\n→ {save_cv_csv}")

    if save_final_model is not None:
        _train_final_model(
            all_windows,
            feature_cols,
            sessions,
            n_estimators,
            random_state,
            save_final_model,
        )

    return {"folds": fold_results, "summary": summary}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--by",
        choices=["person", "session"],
        default="person",
        help="Hold-out unit (default: person)",
    )
    p.add_argument(
        "--include-all",
        action="store_true",
        help="Skip the verdict ∈ {trainable, usable} quality gate.",
    )
    p.add_argument(
        "--min-windows",
        type=int,
        default=0,
        help="Additional filter: drop sessions with < N windows (default: off).",
    )
    p.add_argument(
        "--no-zscore",
        action="store_true",
        help="Disable per-session z-score normalization of features (default: on).",
    )
    p.add_argument(
        "--pool",
        choices=["auto", "legacy", "modern"],
        default="auto",
        help="Session pool selection: 'auto' (include all, drop gravity if "
        "mixed), 'legacy' (no-gravity sessions only, 88 features), "
        "'modern' (gravity-required sessions only, 94 features). "
        "Default: auto.",
    )
    p.add_argument(
        "--drop-gravity",
        action="store_true",
        help="Ablation arm: drop the gravity feature columns while keeping "
        "the session selection unchanged (paired 88-vs-92 comparison on "
        "identical folds). Save paths get a *_nogravity suffix.",
    )
    p.add_argument("--n-estimators", type=int, default=200)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument(
        "--save-final-model",
        nargs="?",
        const=str(MODEL_DIR / "rf_all.joblib"),
        default=None,
        help="After CV, re-train on all data and dump to PATH "
        "(default: models/rf_all.joblib).",
    )
    p.add_argument(
        "--save-cv-csv",
        nargs="?",
        const=str(MODEL_DIR / "loso_cv.csv"),
        default=None,
        help="Write per-fold metrics to PATH (default: models/loso_cv.csv).",
    )
    p.add_argument(
        "--save-oof",
        nargs="?",
        const=str(MODEL_DIR / "loso_oof.csv"),
        default=None,
        help="Write per-window out-of-fold predictions (raw + calibrated "
        "proba) to PATH (default: models/loso_oof.csv).",
    )
    return p.parse_args()


def _pool_suffixed_path(
    default_path: Path, pool: str, drop_gravity: bool = False
) -> Path:
    """Suffix the save path with the pool name to keep artefacts separate.

    Why: the headline Legacy artefacts (rf_all.joblib, loso_oof.csv,
    loso_cv.csv) are consumed by other pipelines (Live-Inference,
    Regression, Engagement) that assume the 10-Probanden Legacy pool.
    Saving a modern-only model under the same path silently corrupts
    those downstream tools. Pool != 'auto' → write to *_modern.* /
    *_legacy.* sibling instead. Same logic for --drop-gravity: the
    ablation arm must never overwrite the full-feature artefacts.
    """
    if pool == "auto" and not drop_gravity:
        return default_path
    parts = [default_path.stem]
    if pool != "auto":
        parts.append(pool)
    if drop_gravity:
        parts.append("nogravity")
    return default_path.with_name(f"{'_'.join(parts)}{default_path.suffix}")


if __name__ == "__main__":
    args = _parse_args()
    save_final = (
        _pool_suffixed_path(Path(args.save_final_model), args.pool, args.drop_gravity)
        if args.save_final_model else None
    )
    save_cv = (
        _pool_suffixed_path(Path(args.save_cv_csv), args.pool, args.drop_gravity)
        if args.save_cv_csv else None
    )
    save_oof = (
        _pool_suffixed_path(Path(args.save_oof), args.pool, args.drop_gravity)
        if args.save_oof else None
    )
    train_loso(
        by=args.by,
        include_all=args.include_all,
        min_windows=args.min_windows,
        n_estimators=args.n_estimators,
        random_state=args.random_state,
        save_final_model=save_final,
        save_cv_csv=save_cv,
        save_oof=save_oof,
        zscore_per_session=not args.no_zscore,
        pool=args.pool,
        drop_gravity=args.drop_gravity,
    )
