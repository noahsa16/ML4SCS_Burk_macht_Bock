"""Gravity-aware window features (Modern-Pool ab 2026-05-26).

Ergänzt die 88 dynamic-only Features aus ``src/features/windows.py`` um
6 orientierungs-basierte Features, wenn ``gx/gy/gz``-Spalten im
Merged-CSV vorhanden sind. CoreMotion liefert ``motion.gravity`` in G's
(Einheit: standard gravity) — ein ruhendes Wrist hat also ``|g| ≈ 1.0``,
nicht 9.81.

Backward-compat: bei fehlenden Spalten oder NaN-Werten kommen alle 6
Features als NaN zurück, damit Legacy-Sessions die Pipeline nicht
crashen.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

GRAVITY_FEATURE_NAMES = [
    "grav_mag_mean",   # ≈ 1.0 G im Ruhezustand; Drift = Sensor-Issue
    "grav_mag_std",    # 0 im Ruhezustand; > 0 bei schneller Reorientierung
    "tilt_x_mean",     # Winkel zwischen x-Achse und Gravity, [0, π]
    "tilt_y_mean",     # Winkel zwischen y-Achse und Gravity, [0, π]
    "tilt_z_mean",     # Winkel zwischen z-Achse und Gravity, [0, π]
    "tilt_change",     # mittlere |Δtilt| über die Achsen, captures Re-Orient
]


def _nan_features() -> dict[str, float]:
    return {name: float("nan") for name in GRAVITY_FEATURE_NAMES}


def _gravity_window_features(window_df: pd.DataFrame) -> dict[str, float]:
    """Per-Window Features die motion.gravity nutzen.

    Bei fehlenden Spalten oder NaN-Werten in der Window → alle 6
    Features NaN (kein Crash, Caller kann filtern oder Imputation
    machen).
    """
    if not {"gx", "gy", "gz"}.issubset(window_df.columns):
        return _nan_features()

    gx = window_df["gx"].to_numpy(dtype=float)
    gy = window_df["gy"].to_numpy(dtype=float)
    gz = window_df["gz"].to_numpy(dtype=float)
    if np.isnan(gx).any() or np.isnan(gy).any() or np.isnan(gz).any():
        return _nan_features()

    grav_mag = np.sqrt(gx * gx + gy * gy + gz * gz)
    # Why: tilt-Berechnung dividiert durch grav_mag; bei free-fall oder
    # Sensor-Glitch könnte das 0 sein. Wir clampen damit arccos nicht
    # crasht — die Tilt-Werte sind dann undefined-but-finite.
    grav_mag_safe = np.where(grav_mag > 1e-6, grav_mag, 1.0)

    # arccos(clip(...)) gegen Floating-Point-Drift, der g_axis/|g|
    # marginal aus [-1, 1] schieben kann.
    tilt_x = np.arccos(np.clip(gx / grav_mag_safe, -1.0, 1.0))
    tilt_y = np.arccos(np.clip(gy / grav_mag_safe, -1.0, 1.0))
    tilt_z = np.arccos(np.clip(gz / grav_mag_safe, -1.0, 1.0))

    if len(tilt_x) > 1:
        tilt_change = (
            float(np.mean(np.abs(np.diff(tilt_x))))
            + float(np.mean(np.abs(np.diff(tilt_y))))
            + float(np.mean(np.abs(np.diff(tilt_z))))
        ) / 3.0
    else:
        tilt_change = 0.0

    return {
        "grav_mag_mean": float(grav_mag.mean()),
        "grav_mag_std": float(grav_mag.std()),
        "tilt_x_mean": float(tilt_x.mean()),
        "tilt_y_mean": float(tilt_y.mean()),
        "tilt_z_mean": float(tilt_z.mean()),
        "tilt_change": float(tilt_change),
    }
