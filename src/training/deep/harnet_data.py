"""Bridge von ``data/processed/{session}_merged.csv`` zu harnet-Fenstern.

Das Oxford ``ssl-wearables``-Foundation-Model (harnet) erwartet Input
``(N, 3, 150)``: 3 Accel-Kanaele, 5 s @ 30 Hz, **Einheiten in g**. Unsere
Watch streamt 50 oder 100 Hz; diese Bruecke resampled per Session auf
30 Hz und schneidet 5-s-Fenster.

Bewusste Forschungsentscheidungen (siehe Aufgabenstellung, nicht aendern):

* **Input = ``userAcceleration`` (ax/ay/az) OHNE Gravity.** Das ist ein
  Distribution-Shift ggue. dem Biobank-Pretraining (Total-Accel inkl. g),
  aber der Legacy-Pool hat kein Gravity. Im Report als Limitation.
* **Kein Per-Session-Z-Score** auf den Inputs — das Netz erwartet g.
* **Resampling via ``scipy.signal.resample_poly``** (Polyphase-FIR), nicht
  ``decimate`` (kein Integer-Faktor 50/100 -> 30) und nicht naive
  Interpolation. 50->30 = (up=3, down=5), 100->30 = (up=3, down=10).
* **Stable-Sort nach per-Sample ``ts``** vor dem Fenstern — exakt wie
  :mod:`src.features.windows` (Sort-Stability-Bug, siehe
  ``reports/sort_stability_bug.md``). ``local_ts_ms`` hat Batch-Ties und
  taugt nicht zum Sortieren; es wird — wie in ``windows.py`` — nur als
  Zeitbasis fuer das Label-Closing benutzt.
* **Label-Closing** mit ``max_gap_ms=2500`` auf der Quell-Rate (geteilte
  Wahrheit via :func:`src.features.windows.smooth_labels`), dann
  Nearest-Sample-Mapping auf die 30-Hz-Achse, dann Fenster-Mehrheit.

Session-Auswahl wird aus :mod:`src.training.train_loso` wiederverwendet
(verdict-Filter, Pool-Profil) — kein Duplikat der Quality-Gates.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import resample_poly

from src.features.windows import smooth_labels
from src.training.train_loso import _profile_for_pool, _select_sessions

ROOT = Path(__file__).parents[3]
DATA_PROC = ROOT / "data" / "processed"

# --- Single source of truth fuer alle Magic Numbers ------------------------
TARGET_HZ = 30                                    # harnet-Eingangsrate
WIN_SEC = 5.0                                     # harnet-Fensterlaenge
STRIDE_SEC = 2.5                                  # 50 % Overlap (Konvention)
WIN_SAMPLES = int(round(WIN_SEC * TARGET_HZ))     # 150
STRIDE_SAMPLES = int(round(STRIDE_SEC * TARGET_HZ))  # 75
LABEL_THRESHOLD = 0.5                             # Fenster=1 iff >=50 % writing
MAX_GAP_MS = 2500.0                               # Label-Closing, wie ueberall
ACCEL_COLS = ("ax", "ay", "az")                   # userAcceleration (g), kein Gravity
# Quell-Rate (Hz) -> (up, down) fuer resample_poly auf 30 Hz.
RESAMPLE_FACTORS: dict[int, tuple[int, int]] = {50: (3, 5), 100: (3, 10)}
VALID_SOURCE_HZ: tuple[int, ...] = tuple(RESAMPLE_FACTORS)

N_CHANNELS = len(ACCEL_COLS)

# harnet-Varianten -> native Fensterlaenge @ 30 Hz. harnet5 erwartet exakt
# 150 Samples (5 s), harnet10 exakt 300 (10 s) — harnet10 crasht auf 150er
# Input. Stride = win_samples // 2 (50 %-Overlap-Konvention): harnet5 75
# (2,5 s, = Spec), harnet10 150 (5 s). Defaults von build_harnet_windows
# bleiben die harnet5-Werte, damit die 5-s-Spec-Entscheidung unangetastet ist.
HARNET_VARIANTS: dict[str, dict[str, int]] = {
    "harnet5": {"win_samples": WIN_SAMPLES, "stride_samples": STRIDE_SAMPLES},
    "harnet10": {"win_samples": WIN_SAMPLES * 2, "stride_samples": STRIDE_SAMPLES * 2},
}


def _empty_windows(win_samples: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.empty((0, N_CHANNELS, win_samples), dtype=np.float32),
        np.empty(0, dtype=np.int64),
        np.empty(0, dtype=np.float64),
    )


def detect_source_hz(ts_ms: np.ndarray) -> int:
    """Quell-Sample-Rate aus dem per-Sample ``ts`` (ms) ableiten.

    Median des |Δts| -> Rate, gesnappt auf die naechste gueltige Rate
    (50/100 Hz). ``ts`` (nicht ``local_ts_ms``) weil letzteres Batch-Ties
    hat (median dt = 0).
    """
    if len(ts_ms) < 2:
        raise ValueError("zu wenige Samples fuer Raten-Detektion")
    dt = float(np.median(np.abs(np.diff(np.sort(ts_ms)))))
    if dt <= 0:
        raise ValueError("ts hat keinen messbaren Sample-Abstand (alles Ties?)")
    fs = 1000.0 / dt
    nearest = min(VALID_SOURCE_HZ, key=lambda hz: abs(hz - fs))
    if abs(fs - nearest) / nearest > 0.2:
        raise ValueError(
            f"detektierte Rate {fs:.1f} Hz liegt ausserhalb ±20 % von "
            f"{VALID_SOURCE_HZ} — Quelle nicht zuordenbar"
        )
    return nearest


def build_harnet_windows(
    merged: pd.DataFrame,
    source_hz: int,
    win_samples: int = WIN_SAMPLES,
    stride_samples: int = STRIDE_SAMPLES,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Baue ``(N, 3, win_samples)``-harnet-Fenster aus einer watch-base merged-CSV.

    ``win_samples``/``stride_samples`` defaulten auf die harnet5-Werte
    (150 / 75 = 5 s / 2,5 s @ 30 Hz); harnet10 nutzt 300 / 150 (siehe
    :data:`HARNET_VARIANTS`).

    Returns ``(X, y, t_center_ms)``:
      * ``X``  — float32, Shape ``(n_windows, 3, win_samples)``, ax/ay/az in g
      * ``y``  — int64; 1 iff writing-Anteil (closed) >= ``LABEL_THRESHOLD``
      * ``t_center_ms`` — float64, Mittel-Zeitstempel je Fenster (Wall-Clock)

    Ablauf: stable-sort ``ts`` -> Label-Closing @2500 ms (auf Quell-Rate,
    Zeitbasis ``local_ts_ms`` wie windows.py) -> ``resample_poly`` auf 30 Hz
    -> Labels per Nearest-Sample auf die 30-Hz-Achse -> Fenster (Stride
    50 % Overlap), Fenster-Label per Mehrheit.
    """
    if source_hz not in RESAMPLE_FACTORS:
        raise ValueError(
            f"source_hz must be one of {VALID_SOURCE_HZ}, got {source_hz!r}"
        )
    needed = {*ACCEL_COLS, "label_writing", "local_ts_ms", "ts"}
    missing = needed - set(merged.columns)
    if missing:
        raise ValueError(f"merged CSV is missing columns: {sorted(missing)}")

    # Why: stable sort by per-sample `ts` — local_ts_ms hat Batch-Ties und
    # wuerde die Sample-Reihenfolge scrambeln (reports/sort_stability_bug.md).
    df = merged.dropna(subset=[*ACCEL_COLS, "label_writing", "ts", "local_ts_ms"])
    df = df.sort_values("ts", kind="stable")
    n_src = len(df)
    if n_src < 2:
        return _empty_windows(win_samples)

    accel_src = df.loc[:, list(ACCEL_COLS)].to_numpy(dtype=np.float64)  # (n_src, 3) in g
    raw_label = df["label_writing"].to_numpy(dtype=int)
    times_ms = df["local_ts_ms"].to_numpy(dtype=float)  # nur fuer Closing-Dauern
    ts_ms = df["ts"].to_numpy(dtype=float)              # Wall-Clock-Basis

    closed = smooth_labels(raw_label, times_ms, max_gap_ms=MAX_GAP_MS).astype(int)

    up, down = RESAMPLE_FACTORS[source_hz]
    accel_30 = resample_poly(accel_src, up, down, axis=0)  # (n_30, 3)
    n_30 = len(accel_30)
    if n_30 < win_samples:
        return _empty_windows(win_samples)

    # Labels per Nearest-Sample auf die 30-Hz-Achse mappen.
    new_idx = np.arange(n_30)
    src_idx = np.clip(
        np.round(new_idx * source_hz / TARGET_HZ).astype(int), 0, n_src - 1
    )
    label_30 = closed[src_idx]

    # Uniforme 30-Hz-Wall-Clock-Achse aus dem ersten ts.
    t0 = float(ts_ms[0])
    t_30 = t0 + new_idx * (1000.0 / TARGET_HZ)

    xs: list[np.ndarray] = []
    ys: list[int] = []
    tc: list[float] = []
    for start in range(0, n_30 - win_samples + 1, stride_samples):
        sl = slice(start, start + win_samples)
        xs.append(accel_30[sl].T)  # (3, win_samples) channels-first
        ys.append(int(label_30[sl].mean() >= LABEL_THRESHOLD))
        tc.append(float(t_30[sl].mean()))

    if not xs:
        return _empty_windows(win_samples)
    return (
        np.stack(xs).astype(np.float32),
        np.array(ys, dtype=np.int64),
        np.array(tc, dtype=np.float64),
    )


def load_session_harnet(
    session_id: str,
    merged_suffix: str | None = None,
    win_samples: int = WIN_SAMPLES,
    stride_samples: int = STRIDE_SAMPLES,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lese die (native) merged-CSV einer Session und baue harnet-Fenster.

    ``merged_suffix`` waehlt die Quelle (``None`` -> ``{sid}_merged.csv``).
    Die Quell-Rate wird aus ``ts`` detektiert; Modern-Sessions (100 Hz)
    werden so in *einem* Schritt 100->30 resampled statt ueber die
    50-Hz-Legacy-View (kein Doppel-Resampling). ``win_samples``/
    ``stride_samples`` siehe :func:`build_harnet_windows`.
    """
    stem = f"{session_id}_merged" + (f"_{merged_suffix}" if merged_suffix else "")
    merged_path = DATA_PROC / f"{stem}.csv"
    if not merged_path.exists():
        raise FileNotFoundError(
            f"{merged_path} fehlt — vorher `python -m src.merge {session_id}` laufen lassen."
        )
    merged = pd.read_csv(merged_path)
    if "ts" not in merged.columns:
        raise ValueError(
            f"{merged_path.name} hat keine 'ts'-Spalte — harnet braucht die "
            f"per-Sample-Uhr fuer Raten-Detektion und Stable-Sort."
        )
    source_hz = detect_source_hz(merged["ts"].to_numpy(dtype=float))
    return build_harnet_windows(merged, source_hz, win_samples, stride_samples)


def select_harnet_sessions(
    pool: str = "legacy", include_all: bool = False
) -> pd.DataFrame:
    """Session-Auswahl fuer den harnet-LOSO — wiederverwendet ``_select_sessions``.

    Identische verdict-/test-Gates wie der RF-/Deep-LOSO. ``pool='legacy'``
    -> Profil ``50hz`` (zieht die N=14-Kohorte inkl. der Modern-Sessions
    ueber ihre 50hz-Views als Auswahl-Kriterium; geladen wird je Session die
    native merged-CSV, siehe :func:`load_session_harnet`).
    """
    profile = _profile_for_pool(pool)
    return _select_sessions(include_all=include_all, min_windows=0, profile=profile)


def load_all_harnet_sessions(
    sessions: pd.DataFrame,
    win_samples: int = WIN_SAMPLES,
    stride_samples: int = STRIDE_SAMPLES,
) -> dict[str, dict]:
    """Lade alle Sessions als harnet-Fenster.

    Returns ``{session_id: {"X", "y", "t", "person_id"}}``; Sessions ohne
    Fenster werden uebersprungen.
    """
    out: dict[str, dict] = {}
    for row in sessions.itertuples():
        sid = row.session_id
        X, y, t = load_session_harnet(sid, None, win_samples, stride_samples)
        if len(X) == 0:
            print(f"  skip {sid} -- keine Fenster")
            continue
        out[sid] = {"X": X, "y": y, "t": t, "person_id": row.person_id}
    return out
