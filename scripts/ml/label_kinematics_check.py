"""Falsifiziert Reviewer-Verdacht #3 (Varianz-Alignment mappt Schreiben auf Ruhe).

Pooled über alle Legacy-Window-CSVs: vergleicht die Bewegungs-/Jerk-Energie der
Schreib-Fenster (label=1) gegen Idle (label=0). Ist Schreiben die dynamischere
Klasse (ratio > 1 bei Jerk), kann das Alignment die Labels NICHT auf ruhige
Handgelenk-Phasen invertiert haben.

NB: Das ersetzt **nicht** die manuelle Video-Ground-Truth (Reviewer-Fix #5,
Gold-Standard) — es testet nur die *falsifizierbare Konsequenz* des Verdachts
reproduzierbar auf den vorhandenen Daten.

CLI: ``python scripts/ml/label_kinematics_check.py``
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.label_diagnostics import class_kinematics_summary  # noqa: E402

# Jerk = Rate-of-Change der Beschleunigung = die Fein-Motor-Dynamik des Schreibens.
JERK_COLS = ["ax_jerk_mean_abs", "ay_jerk_mean_abs", "az_jerk_mean_abs",
             "acc_mag_jerk_mean_abs", "gyro_mag_jerk_mean_abs",
             "ax_jerk_std", "ay_jerk_std", "az_jerk_std"]
VAR_COLS = ["ax_std", "ay_std", "az_std", "acc_mag_std"]


def main() -> None:
    files = sorted(glob.glob(str(ROOT / "data/processed/windows/50hz/*_windows.csv")))
    if not files:
        raise SystemExit("Keine 50hz-Window-CSVs gefunden.")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    n_w = int((df["label"] == 1).sum())
    n_i = int((df["label"] == 0).sum())
    print(f"{len(files)} Sessions | {len(df)} Fenster | writing={n_w} idle={n_i}\n")

    summ = class_kinematics_summary(df, JERK_COLS + VAR_COLS)
    print(f"{'feature':<24}{'writing':>10}{'idle':>10}{'w/idle':>9}")
    for r in summ.itertuples():
        print(f"{r.feature:<24}{r.writing_mean:>10.4f}{r.idle_mean:>10.4f}{r.ratio:>9.2f}")

    jerk = summ[summ["feature"].isin(JERK_COLS)]
    median_jerk_ratio = float(jerk["ratio"].median())
    higher = int((jerk["ratio"] > 1.0).sum())
    print(f"\nJerk-Features mit writing > idle: {higher}/{len(jerk)}, "
          f"Median-Ratio {median_jerk_ratio:.2f}")
    if median_jerk_ratio > 1.0:
        print("VERDIKT: Schreiben ist die DYNAMISCHERE Klasse (höherer Jerk) — "
              "Verdacht 'Schreiben = ruhiges Handgelenk' WIDERLEGT.")
    else:
        print("VERDIKT: Schreiben ist NICHT dynamischer — Verdacht gestützt, "
              "Alignment-Bias plausibel. Bitte Video-Check.")


if __name__ == "__main__":
    main()
