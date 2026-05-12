"""Sliding-Window-Features auf der watch-base gemergten CSV.

Pipeline-Schritt 3:
    raw  →  alignment  →  merge  →  [features]  →  (train)

Liest ``data/processed/{session}_merged.csv`` (Output von
``python -m src.merge``), baut überlappende Fenster über den 50 Hz
Watch-Stream und berechnet pro Achse + Magnitude statistische Features.

Output: 1 Zeile pro Fenster (42 Features + ``label`` + ``t_center_ms``).
``t_center_ms`` erlaubt einen temporalen Train/Test-Split downstream.

CLI
---
::

    python -m src.features              # neueste Session
    python -m src.features S029         # spezifische Session

Schreibt nach ``data/processed/{session}_windows.csv``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

ACC_COLS = ["ax", "ay", "az"]
GYRO_COLS = ["rx", "ry", "rz"]
IMU_COLS = ACC_COLS + GYRO_COLS

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"

_MERGED_RE = re.compile(r"^(S\d+)_merged\.csv$")


def smooth_labels(
    label: np.ndarray,
    t_ms: np.ndarray,
    max_gap_ms: float = 300.0,
    max_spike_ms: float = 0.0,
) -> np.ndarray:
    """Morphologisches Glätten der binären Schreib-Label-Sequenz.

    * ``max_gap_ms``: alle ``idle``-Runs ≤ dieser Dauer, die von ``writing``
      umgeben sind, werden zu ``writing`` (Closing). Default 300 ms fängt
      Pen-Lift-Artefakte zwischen Buchstaben + kurze Wort-Übergänge.
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


def _window_features(window: np.ndarray) -> dict[str, float]:
    """Per-axis stats + magnitude features for a (N, 6) IMU window."""
    feats: dict[str, float] = {}
    for i, name in enumerate(IMU_COLS):
        x = window[:, i]
        feats[f"{name}_mean"] = float(np.mean(x))
        feats[f"{name}_std"] = float(np.std(x))
        feats[f"{name}_min"] = float(np.min(x))
        feats[f"{name}_max"] = float(np.max(x))
        feats[f"{name}_rms"] = float(np.sqrt(np.mean(x * x)))
        feats[f"{name}_range"] = feats[f"{name}_max"] - feats[f"{name}_min"]

    acc_mag = np.linalg.norm(window[:, 0:3], axis=1)
    gyro_mag = np.linalg.norm(window[:, 3:6], axis=1)
    feats["acc_mag_mean"] = float(np.mean(acc_mag))
    feats["acc_mag_std"] = float(np.std(acc_mag))
    feats["acc_mag_energy"] = float(np.mean(acc_mag * acc_mag))
    feats["gyro_mag_mean"] = float(np.mean(gyro_mag))
    feats["gyro_mag_std"] = float(np.std(gyro_mag))
    feats["gyro_mag_energy"] = float(np.mean(gyro_mag * gyro_mag))
    return feats


def build_windows(
    merged: pd.DataFrame,
    window_sec: float = 1.0,
    stride_sec: float = 0.5,
    fs_hz: float = 50.0,
    min_label_ratio: float = 0.6,
    max_gap_ms: float = 300.0,
    max_spike_ms: float = 0.0,
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

    df = merged.dropna(subset=[*IMU_COLS, "local_ts_ms"]).sort_values("local_ts_ms")
    if df.empty:
        return pd.DataFrame()

    win = int(round(window_sec * fs_hz))
    stride = int(round(stride_sec * fs_hz))
    if win <= 1 or stride < 1:
        raise ValueError("window/stride too small")

    imu = df[IMU_COLS].to_numpy(dtype=float)
    raw_labels = df["label_writing"].to_numpy(dtype=int)
    times = df["local_ts_ms"].to_numpy(dtype=float)
    labels = smooth_labels(
        raw_labels, times, max_gap_ms=max_gap_ms, max_spike_ms=max_spike_ms,
    ).astype(float)

    rows: list[dict[str, float]] = []
    for start in range(0, len(df) - win + 1, stride):
        end = start + win
        feats = _window_features(imu[start:end])
        feats["label"] = int(labels[start:end].mean() >= min_label_ratio)
        feats["t_center_ms"] = float(times[start:end].mean())
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
        "--max-gap-ms", type=float, default=300.0,
        help="Idle-Lücken ≤ X ms zwischen Schreib-Runs werden zu Schreiben (Closing). 0 = aus.",
    )
    parser.add_argument(
        "--max-spike-ms", type=float, default=0.0,
        help="Schreib-Spitzen ≤ X ms zwischen Idle-Runs werden zu Idle (Opening). 0 = aus.",
    )
    parser.add_argument("--out", type=Path, help="Ausgabepfad (default: data/processed/{session}_windows.csv)")
    args = parser.parse_args()

    sid = args.session or _latest_session()
    feats = load_session_windows(
        sid,
        window_sec=args.window_sec,
        stride_sec=args.stride_sec,
        max_gap_ms=args.max_gap_ms,
        max_spike_ms=args.max_spike_ms,
    )
    if feats.empty:
        raise SystemExit(f"Keine Windows für {sid} — prüfe die merged CSV.")

    out = args.out or (DATA_PROC / f"{sid}_windows.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    feats.to_csv(out, index=False)
    counts = feats["label"].value_counts().to_dict()
    print(
        f"Session {sid}: {len(feats)} Fenster | "
        f"writing={counts.get(1, 0)}, idle={counts.get(0, 0)} | "
        f"Features: {len(feats.columns) - 2}"
    )
    print(f"Gespeichert: {out}")


if __name__ == "__main__":
    main()
