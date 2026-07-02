"""Rhythmus-/Periodizitäts-Features gegen die Tipp-vs-Schreib-Verwechslung.

Motivation (Marker-FPR-Befund 2026-07-01): das Modell verwechselt keyboard/phone-
Tippen mit Schreiben (P17: 0.63-0.68 FPR). Tippen ist **regelmäßiger** als Schreiben
— gleichmäßige Anschläge vs. variable Buchstaben-Kinematik. Die bestehenden 88
Features (dominante Frequenz, 3-8-Hz-Band, ZCR) erfassen kein explizites
**Regelmäßigkeits-Maß**. Diese 4 Features schließen die Lücke:

- **Autokorrelations-Peak-Höhe** (das orthogonalste neue Signal): stärkster
  normalisierter Autokorrelations-Peak in der Rhythmus-Band-Lag-Spanne. Periodisches
  Signal (Tippen) → hoher Peak; irreguläres (Schreiben) → niedrig. Zeit-Domäne,
  nicht spektral → ergänzt die vorhandenen Spektral-Features.
- **Spektrale Flatness** (Wiener-Entropie): geo/arith-Mittel des Leistungsspektrums.
  →0 bei schmalbandig/peakig (Tippen), →1 bei breitbandig (Schreiben). Kann mit der
  vorhandenen spectral_entropy überlappen — Feature-Importance + Signifikanz
  entscheiden, ob es trägt.

Berechnet auf accel-mag + gyro-mag (rotations-invariant, lean = 4 Features gegen
Overfitting bei N=20).
"""
from __future__ import annotations

import numpy as np


def spectral_flatness(x: np.ndarray, eps: float = 1e-12) -> float:
    """geo/arith-Mittel des Leistungsspektrums (DC entfernt). [0,1], klein=peakig."""
    x = np.asarray(x, dtype=float)
    if len(x) < 2 or np.allclose(x, x[0]):
        return 1.0  # konstant -> keine Peaks -> maximal flach
    spec = np.abs(np.fft.rfft(x - x.mean())) ** 2
    spec = spec[1:]  # DC-Bin raus
    if spec.size == 0 or spec.sum() <= 0:
        return 1.0
    spec = spec + eps
    gm = float(np.exp(np.mean(np.log(spec))))
    am = float(np.mean(spec))
    return gm / am


def autocorr_peak(x: np.ndarray, fs_hz: float,
                  lo_hz: float = 2.0, hi_hz: float = 12.0) -> float:
    """Höchster normalisierter Autokorr-Peak in der Rhythmus-Band-Lag-Spanne.

    Lags entsprechen [fs/hi_hz, fs/lo_hz]. Hoch = periodisch (Tippen). [0,1]-nah.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 4 or np.allclose(x, x[0]):
        return 0.0
    x = x - x.mean()
    r = np.correlate(x, x, mode="full")[n - 1:]  # r[0..n-1], r[0] = Energie
    if r[0] <= 0:
        return 0.0
    r = r / r[0]
    lo_lag = max(1, int(np.floor(fs_hz / hi_hz)))
    hi_lag = min(n - 1, int(np.ceil(fs_hz / lo_hz)))
    if hi_lag <= lo_lag:
        return 0.0
    return float(np.max(r[lo_lag:hi_lag + 1]))


def rhythm_window_features(acc_mag: np.ndarray, gyro_mag: np.ndarray,
                           fs_hz: float) -> dict[str, float]:
    """4 Rhythmus-Features für ein Fenster (accel-mag + gyro-mag)."""
    return {
        "acc_mag_flatness": spectral_flatness(acc_mag),
        "gyro_mag_flatness": spectral_flatness(gyro_mag),
        "acc_mag_autocorr_peak": autocorr_peak(acc_mag, fs_hz),
        "gyro_mag_autocorr_peak": autocorr_peak(gyro_mag, fs_hz),
    }


RHYTHM_FEATURE_NAMES = (
    "acc_mag_flatness", "gyro_mag_flatness",
    "acc_mag_autocorr_peak", "gyro_mag_autocorr_peak",
)
