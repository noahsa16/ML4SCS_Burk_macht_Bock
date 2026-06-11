"""Kinematische Label-Diagnostik (Falsifikation des Alignment-Bias-Verdachts).

Reviewer-Verdacht #3: das varianz-minimierende Pen↔Watch-Alignment mappe
Schreib-Labels auf *ruhige* Handgelenk-Phasen, sodass das Modell auf paradoxen
Labels („stilles Handgelenk = Schreiben") trainiert. Falsifizierbare
Konsequenz: Schreib-Fenster hätten dann *niedrigere* Bewegungs-/Jerk-Energie
als Idle. ``class_kinematics_summary`` misst genau das.
"""
from __future__ import annotations

import pandas as pd


def class_kinematics_summary(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Per-Klassen-Mittel (writing=1 vs idle=0) + Ratio für jede Feature-Spalte.

    Returns DataFrame ``[feature, writing_mean, idle_mean, ratio]`` mit
    ``ratio = writing_mean / idle_mean``. Ratio > 1 bei Jerk-/Dynamik-Features
    heißt: Schreiben ist die *dynamischere* Klasse → der „Schreiben = Ruhe"-
    Verdacht ist falsifiziert. Fehlende Spalten werden übersprungen.
    """
    if df["label"].nunique() < 2:
        raise ValueError("brauche beide Klassen (writing=1 und idle=0)")
    cols = [c for c in feature_cols if c in df.columns]
    w = df[df["label"] == 1]
    idle = df[df["label"] == 0]
    rows = []
    for c in cols:
        wm = float(w[c].mean())
        im = float(idle[c].mean())
        rows.append({"feature": c, "writing_mean": wm, "idle_mean": im,
                     "ratio": (wm / im) if im else float("nan")})
    return pd.DataFrame(rows)
