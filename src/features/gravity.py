"""Gravity-aware window features (Modern-Pool ab 2026-05-26).

Ergänzt die 88 dynamic-only Features aus ``src/features/windows.py`` um
4 orientierungs-basierte Features, wenn ``gx/gy/gz``-Spalten im
Merged-CSV vorhanden sind. CoreMotion liefert ``motion.gravity`` in G's
(Einheit: standard gravity) — ein ruhendes Wrist hat also ``|g| ≈ 1.0``,
nicht 9.81.

Why nur Tilt, keine Magnitude: ``motion.gravity`` ist per CoreMotion-
Definition ein Einheitsvektor (``|g| ≈ 1.000`` immer). ``grav_mag_mean``
hat damit keine Varianz und ``grav_mag_std`` ist ≈ 0 — beide trugen im
S038-Within-Session-RF exakt 0.0 Importance (Rang #93/#94 von 94) und
wurden 2026-05-29 ersatzlos gestrichen. Das Gravity-Signal sitzt
vollständig in der Wrist-Orientierung (``tilt_*_mean``).

Backward-compat: bei fehlenden Spalten oder NaN-Werten kommen alle 4
Features als NaN zurück, damit Legacy-Sessions die Pipeline nicht
crashen.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

GRAVITY_FEATURE_NAMES = [
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

    # Direkter Winkel zwischen aufeinanderfolgenden Gravity-Vektoren.
    # Why: Per-Achsen-Mittel von |Δtilt_axis| unterschätzt reine Rotationen
    # systematisch, weil sich Winkeländerungen auf mehrere Achsen verteilen
    # (eine 90°-Rotation um eine Achse zeigt sich in zwei Achsen-Tilts mit
    # je ~45°). Die Vektor-Winkel-Formel ist koordinatensystem-unabhängig
    # und misst die echte Reorientierungs-Geschwindigkeit.
    if len(gx) > 1:
        g_curr = np.stack([gx[:-1], gy[:-1], gz[:-1]], axis=1)
        g_next = np.stack([gx[1:], gy[1:], gz[1:]], axis=1)
        norms_curr = grav_mag_safe[:-1]
        norms_next = grav_mag_safe[1:]
        cos_step = np.einsum("ij,ij->i", g_curr, g_next) / (
            norms_curr * norms_next
        )
        tilt_change = float(np.arccos(np.clip(cos_step, -1.0, 1.0)).mean())
    else:
        tilt_change = 0.0

    return {
        "tilt_x_mean": float(tilt_x.mean()),
        "tilt_y_mean": float(tilt_y.mean()),
        "tilt_z_mean": float(tilt_z.mean()),
        "tilt_change": float(tilt_change),
    }
