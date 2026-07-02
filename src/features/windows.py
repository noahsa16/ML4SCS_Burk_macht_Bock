"""Sliding-Window-Features auf der watch-base gemergten CSV.

Pipeline-Schritt 3:
    raw  →  alignment  →  merge  →  [features]  →  (train)

Liest ``data/processed/{session}_merged.csv`` (Output von
``python -m src.merge``), baut überlappende Fenster über den 50 Hz
Watch-Stream und berechnet pro Achse + Magnitude statistische Features.

Output: 1 Zeile pro Fenster (88 Features + ``label`` + ``t_center_ms``).
``t_center_ms`` erlaubt einen temporalen Train/Test-Split downstream.

CLI
---
::

    python -m src.features              # neueste Session
    python -m src.features S029         # spezifische Session

Schreibt nach ``data/processed/windows/{profil}/{session}_windows.csv``
(Profil inhalts-abgeleitet, siehe :mod:`src.profiles`).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.gravity import _gravity_window_features
from src.features.rhythm import rhythm_window_features
from src.features.tsfresh_winners import tsfresh_winner_features

ACC_COLS = ["ax", "ay", "az"]
GYRO_COLS = ["rx", "ry", "rz"]
IMU_COLS = ACC_COLS + GYRO_COLS

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"

_MERGED_RE = re.compile(r"^(S\d+)_merged\.csv$")


def infer_fs_hz(merged: pd.DataFrame, fallback: float = 50.0) -> float:
    # Why: 100-Hz-Streaming kam nach dem Original-50-Hz-Default; ohne
    # Auto-Detection rechnen wir bei 100-Hz-Sessions Fenster/FFT/Jerk falsch
    # (Befund aus S032-100-Hz-Selbsttest 2026-05-24).
    # Watch sendet in Batches -> viele Samples teilen local_ts_ms, deshalb
    # NICHT median(diff): nimm den globalen Mittelwert ueber die Spanne.
    # Why: ts (per-Sample-Capture-Uhr) bevorzugen — local_ts_ms ist bei
    # Spill-Drain-Strecken Minuten verspätet und verzerrt die Spanne.
    t_col = "ts" if "ts" in merged.columns else "local_ts_ms"
    if t_col not in merged.columns or len(merged) < 2:
        return fallback
    t = pd.to_numeric(merged[t_col], errors="coerce").dropna().to_numpy(dtype=float)
    if len(t) < 2:
        return fallback
    span_ms = float(t.max() - t.min())
    if span_ms <= 0:
        return fallback
    return float((len(t) - 1) * 1000.0 / span_ms)


def smooth_labels(
    label: np.ndarray,
    t_ms: np.ndarray,
    max_gap_ms: float = 2500.0,
    max_spike_ms: float = 0.0,
) -> np.ndarray:
    """Morphologisches Glätten der binären Schreib-Label-Sequenz.

    * ``max_gap_ms``: alle ``idle``-Runs ≤ dieser Dauer, die von ``writing``
      umgeben sind, werden zu ``writing`` (Closing). Default 2500 ms =
      Schreibmodus-Semantik (Mikropausen ≤ 2.5 s zählen als Schreiben).
    * ``max_spike_ms``: alle ``writing``-Runs ≤ dieser Dauer, die von
      ``idle`` umgeben sind, werden zu ``idle`` (Opening). Default 0 =
      kein Spike-Removal.
    * Runs am Anfang/Ende werden nicht angetastet (kein Kontext auf einer
      Seite, könnte echte Idle-Phase abschneiden).
    """
    if len(label) == 0:
        return label.copy()
    out = label.astype(int).copy()

    # Runs sammeln: alternierend, also reicht ein einfacher Pass.
    runs: list[tuple[int, int, int]] = []
    cur_start = 0
    for i in range(1, len(out)):
        if out[i] != out[cur_start]:
            runs.append((cur_start, i, int(out[cur_start])))
            cur_start = i
    runs.append((cur_start, len(out), int(out[cur_start])))

    for idx, (s, e, v) in enumerate(runs):
        if idx == 0 or idx == len(runs) - 1:
            continue
        duration_ms = float(t_ms[e - 1] - t_ms[s])
        if v == 0 and max_gap_ms > 0 and duration_ms <= max_gap_ms:
            out[s:e] = 1
        elif v == 1 and max_spike_ms > 0 and duration_ms <= max_spike_ms:
            out[s:e] = 0
    return out


def _spectral_features(x: np.ndarray, fs: float) -> tuple[float, float, float, float]:
    """Dominant freq, spectral centroid, spectral entropy, 3–8 Hz band ratio.

    DC-Bin wird entfernt (Mean abziehen + rfft[1:]), damit ein konstanter
    Offset nicht Centroid/Entropy verfälscht. Bei stiller Hand kollabiert
    das Spektrum auf Rauschen → alle Returns gehen sauber gegen 0.
    """
    n = len(x)
    if n < 4:
        return 0.0, 0.0, 0.0, 0.0
    x = x - np.mean(x)
    spec = np.abs(np.fft.rfft(x))
    psd = spec * spec
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    psd = psd[1:]
    freqs = freqs[1:]
    total = float(psd.sum())
    if total <= 1e-20:
        return 0.0, 0.0, 0.0, 0.0
    pn = psd / total
    dom = float(freqs[int(np.argmax(psd))])
    centroid = float(np.sum(freqs * pn))
    entropy = float(-np.sum(pn * np.log(pn + 1e-12)))
    band_mask = (freqs >= 3.0) & (freqs <= 8.0)
    band_ratio = float(psd[band_mask].sum() / total)
    return dom, centroid, entropy, band_ratio


def _zero_crossing_rate(x: np.ndarray) -> float:
    """Fraction of sign changes after mean-centering. Robuster Frequenz-Proxy."""
    if len(x) < 2:
        return 0.0
    xc = x - np.mean(x)
    signs = np.sign(xc)
    signs[signs == 0] = 1
    return float(np.mean(np.diff(signs) != 0))


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    sa, sb = np.std(a), np.std(b)
    if sa < 1e-12 or sb < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _window_features(window: np.ndarray, fs_hz: float,
                     rhythm: bool = False,
                     hard_negative_feats: bool = False,
                     tsfresh_winners: bool = False) -> dict[str, float]:
    """Per-axis stats + magnitude + spectral + jerk + correlation features.

    Layout for one (N, 6) IMU window (axes: ax, ay, az, rx, ry, rz):
      * 6 axes × 6 zeitliche Stats (mean/std/min/max/rms/range) = 36
      * 6 axes × 4 Spektral-Features (dom_freq, centroid, entropy, band_3_8) = 24
      * 6 axes × ZCR = 6
      * 3 accel axes × 2 Jerk-Stats (std, mean_abs) = 6
      * accel/gyro Magnitude: mean/std/energy + jerk std + jerk mean_abs = 10
      * 6 Cross-Achsen-Korrelationen (accel-pairs + gyro-pairs) = 6
      = 88 Features
    """
    feats: dict[str, float] = {}
    for i, name in enumerate(IMU_COLS):
        x = window[:, i]
        feats[f"{name}_mean"] = float(np.mean(x))
        feats[f"{name}_std"] = float(np.std(x))
        feats[f"{name}_min"] = float(np.min(x))
        feats[f"{name}_max"] = float(np.max(x))
        feats[f"{name}_rms"] = float(np.sqrt(np.mean(x * x)))
        feats[f"{name}_range"] = feats[f"{name}_max"] - feats[f"{name}_min"]

        dom, cent, ent, band = _spectral_features(x, fs_hz)
        feats[f"{name}_dom_freq"] = dom
        feats[f"{name}_spec_centroid"] = cent
        feats[f"{name}_spec_entropy"] = ent
        feats[f"{name}_band_3_8"] = band

        feats[f"{name}_zcr"] = _zero_crossing_rate(x)

    # Jerk = d(accel)/dt; multipliziert mit fs_hz, damit Einheit g/s ist
    # und Features fs-skalierungs-invariant bleiben.
    for i, name in enumerate(ACC_COLS):
        dx = np.diff(window[:, i]) * fs_hz
        feats[f"{name}_jerk_std"] = float(np.std(dx)) if len(dx) else 0.0
        feats[f"{name}_jerk_mean_abs"] = float(np.mean(np.abs(dx))) if len(dx) else 0.0

    acc_mag = np.linalg.norm(window[:, 0:3], axis=1)
    gyro_mag = np.linalg.norm(window[:, 3:6], axis=1)
    feats["acc_mag_mean"] = float(np.mean(acc_mag))
    feats["acc_mag_std"] = float(np.std(acc_mag))
    feats["acc_mag_energy"] = float(np.mean(acc_mag * acc_mag))
    feats["gyro_mag_mean"] = float(np.mean(gyro_mag))
    feats["gyro_mag_std"] = float(np.std(gyro_mag))
    feats["gyro_mag_energy"] = float(np.mean(gyro_mag * gyro_mag))

    acc_mag_jerk = np.diff(acc_mag) * fs_hz
    gyro_mag_jerk = np.diff(gyro_mag) * fs_hz
    feats["acc_mag_jerk_std"] = float(np.std(acc_mag_jerk)) if len(acc_mag_jerk) else 0.0
    feats["acc_mag_jerk_mean_abs"] = float(np.mean(np.abs(acc_mag_jerk))) if len(acc_mag_jerk) else 0.0
    feats["gyro_mag_jerk_std"] = float(np.std(gyro_mag_jerk)) if len(gyro_mag_jerk) else 0.0
    feats["gyro_mag_jerk_mean_abs"] = float(np.mean(np.abs(gyro_mag_jerk))) if len(gyro_mag_jerk) else 0.0

    ax, ay, az = window[:, 0], window[:, 1], window[:, 2]
    rx, ry, rz = window[:, 3], window[:, 4], window[:, 5]
    feats["corr_ax_ay"] = _safe_corr(ax, ay)
    feats["corr_ax_az"] = _safe_corr(ax, az)
    feats["corr_ay_az"] = _safe_corr(ay, az)
    feats["corr_rx_ry"] = _safe_corr(rx, ry)
    feats["corr_rx_rz"] = _safe_corr(rx, rz)
    feats["corr_ry_rz"] = _safe_corr(ry, rz)

    # Opt-in: 4 Rhythmus-/Periodizitäts-Features (Tipp-vs-Schreib-Trennung).
    # Default aus → kanonischer 88-Vektor bit-identisch.
    if rhythm:
        feats.update(rhythm_window_features(acc_mag, gyro_mag, fs_hz))

    # Opt-in: 10 Features gegen die keyboard/phone-Verwechslung (SHAP-Diff
    # 2026-07-01, reports/shap_hard_negative_diff.md). rx_band_3_8 und
    # gyro_mag_jerk_mean_abs trennen P17s Tippen von Schreiben schon korrekt,
    # werden aber von den lauten Accel-Jerk-Features ueberstimmt. Verschaerft
    # beide Signale statt sie zu duplizieren: Jerk pro Gyro-Achse (bisher nur
    # Magnitude) + Accel-Rotations-Kopplung verankert an rx (die eine Achse,
    # die im SHAP-Diff schon informativ war — nicht alle 9 Accel×Gyro-Paare,
    # um die Feature-Zahl bei N=20 nicht unnoetig aufzublaehen).
    if hard_negative_feats:
        for i, name in zip((3, 4, 5), GYRO_COLS):
            dx = np.diff(window[:, i]) * fs_hz
            feats[f"{name}_jerk_std"] = float(np.std(dx)) if len(dx) else 0.0
            feats[f"{name}_jerk_mean_abs"] = float(np.mean(np.abs(dx))) if len(dx) else 0.0
        feats["corr_ax_rx"] = _safe_corr(ax, rx)
        feats["corr_ay_rx"] = _safe_corr(ay, rx)
        feats["corr_az_rx"] = _safe_corr(az, rx)
        # Ratio auf den ROHEN, nicht-negativen Groessen (band-ratio in [0,1],
        # jerk mean_abs >= 0) -- NICHT auf bereits z-gescorten Werten (die
        # koennen negativ sein, was die Ratio unsinnig macht). Z-Score der
        # Ratio selbst passiert wie bei jedem anderen Feature stromabwaerts
        # in _zscore_per_session().
        feats["rx_ay_ratio"] = feats["rx_band_3_8"] / (feats["ay_jerk_mean_abs"] + 1e-3)

    # Opt-in: 42 destillierte tsfresh-Winner (per-Achse-Autokorr@Lags,
    # Quantile, change_quantiles, CID) — die volle tsfresh-Bank schlug die
    # 88 gepaart signifikant (2026-07-02, siehe src/features/tsfresh_winners.py).
    if tsfresh_winners:
        feats.update(tsfresh_winner_features(window))
    return feats


def build_windows(
    merged: pd.DataFrame,
    window_sec: float = 1.0,
    stride_sec: float = 0.5,
    fs_hz: float | None = None,
    min_label_ratio: float = 0.6,
    max_gap_ms: float = 2500.0,
    max_spike_ms: float = 0.0,
    rhythm: bool = False,
    hard_negative_feats: bool = False,
    tsfresh_winners: bool = False,
) -> pd.DataFrame:
    """Build feature rows from a watch-base merged DataFrame.

    Sample-level labels werden vor dem Windowing geglättet
    (siehe :func:`smooth_labels`) — der Merge bleibt unverändert,
    das Closing ist eine Feature-Engineering-Entscheidung.

    Each window is labelled 1 only if the writing-fraction inside the window
    is ≥ ``min_label_ratio``, else 0. The deadband prevents mostly-idle windows
    from being called "writing" because of a single stray PEN_MOVE row.
    """
    needed = {*IMU_COLS, "label_writing", "local_ts_ms"}
    missing = needed - set(merged.columns)
    if missing:
        raise ValueError(f"merged CSV is missing columns: {sorted(missing)}")

    # Why: ts is the watch's per-sample monotonic clock. local_ts_ms is the
    # server's batch-receive time -> 10+ samples share it, and an unstable
    # sort scrambles within-batch ordering, which breaks every order-sensitive
    # feature (FFT, jerk, ZCR, correlations). Sorting by ts gives globally
    # monotonic per-sample order, matching what live inference sees.
    sort_col = "ts" if "ts" in merged.columns else "local_ts_ms"
    df = merged.dropna(subset=[*IMU_COLS, sort_col]).sort_values(sort_col, kind="stable")
    if df.empty:
        return pd.DataFrame()

    if fs_hz is None:
        fs_hz = infer_fs_hz(df)

    win = int(round(window_sec * fs_hz))
    stride = int(round(stride_sec * fs_hz))
    if win <= 1 or stride < 1:
        raise ValueError("window/stride too small")

    imu = df[IMU_COLS].to_numpy(dtype=float)
    raw_labels = df["label_writing"].to_numpy(dtype=int)
    # Why: Label-Closing (Gap-Messung) und t_center_ms auf der Capture-Uhr
    # rechnen — local_ts_ms (Batch-Ankunft) verortet Spill-Strecken Minuten
    # falsch und misst Gaps in Ankunfts- statt Ereigniszeit.
    times = pd.to_numeric(df[sort_col], errors="coerce").to_numpy(dtype=float)
    labels = smooth_labels(
        raw_labels, times, max_gap_ms=max_gap_ms, max_spike_ms=max_spike_ms,
    ).astype(float)

    # Modern-Pool: gx/gy/gz vorhanden → 6 zusätzliche gravity-Features
    # pro Window. has_gravity verlangt alle drei Achsen vorhanden UND
    # *jedes* Sample non-NaN. Why: per-window NaN-Imputation würde sonst
    # heterogene Feature-Verteilung pro Session erzeugen (manche Fenster
    # haben gravity, manche NaN) — sauberer ist binäre Pool-Klassifikation
    # auf Session-Ebene. Sessions mit auch nur einem NaN-gravity-Sample
    # zählen als Legacy.
    grav_cols = ("gx", "gy", "gz")
    has_gravity = (
        set(grav_cols).issubset(df.columns)
        and not df[list(grav_cols)].isna().any().any()
    )
    grav_arr = df[list(grav_cols)].to_numpy(dtype=float) if has_gravity else None

    has_task_id = "task_id" in df.columns
    has_task_cat = "task_category" in df.columns
    task_ids = df["task_id"].to_numpy() if has_task_id else None
    task_cats = df["task_category"].to_numpy() if has_task_cat else None

    rows: list[dict[str, float]] = []
    for start in range(0, len(df) - win + 1, stride):
        end = start + win
        feats = _window_features(imu[start:end], fs_hz=fs_hz, rhythm=rhythm,
                                  hard_negative_feats=hard_negative_feats,
                                  tsfresh_winners=tsfresh_winners)
        feats["label"] = int(labels[start:end].mean() >= min_label_ratio)
        feats["t_center_ms"] = float(times[start:end].mean())
        if has_gravity:
            grav_df = pd.DataFrame(
                grav_arr[start:end], columns=list(grav_cols),
            )
            feats.update(_gravity_window_features(grav_df))
        # Task metadata propagated from merged CSV when markers attached.
        # Window-level value = mode of sample-level task_id over the window.
        # If the merged DF has no task_id (legacy session), the column is
        # silently absent from the output — keeps the schema clean.
        if has_task_id:
            tid_series = pd.Series(task_ids[start:end]).dropna()
            if not tid_series.empty:
                feats["task_id"] = tid_series.mode().iat[0]
                if has_task_cat:
                    cat_series = pd.Series(task_cats[start:end]).dropna()
                    if not cat_series.empty:
                        feats["task_category"] = cat_series.mode().iat[0]
        rows.append(feats)

    return pd.DataFrame(rows)


def load_session_windows(session_id: str, **kwargs) -> pd.DataFrame:
    """Read ``{session}_merged.csv`` and build windows in one go."""
    merged_path = DATA_PROC / f"{session_id}_merged.csv"
    if not merged_path.exists():
        raise FileNotFoundError(
            f"{merged_path} fehlt — vorher `python -m src.merge {session_id}` laufen lassen."
        )
    merged = pd.read_csv(merged_path)
    return build_windows(merged, **kwargs)


def _latest_session() -> str:
    sessions = sorted(
        m.group(1)
        for p in DATA_PROC.glob("S*_merged.csv")
        if (m := _MERGED_RE.match(p.name))
    )
    if not sessions:
        raise SystemExit(
            "Keine S###_merged.csv unter data/processed/ — "
            "vorher `python -m src.merge` laufen lassen."
        )
    return sessions[-1]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.features")
    parser.add_argument("session", nargs="?", help="z. B. S029 — default: neueste merged Session")
    parser.add_argument("--window-sec", type=float, default=1.0)
    parser.add_argument("--stride-sec", type=float, default=0.5)
    parser.add_argument(
        "--max-gap-ms", type=float, default=2500.0,
        help="Idle-Lücken ≤ X ms zwischen Schreib-Runs werden zu Schreiben (Closing). 0 = aus.",
    )
    parser.add_argument(
        "--max-spike-ms", type=float, default=0.0,
        help="Schreib-Spitzen ≤ X ms zwischen Idle-Runs werden zu Idle (Opening). 0 = aus.",
    )
    parser.add_argument(
        "--fs-hz", type=float, default=None,
        help="Sample-Rate (Hz). Default: aus local_ts_ms abgeleitet.",
    )
    parser.add_argument(
        "--merged-suffix", default=None,
        help="Alternative merged-CSV lesen, z. B. 'legacy' → "
        "{session}_merged_legacy.csv (Output der Downsample-Bridge). "
        "Der Zielordner unter windows/ folgt immer dem Inhalt.",
    )
    parser.add_argument("--out", type=Path, help="Ausgabepfad (default: data/processed/windows/{profil}/{session}_windows.csv)")
    args = parser.parse_args()

    sid = args.session or _latest_session()
    suffix = f"_{args.merged_suffix}" if args.merged_suffix else ""
    merged_path = DATA_PROC / f"{sid}_merged{suffix}.csv"
    if not merged_path.exists():
        raise SystemExit(
            f"{merged_path} fehlt — vorher `python -m src.merge {sid}"
            + (f" --watch-suffix {args.merged_suffix}" if args.merged_suffix else "")
            + "` laufen lassen."
        )
    merged = pd.read_csv(merged_path)
    feats = build_windows(
        merged,
        window_sec=args.window_sec,
        stride_sec=args.stride_sec,
        fs_hz=args.fs_hz,
        max_gap_ms=args.max_gap_ms,
        max_spike_ms=args.max_spike_ms,
    )
    if feats.empty:
        raise SystemExit(f"Keine Windows für {sid} — prüfe die merged CSV.")

    # Why: der Ordner lügt nie — Profil wird aus dem tatsächlich
    # geschriebenen Artefakt abgeleitet (Gravity-Features im Output +
    # gemessene Rate), nicht aus einem manuell gesetzten Flag.
    from src import profiles
    from src.features.gravity import GRAVITY_FEATURE_NAMES
    has_grav = set(GRAVITY_FEATURE_NAMES).issubset(feats.columns)
    fs = args.fs_hz or infer_fs_hz(merged)
    out = args.out or profiles.windows_path(sid, profiles.profile_for(fs, has_grav))
    out.parent.mkdir(parents=True, exist_ok=True)
    feats.to_csv(out, index=False)
    counts = feats["label"].value_counts().to_dict()
    # Why: label/t_center_ms sind immer Metadaten; task_id/task_category nur
    # bei Study-Sessions mit angehaengten Markern. Nur die tatsaechlich
    # vorhandenen Metadaten-Spalten abziehen -> echte Feature-Zahl (88 Legacy
    # / 92 Modern), nicht ein um die Task-Spalten ueberhoehter Count.
    _META_COLS = {"label", "t_center_ms", "task_id", "task_category"}
    n_features = len(feats.columns) - len(_META_COLS & set(feats.columns))
    print(
        f"Session {sid}: {len(feats)} Fenster | "
        f"writing={counts.get(1, 0)}, idle={counts.get(0, 0)} | "
        f"Features: {n_features}"
    )
    print(f"Gespeichert: {out}")


if __name__ == "__main__":
    main()
