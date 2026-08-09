"""Geteilte, reine Fusions-Kernlogik (OOF-Normalisierung, N-Wege-Alignment,
per-Fold-Metriken, Proba-Mittel).

Single source of truth für ``scripts/ml/tcn_rf_fusion.py`` (2-Wege) und
``scripts/ml/ensemble_committee.py`` (N-Wege). Alle Funktionen sind rein und
GPU-frei — reines Post-Processing auf OOF-CSVs, die auf identischen Folds
(LOSO-by-person, ``random_state=42``) liegen.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.metrics import roc_auc_score

from src.evaluation.significance import paired_fold_test


def _pick(cols: list[str], candidates: tuple[str, ...]) -> str:
    for c in candidates:
        if c in cols:
            return c
    raise KeyError(f"keine von {candidates} in {cols}")


def normalise_oof(df: pd.DataFrame) -> pd.DataFrame:
    """Robust auf einheitliche Spalten: session_id, t_center_ms, person_id, y, proba."""
    cols = list(df.columns)
    proba = _pick(cols, ("proba_cal", "proba", "proba_raw"))
    label = _pick(cols, ("label", "y"))
    person = _pick(cols, ("person_id", "held_out", "person"))
    out = df.rename(columns={proba: "proba", label: "y", person: "person_id"})
    return out[["session_id", "t_center_ms", "person_id", "y", "proba"]].copy()


def align_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Paart N OOF-Frames per Session auf nächstem t_center (nearest).

    Der **erste** Eintrag ist die Basis (liefert ``y`` + ``person_id``); jeder
    weitere steuert eine Spalte ``{name}_proba`` bei. ``merge_asof(direction=
    'nearest')`` fängt kleine Gitter-Offsets zwischen den Läufen ab. Fenster
    ohne Match in irgendeinem Arm werden verworfen. Returns: session_id,
    t_center_ms, person_id, y, und je ein ``{name}_proba``.
    """
    items = list(frames.items())
    if not items:
        raise ValueError("align_frames braucht mindestens einen Frame")
    base_name, base_df = items[0]
    merged = (normalise_oof(base_df)
              .rename(columns={"proba": f"{base_name}_proba"})
              .sort_values("t_center_ms"))
    for name, df in items[1:]:
        right = (normalise_oof(df)[["session_id", "t_center_ms", "proba"]]
                 .rename(columns={"proba": f"{name}_proba"})
                 .sort_values("t_center_ms"))
        merged = pd.merge_asof(merged, right, on="t_center_ms", by="session_id",
                               direction="nearest")
    proba_cols = [f"{n}_proba" for n, _ in items]
    missing = int(merged[proba_cols].isna().any(axis=1).sum())
    if missing:
        print(f"[committee] {missing} Fenster ohne vollständigen Match — verworfen")
        merged = merged.dropna(subset=proba_cols)
    return merged.reset_index(drop=True)


def per_fold_metrics(df: pd.DataFrame, proba_col: str) -> pd.DataFrame:
    """Per-Person acc/AUC auf nativer Decision (ein Fenster = eine Entscheidung).

    Returns significance.py-kompatibles CV: held_out, accuracy, roc_auc.
    """
    rows = []
    for person, g in df.groupby("person_id"):
        y = g["y"].to_numpy()
        p = g[proba_col].to_numpy()
        acc = float(((p >= 0.5).astype(int) == y).mean())
        try:
            auc = float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan")
        except ValueError:
            auc = float("nan")
        rows.append({"held_out": person, "accuracy": acc, "roc_auc": auc})
    return pd.DataFrame(rows).sort_values("held_out").reset_index(drop=True)


def mean_proba(probas: list[np.ndarray]) -> np.ndarray:
    """Gleichgewichtetes Proba-Mittel über N Arme."""
    return np.mean(np.vstack([np.asarray(p, dtype=float) for p in probas]), axis=0)


def paired_metric(a_cv: pd.DataFrame, b_cv: pd.DataFrame, metric: str) -> dict:
    """paired_fold_test auf gemeinsamen Folds (held_out) für eine Metrik."""
    m = a_cv[["held_out", metric]].merge(
        b_cv[["held_out", metric]], on="held_out", suffixes=("_a", "_b")).dropna()
    return paired_fold_test(m[f"{metric}_a"].to_numpy(), m[f"{metric}_b"].to_numpy())


def residual_corr(aligned: pd.DataFrame, members: list[str]) -> float:
    """Mittlere paarweise Pearson-Korrelation der Residuen ``proba − y``.

    Leitgröße der Fusion: hohe Residuen-Korrelation → Modelle irren an denselben
    Fenstern → wenig Fusions-Spielraum. Bei einem Paar = die eine Korrelation,
    bei N Mitgliedern der Mittelwert aller Paare.
    """
    y = aligned["y"].to_numpy()
    resid = {m: aligned[f"{m}_proba"].to_numpy() - y for m in members}
    rs = [pearsonr(resid[a], resid[b])[0] for a, b in combinations(members, 2)]
    return float(np.mean(rs)) if rs else float("nan")
