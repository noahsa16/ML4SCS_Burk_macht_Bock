"""Rohe Sequenz-Windows fuer die Deep-Modelle.

Liest ``data/processed/{session}_merged.csv`` und baut ueberlappende
Fenster ueber den 50-Hz-Watch-Stream — analog zu :mod:`src.features.windows`,
aber behaelt die rohen Samples (6 Kanaele) statt der 88 Features. Die
sample-level Label werden mit derselben :func:`smooth_labels`-Funktion
geglaettet (Single Source of Truth fuer das morphologische Closing).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.features.windows import ACC_COLS, IMU_COLS, smooth_labels

ROOT = Path(__file__).parents[3]
DATA_PROC = ROOT / "data" / "processed"

# Modern-Pool-Schwerkraft-Kanaele (motion.gravity). Nur mit gravity=True gefuettert.
GRAVITY_COLS = ("gx", "gy", "gz")

# Waehlbare Kanalsaetze. "imu" ist der Trainings-Default (6 bzw. 9 mit gravity).
# Die beiden 3-Kanal-Saetze bedienen das Passiv-Deployment: CMSensorRecorder
# liefert ausschliesslich das Accelerometer, und zwar die ROHE Gesamt-
# beschleunigung (userAcceleration + Schwerkraft) -- CoreMotion rechnet die
# Schwerkraft nur im gyro-fusionierten CMDeviceMotion heraus. "raw_accel"
# rekonstruiert genau dieses Deployment-Signal aus dem Modern-Pool, sodass
# train == deploy gilt; "user_accel" ist der Kontrollarm, der die Variable
# "accel-only" von der Variable "roh statt fusioniert" trennt.
CHANNEL_SETS = ("imu", "raw_accel", "user_accel")


def build_raw_windows(
    merged: pd.DataFrame,
    seq_len: int,
    stride: int = 25,
    min_label_ratio: float = 0.6,
    max_gap_ms: float = 2500.0,
    exclude_boundary: tuple[float, float] | None = None,
    gravity: bool = False,
    channels: str = "imu",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Baue rohe Sequenz-Fenster aus einer watch-base gemergten CSV.

    Returns ``(X, y, t_center_ms)``:
      * ``X``  — float32, Shape ``(n_windows, seq_len, 6)``
      * ``y``  — int64, Shape ``(n_windows,)``; 1 iff writing-Anteil >=
        ``min_label_ratio``
      * ``t_center_ms`` — float64, Mittel-Zeitstempel je Fenster

    ``stride`` ist in Samples (25 = 0,5 s @ 50 Hz, wie der RF-Window-Stride).
    Wird wie in :func:`src.features.windows.build_windows` unabhaengig von
    ``seq_len`` gehalten, damit die Burst-Aggregation denselben dt sieht.

    ``max_gap_ms`` defaultet auf den Headline-Pipeline-Wert 2500 (nicht auf
    den historischen 300er-Default von :func:`build_windows`) — die
    Deep-Modelle werden ausschliesslich in der Headline-Konfiguration
    trainiert, ein Closing-Wert hier ist die richtige Voreinstellung.

    ``exclude_boundary`` (lo, hi): Fenster, deren writing-Anteil *echt*
    zwischen ``lo`` und ``hi`` liegt, werden verworfen. Diese Fenster
    straddeln einen writing<->idle-Uebergang und sind durch die
    ``min_label_ratio``-Schwelle inhaerent mehrdeutig gelabelt — fuer das
    Label-Qualitaets-Experiment lassen sie sich so ausschliessen.
    """
    if seq_len < 2 or stride < 1:
        raise ValueError(f"seq_len/stride too small: seq_len={seq_len}, stride={stride}")
    if channels not in CHANNEL_SETS:
        raise ValueError(
            f"channels must be one of {list(CHANNEL_SETS)}, got {channels!r}")
    if channels != "imu" and gravity:
        # Why: die 3-Kanal-Saetze definieren ihren Umgang mit der Schwerkraft
        # bereits selbst (raw_accel addiert sie auf, user_accel laesst sie weg).
        # gravity=True zusaetzlich waere widerspruechlich statt additiv.
        raise ValueError(
            f"gravity=True is only valid with channels='imu', got {channels!r}")

    if channels == "imu":
        cols = list(IMU_COLS) + (list(GRAVITY_COLS) if gravity else [])
        n_ch = len(cols)  # 6 (Default) oder 9 (mit Gravity gx/gy/gz)
    elif channels == "user_accel":
        cols = list(ACC_COLS)
        n_ch = 3
    else:  # raw_accel -- Schwerkraft wird auf die Accel-Achsen addiert
        cols = list(ACC_COLS) + list(GRAVITY_COLS)
        n_ch = 3
    needed = {*cols, "label_writing", "local_ts_ms"}
    missing = needed - set(merged.columns)
    if missing:
        raise ValueError(f"merged CSV is missing columns: {sorted(missing)}")

    # Why: stable sort by per-sample `ts` (when available) matches
    # src/features/windows.py and the live-inference buffer — see
    # reports/sort_stability_bug.md. Pre-fix unstable sort by local_ts_ms
    # scrambled within-batch order and gave Deep models order-corrupted
    # raw sequences.
    sort_col = "ts" if "ts" in merged.columns else "local_ts_ms"
    df = merged.dropna(subset=[*cols, sort_col]).sort_values(sort_col, kind="stable")
    empty = (
        np.empty((0, seq_len, n_ch), dtype=np.float32),
        np.empty(0, dtype=np.int64),
        np.empty(0, dtype=np.float64),
    )
    if len(df) < seq_len:
        return empty

    imu = df[cols].to_numpy(dtype=np.float32)
    if channels == "raw_accel":
        imu = imu[:, :3] + imu[:, 3:]
    times = df["local_ts_ms"].to_numpy(dtype=float)
    raw_labels = df["label_writing"].to_numpy(dtype=int)
    labels = smooth_labels(raw_labels, times, max_gap_ms=max_gap_ms).astype(float)

    xs: list[np.ndarray] = []
    ys: list[int] = []
    ts: list[float] = []
    for start in range(0, len(df) - seq_len + 1, stride):
        end = start + seq_len
        frac = float(labels[start:end].mean())
        if exclude_boundary is not None:
            lo, hi = exclude_boundary
            if lo < frac < hi:
                continue
        xs.append(imu[start:end])
        ys.append(int(frac >= min_label_ratio))
        ts.append(float(times[start:end].mean()))

    if not xs:
        return empty
    return (
        np.stack(xs).astype(np.float32),
        np.array(ys, dtype=np.int64),
        np.array(ts, dtype=np.float64),
    )


def zscore_channels(X: np.ndarray) -> np.ndarray:
    """Per-Kanal-Z-Score ueber alle Samples in ``X`` (eine Session).

    ``X`` hat Shape ``(n_windows, seq_len, 6)``. mu und sigma werden ueber
    alle ``n_windows x seq_len`` Zeitschritte je Kanal berechnet — das ist
    der Sequenz-Pendant zum Per-Session-Z-Score des RF: subjekt-abhaengige
    Baselines (Handgelenk-Groesse, Watch-Position) werden entfernt, die
    relative Struktur bleibt erhalten. sigma < 1e-8 (konstanter Kanal) -> 1.0.
    """
    if len(X) == 0:
        return X
    flat = X.reshape(-1, X.shape[-1])
    mu = flat.mean(axis=0)
    sigma = flat.std(axis=0)
    sigma = np.where(sigma < 1e-8, 1.0, sigma)
    return ((X - mu) / sigma).astype(np.float32)


def load_session_raw(
    session_id: str,
    seq_len: int,
    merged_suffix: str | None = None,
    zscore: bool = False,
    **kwargs,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lese die merged CSV, baue Fenster und (optional) z-score sie.

    ``merged_suffix`` waehlt die Quelle: ``None`` -> native
    ``{sid}_merged.csv``; ``"legacy"`` -> die downsampled 50-Hz-View
    ``{sid}_merged_legacy.csv`` (via :mod:`src.features.downsample`). So
    kann eine Modern-Session (100 Hz, 9 Kanaele) im Legacy-Pool als
    50-Hz-View mittrainiert werden, ohne die Sample-Rate zu mischen.

    ``zscore`` (default **False**): per-Session-per-Kanal-Z-Score, das
    Sequenz-Pendant zum RF-Per-Session-Z-Score. Default aus, weil er fuers
    CNN empirisch neutral ist (gepaartes A/B, N=14: Δacc −0.002, p=0.65) und
    Weglassen ein Deployment-Gewinn ist — kein Per-Stream-Kalibrieren von
    μ/σ noetig. Mechanik: BatchNorm normalisiert Conv-*Outputs* ueber den
    Batch (nicht die rohe Eingangs-Skala je Subjekt), macht das Netz aber
    scale-tolerant genug. ``True`` schaltet ihn wieder ein.

    ``kwargs`` werden an :func:`build_raw_windows` durchgereicht
    (``stride``, ``min_label_ratio``, ``max_gap_ms``).
    """
    stem = f"{session_id}_merged" + (f"_{merged_suffix}" if merged_suffix else "")
    merged_path = DATA_PROC / f"{stem}.csv"
    if not merged_path.exists():
        if merged_suffix:
            raise FileNotFoundError(
                f"{merged_path} fehlt — die Legacy-View erst bauen: "
                f"`python -m src.features.downsample {session_id} --target-hz 50` "
                f"dann `python -m src.merge {session_id} --watch-suffix {merged_suffix}`."
            )
        raise FileNotFoundError(
            f"{merged_path} fehlt — vorher `python -m src.merge {session_id}` laufen lassen."
        )
    merged = pd.read_csv(merged_path)
    X, y, t = build_raw_windows(merged, seq_len, **kwargs)
    return (zscore_channels(X) if zscore else X), y, t
