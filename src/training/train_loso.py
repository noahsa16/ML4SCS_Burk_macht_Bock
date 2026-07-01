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
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from src.features.gravity import GRAVITY_FEATURE_NAMES
from src.profiles import find_windows
from src.features.windows import load_session_windows
from src.features import param_cache as _param_cache
from src.training import events as _events

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


def _parse_burst_scales(spec: str) -> tuple[float, ...]:
    """Parse a comma-separated burst-scale spec into a sorted, deduped tuple.

    ``"5,10,30"`` → ``(5.0, 10.0, 30.0)``. Whitespace tolerant, non-positive
    values dropped, empty string → ``()`` (= report only the 1 s base window).
    The 1 s per-window metric is always reported separately and is not a burst
    scale, so it need not appear here.
    """
    vals = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        v = float(part)
        if v > 0:
            vals.append(v)
    return tuple(sorted(set(vals)))


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


# Why: Pool wählt das Profil — legacy lädt 50hz-Windows (native ODER
# Downsample-Views von Modern-Sessions, der N=14-Mechanismus), modern
# lädt 100hz_grav, auto die native Form (höchste Fidelity).
_POOL_PROFILE = {"legacy": "50hz", "modern": "100hz_grav", "auto": None}


def _profile_for_pool(pool: str) -> str | None:
    if pool not in _POOL_PROFILE:
        raise ValueError(f"pool must be one of {sorted(_POOL_PROFILE)}, got {pool!r}")
    return _POOL_PROFILE[pool]


def _load_windows(session_id: str, profile: str | None = None) -> pd.DataFrame:
    cached = find_windows(session_id, profile)
    if cached is not None:
        df = pd.read_csv(cached)
    elif profile is None:
        df = load_session_windows(session_id)
    else:
        # Why: explizites Profil ohne Datei darf nicht stillschweigend
        # die native Variante bauen — das wäre die falsche Form.
        raise FileNotFoundError(
            f"windows/{profile}/{session_id}_windows.csv fehlt — View erst "
            f"bauen (downsample → merge --watch-suffix → features --merged-suffix)."
        )
    df = df.copy()
    df["session_id"] = session_id
    return df


def _exclude_drawing_windows(
    all_windows: pd.DataFrame, timeline_loader=None
) -> pd.DataFrame:
    """Drop windows that fall inside a ``drawing`` task block.

    Non-handwriting pen motion (drawing/sketching/hatching) is out of scope
    for the writing detector; the ``drawing`` task was removed from v2 on
    2026-06-18, but already-recorded sessions (S042/S043) still carry the
    blocks in their marker CSVs and would otherwise enter training as the
    writing class. Marker-driven: matches windows by ``t_center_ms`` against
    each session's ``drawing`` blocks (half-open ``[start_ms, end_ms)``).
    Sessions without a marker CSV (empty timeline) are left untouched.
    """
    if timeline_loader is None:
        from src.evaluation.engagement import task_timeline as timeline_loader
    keep = pd.Series(True, index=all_windows.index)
    for sid, g in all_windows.groupby("session_id"):
        timeline = timeline_loader(sid)
        if timeline.empty:
            continue
        draw = timeline[timeline["task_id"] == "drawing"]
        if draw.empty:
            continue
        t = all_windows.loc[g.index, "t_center_ms"]
        for _, blk in draw.iterrows():
            in_block = (t >= blk["start_ms"]) & (t < blk["end_ms"])
            keep.loc[g.index[in_block.to_numpy()]] = False
    return all_windows[keep].reset_index(drop=True)


def _select_sessions(
    include_all: bool, min_windows: int, profile: str | None = None
) -> pd.DataFrame:
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
            lambda s: find_windows(s, profile) is not None
        )
    ]
    if min_windows > 0:
        kept = []
        for sid in sessions["session_id"]:
            n = sum(1 for _ in open(find_windows(sid, profile))) - 1
            if n >= min_windows:
                kept.append(sid)
            else:
                print(f"  skip {sid}  (n_windows={n} < {min_windows})")
        sessions = sessions[sessions["session_id"].isin(kept)]
    return sessions.reset_index(drop=True)


def _causal_rolling_mean(values: np.ndarray, n: int) -> np.ndarray:
    """Trailing (causal) rolling mean over a window of ``n`` samples.

    Window covers ``[i-n+1, i]`` (``min_periods=1`` at the start). No
    look-ahead: the smoothed value at position ``i`` depends only on the
    present and past, matching what a live Schreibzeit-tracker can compute
    at time ``i``. Replaces the earlier ``center=True`` smoothing, which
    averaged future windows into the current decision (non-causal — fine
    offline, but optimistic for a metric sold as live).
    """
    return pd.Series(values).rolling(n, min_periods=1).mean().to_numpy()


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
            s = _causal_rolling_mean(g["_proba"].to_numpy(), n)
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


def _zscore_train_pooled(
    train_df: pd.DataFrame, test_df: pd.DataFrame, feature_cols: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Leak-freie, deploy-repräsentative Standardisierung.

    μ/σ werden **pooled über die Trainings-Folds** geschätzt und auf Train UND
    Test angewendet. Anders als ``_zscore_per_session`` nutzt der Held-out
    **nicht** seine eigene (auch zukünftige) Session-Statistik — entspricht
    einem live deploybaren Modell mit eingebackenem pooled μ/σ (vgl.
    ``rf_all_live``). Returns ``(train_norm, test_norm)``; Eingaben unverändert.
    """
    mu = train_df[feature_cols].mean()
    sigma = train_df[feature_cols].std().replace(0.0, 1.0).fillna(1.0)
    tr = train_df.copy()
    te = test_df.copy()
    tr[feature_cols] = (tr[feature_cols] - mu) / sigma
    te[feature_cols] = (te[feature_cols] - mu) / sigma
    return tr, te


def _make_classifier(model: str, n_estimators: int, random_state: int,
                     params: dict | None = None):
    """Build a fresh estimator for the given registry model id.

    Hyperparameters match scripts/ml/compare_models.py so the cockpit and the
    offline panel train the same models. Linear/kernel/MLP get a StandardScaler
    in front; tree models expose feature_importances_ (the cockpit gates the
    importance card on registry.supports_feature_importance).

    ``params`` überschreibt die Estimator-Hyperparameter (z. B. SVM ``C``/
    ``gamma`` oder Tree ``max_depth``) — beim Pipeline-gewrappten Modell landet
    es im ``clf``-Step. Wird vom Hyperparameter-Sweep (``--model-params``) genutzt.
    """
    p = params or {}
    if model == "rf":
        return RandomForestClassifier(**{
            "n_estimators": n_estimators, "random_state": random_state,
            "class_weight": "balanced", "n_jobs": -1, **p})
    if model == "extratrees":
        return ExtraTreesClassifier(**{
            "n_estimators": n_estimators, "random_state": random_state,
            "class_weight": "balanced", "n_jobs": -1, **p})
    if model == "histgb":
        return HistGradientBoostingClassifier(**{
            "max_iter": 300, "learning_rate": 0.05, "random_state": random_state, **p})
    if model == "logreg":
        return Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(**{
                "max_iter": 2000, "class_weight": "balanced", **p})),
        ])
    if model == "mlp":
        return Pipeline([
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(**{
                "hidden_layer_sizes": (64, 32), "max_iter": 300,
                "early_stopping": True, "random_state": random_state, **p})),
        ])
    if model == "svm_rbf":
        return Pipeline([
            ("scaler", StandardScaler()),
            ("clf", SVC(**{
                "kernel": "rbf", "C": 1.0, "gamma": "scale",
                "probability": True, "class_weight": "balanced", **p})),
        ])
    raise ValueError(f"unknown classical model id {model!r}")


def _fit_eval_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    n_estimators: int,
    random_state: int,
    burst_scales: tuple[float, ...] = BURST_SCALES_SEC,
    model: str = "rf",
    model_params: dict | None = None,
) -> dict | None:
    """Train on train_df, evaluate on test_df. Returns None if test is single-class."""
    y_test = test_df["label"].to_numpy()
    if len(np.unique(y_test)) < 2:
        return None

    X_train = train_df[feature_cols].to_numpy()
    y_train = train_df["label"].to_numpy()
    X_test = test_df[feature_cols].to_numpy()

    clf = _make_classifier(model, n_estimators, random_state, model_params)
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    # Isotonische Kalibrierung für die Schreib-Prozent-Regression (Stufe 1).
    # Why: cv=3 splittet die Trainings-Folds NICHT personen-gruppiert —
    # bei N=10 und monotoner Kalibrierung vertretbar (bekannte Vereinfachung,
    # siehe docs/specs/2026-05-21-regression-schreibprozent-design.md).
    # Eigene Estimator-Instanz, damit der Headline-clf unangetastet bleibt.
    cal = CalibratedClassifierCV(
        _make_classifier(model, n_estimators, random_state, model_params),
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

    bursts = _burst_metrics(y_proba, y_test, test_df, scales_sec=burst_scales)

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
    model: str = "rf",
    model_params: dict | None = None,
) -> None:
    """Re-train on every available window and dump the deployment model."""
    print("\nTraining final model on all sessions…")
    clf = _make_classifier(model, n_estimators, random_state, model_params)
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


def _make_fold_sets(
    groups: list, folds: int | None, random_state: int
) -> list[list]:
    """Fold-Zuteilung der Subjects. ``folds=None`` (oder >= #Groups) = LOSO:
    ein Group je Fold. Sonst grouped-K-fold: die Groups werden in ``folds``
    Chunks partitioniert -- **leakage-frei**, weil ein Subject nie ueber
    Train/Test kreuzt (das waere Random-K-fold ueber Fenster -> Inflation).
    Round-robin-Zuteilung fuer balancierte Fold-Groessen, deterministisch
    ueber ``random_state``. Leere Chunks (K > #Groups) werden verworfen.
    """
    if folds is None or folds >= len(groups):
        return [[g] for g in groups]
    shuffled = list(groups)
    np.random.RandomState(random_state).shuffle(shuffled)
    return [chunk for i in range(folds) if (chunk := shuffled[i::folds])]


def train_loso(
    by: str = "person",
    folds: int | None = None,
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
    keep_drawing: bool = False,
    burst_scales: tuple[float, ...] = BURST_SCALES_SEC,
    window_sec: float = _param_cache.DEFAULT_WINDOW_SEC,
    stride_sec: float = _param_cache.DEFAULT_STRIDE_SEC,
    max_gap_ms: float = _param_cache.DEFAULT_MAX_GAP_MS,
    model: str = "rf",
    model_params: dict | None = None,
    on_event=None,
    run_dir: Path | None = None,
) -> dict:
    emit = on_event if on_event is not None else (lambda e: None)
    if by not in {"person", "session"}:
        raise ValueError(f"--by must be 'person' or 'session', got {by!r}")

    profile = _profile_for_pool(pool)
    sessions = _select_sessions(
        include_all=include_all, min_windows=min_windows, profile=profile
    )
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

    fold_sets = _make_fold_sets(groups, folds, random_state)
    cv_name = (f"LOSO-by-{by}" if len(fold_sets) == len(groups)
               else f"grouped-{len(fold_sets)}fold-by-{by}")

    print(
        f"{cv_name}: {len(fold_sets)} folds over "
        f"{len(groups)} {by}(s), {len(sessions)} session(s)"
    )

    sids = sessions["session_id"].tolist()
    if _param_cache.is_default_params(window_sec, stride_sec, max_gap_ms):
        frames = [_load_windows(s, profile) for s in sids]
    else:
        # Why: Feature-Fenster/Gap sind Build-Parameter — der kanonische
        # windows/{profile}/-Cache bleibt unangetastet, abweichende Kombis
        # liegen keyed im Param-Cache (einmal bauen, wiederverwenden).
        print(f"feature-params: window={window_sec}s stride={stride_sec}s "
              f"gap={int(max_gap_ms)}ms — Param-Cache (kanonischer Cache unberührt)")
        frames = []
        for s in sids:
            path = _param_cache.ensure_param_windows(
                s, pool, window_sec, stride_sec, max_gap_ms)
            df = pd.read_csv(path)
            df["session_id"] = s
            frames.append(df)
    all_windows = pd.concat(frames, ignore_index=True)
    all_windows = all_windows.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )

    if not keep_drawing:
        n_before = len(all_windows)
        all_windows = _exclude_drawing_windows(all_windows)
        n_dropped = n_before - len(all_windows)
        # Why: never silent — drawing is out of scope (non-handwriting pen
        # motion); print so the user can see how much training data it removed.
        if n_dropped:
            print(f"drawing-exclusion: dropped {n_dropped} window(s) "
                  f"from drawing task blocks")

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

    emit({"type": _events.RUN_START, "model": model, "by": by, "pool": pool,
          "n_folds": len(fold_sets), "features": len(feature_cols),
          "zscore": zscore_per_session})
    interrupted = False
    fold_results: list[dict] = []
    for fold_idx, held_group in enumerate(fold_sets, start=1):
        held_label = (str(held_group[0]) if len(held_group) == 1
                      else "+".join(map(str, held_group)))
        emit({"type": _events.FOLD_START, "idx": fold_idx,
              "person": held_label, "n": len(fold_sets)})
        test_mask = all_windows[group_col].isin(held_group)
        train_df = all_windows[~test_mask]
        test_df = all_windows[test_mask]

        held_out_sessions = sessions.loc[
            sessions[group_col].isin(held_group), "session_id"
        ].tolist()

        print(f"\n--- Fold {fold_idx}: held-out {by}={held_label} "
              f"({len(held_group)} {by}(s), sessions={held_out_sessions}) ---")
        try:
            res = _fit_eval_fold(
                train_df, test_df, feature_cols, n_estimators, random_state,
                burst_scales=burst_scales, model=model, model_params=model_params,
            )
        except KeyboardInterrupt:
            print("\n[stop] KeyboardInterrupt — finalisiere fertige Folds…")
            interrupted = True
            break
        if res is None:
            print(f"  skipped — test fold has only one class")
            continue

        res["held_out"] = held_label
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
        cm = res["confusion_matrix"]
        emit({"type": _events.FOLD_END, "idx": fold_idx, "person": held_label,
              "n": len(fold_sets), "acc": res["accuracy"], "auc": res["roc_auc"],
              "f1": res["f1_writing"],
              "burst": {k: v["accuracy"] for k, v in res["bursts"].items()},
              "confusion": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]),
                            "fn": int(cm[1, 0]), "tp": int(cm[1, 1])}})
        fold_results.append(res)

    if not fold_results:
        print("\n[warn] All folds skipped / interrupted. Nothing to summarise.")
        emit({"type": _events.RUN_END, "partial": interrupted, "n_done": 0,
              "mean_acc": 0.0, "std_acc": 0.0, "auc": 0.0, "f1": 0.0,
              "burst": {}, "out_dir": ""})
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

    print(f"\n=== {cv_name} summary ===")
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
            model=model,
            model_params=model_params,
        )

    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        per_fold_table.to_csv(run_dir / "cv.csv", index=False)
        pd.concat([r["oof"] for r in fold_results], ignore_index=True).to_csv(
            run_dir / "oof.csv", index=False)
        _train_final_model(all_windows, feature_cols, sessions,
                           n_estimators, random_state, run_dir / "model.joblib",
                           model=model)

    emit({"type": _events.RUN_END, "partial": interrupted,
          "n_done": len(fold_results),
          "mean_acc": summary["mean_accuracy"], "std_acc": summary["std_accuracy"],
          "auc": summary["mean_roc_auc"], "f1": summary["mean_f1_writing"],
          "burst": {k: v["mean_accuracy"] for k, v in burst_summary.items()},
          "out_dir": str(run_dir) if run_dir else ""})

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
        "--folds",
        type=int,
        default=None,
        help="Grouped-K-fold statt LOSO: die Subjects in K Chunks partitionieren "
        "(leakage-frei — Subjects kreuzen nie Train/Test, KEIN Random-K-fold "
        "ueber Fenster). Default: None = LOSO (ein Subject je Fold). Z.B. --folds 5.",
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
        "'modern' (gravity-required sessions only, 92 features). "
        "Default: auto.",
    )
    p.add_argument(
        "--no-pool-suffix",
        action="store_true",
        help="Save-Pfade NICHT mit dem Pool-Namen suffixen — bewusster "
        "Override, um einen Pool-Lauf zur kanonischen Headline zu machen "
        "(rf_all.joblib / loso_cv.csv / loso_oof.csv). Der _nogravity-"
        "Suffix des Ablation-Arms bleibt immer erhalten.",
    )
    p.add_argument(
        "--drop-gravity",
        action="store_true",
        help="Ablation arm: drop the gravity feature columns while keeping "
        "the session selection unchanged (paired 88-vs-92 comparison on "
        "identical folds). Save paths get a *_nogravity suffix.",
    )
    p.add_argument(
        "--keep-drawing",
        action="store_true",
        help="Keep windows from `drawing` task blocks (default: exclude them). "
        "Drawing is non-handwriting pen motion and out of scope for the "
        "detector; use this only for ablation/reproduction.",
    )
    p.add_argument(
        "--burst-scales",
        default=None,
        help="Comma-separated decision-window scales in seconds for burst "
        "aggregation (default: 5,10,30). The 1 s per-window metric is always "
        "reported. Empty string reports only the 1 s base.",
    )
    p.add_argument(
        "--window-sec", type=float, default=_param_cache.DEFAULT_WINDOW_SEC,
        help="Feature-Fenstergröße in Sekunden (Default 1.0). Stride = window/2 "
        "(50%% Overlap). Abweichend vom Default → Features werden in einen keyed "
        "Param-Cache gebaut, der kanonische windows/-Cache bleibt unberührt.",
    )
    p.add_argument(
        "--max-gap-ms", type=float, default=_param_cache.DEFAULT_MAX_GAP_MS,
        help="Label-Closing-Gap in ms (Default 2500). Idle-Lücken ≤ diesem Wert "
        "zwischen Schreibphasen zählen als Schreibmodus.",
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
    p.add_argument(
        "--emit-json", action="store_true",
        help="Strukturierte JSON-Events auf stdout (für den Web-Launcher).",
    )
    p.add_argument(
        "--run-dir", type=Path, default=None,
        help="Artefakte (cv.csv/oof.csv/model.joblib) in dieses Verzeichnis "
        "schreiben (nicht-destruktiver Run-Store des Web-Cockpits).",
    )
    p.add_argument(
        "--model", default="rf",
        help="Klassische Registry-Modell-ID: rf | extratrees | histgb | "
             "logreg | svm_rbf | mlp.",
    )
    p.add_argument(
        "--model-params", default=None,
        help="JSON-Dict mit Estimator-Hyperparameter-Overrides für den Sweep, "
             "z. B. '{\"C\": 10, \"gamma\": 0.01}' (svm_rbf) oder "
             "'{\"max_depth\": 12}' (extratrees). Beim Pipeline-Modell landet es "
             "im clf-Step.",
    )
    return p.parse_args()


def _pool_suffixed_path(
    default_path: Path, pool: str, drop_gravity: bool = False,
    pool_suffix: bool = True,
) -> Path:
    """Suffix the save path with the pool name to keep artefacts separate.

    Why: the canonical headline artefacts (rf_all.joblib, loso_oof.csv,
    loso_cv.csv) are consumed by other pipelines (Live-Inference,
    Regression, Engagement). Saving a pool-specific model under the same
    path SILENTLY corrupts those downstream tools — pool != 'auto' →
    write to *_modern.* / *_legacy.* sibling instead. ``pool_suffix=False``
    (CLI: --no-pool-suffix) is the deliberate override for promoting a
    pool run to the canonical headline. The --drop-gravity suffix is
    NOT overridable: the ablation arm must never become canonical.
    """
    parts = [default_path.stem]
    if pool != "auto" and pool_suffix:
        parts.append(pool)
    if drop_gravity:
        parts.append("nogravity")
    if len(parts) == 1:
        return default_path
    return default_path.with_name(f"{'_'.join(parts)}{default_path.suffix}")


if __name__ == "__main__":
    args = _parse_args()
    _suffix = not args.no_pool_suffix
    save_final = (
        _pool_suffixed_path(Path(args.save_final_model), args.pool,
                            args.drop_gravity, pool_suffix=_suffix)
        if args.save_final_model else None
    )
    save_cv = (
        _pool_suffixed_path(Path(args.save_cv_csv), args.pool,
                            args.drop_gravity, pool_suffix=_suffix)
        if args.save_cv_csv else None
    )
    save_oof = (
        _pool_suffixed_path(Path(args.save_oof), args.pool,
                            args.drop_gravity, pool_suffix=_suffix)
        if args.save_oof else None
    )
    train_loso(
        by=args.by,
        folds=args.folds,
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
        keep_drawing=args.keep_drawing,
        burst_scales=(_parse_burst_scales(args.burst_scales)
                      if args.burst_scales is not None else BURST_SCALES_SEC),
        window_sec=args.window_sec,
        stride_sec=args.window_sec / 2.0,  # 50% Overlap, wie im Window-Sweep
        max_gap_ms=args.max_gap_ms,
        model=args.model,
        model_params=(json.loads(args.model_params) if args.model_params else None),
        on_event=_events.json_line_emitter() if args.emit_json else None,
        run_dir=args.run_dir,
    )
