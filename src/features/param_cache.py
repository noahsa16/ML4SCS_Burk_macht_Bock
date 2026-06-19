"""Parametrisierter Window-Feature-Cache (Feature-Fenster + Label-Gap).

Feature-Fenster (``window_sec`` / ``stride_sec``) und das Label-Closing
(``max_gap_ms``) sind Feature-Build-Zeit-Parameter. Der kanonische Cache
``windows/{profile}/`` ist fix auf 1 s / 0.5 s / 2500 ms (die Headline) und
darf nicht überschrieben werden. Abweichende Kombinationen landen hier keyed
unter ``windows_param/{pool}/w{W}s{S}_g{GAP}/{session}_windows.csv`` — jede
Kombination in ihrem eigenen Ordner (keine gegenseitige Kollision), einmal
gebaut und danach wiederverwendet.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.features.gravity import GRAVITY_FEATURE_NAMES
from src.features.windows import build_windows

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"
PARAM_DIR = DATA_PROC / "windows_param"

# Kanonischer Default = der gecachte windows/{profile}/-Satz.
DEFAULT_WINDOW_SEC = 1.0
DEFAULT_STRIDE_SEC = 0.5
DEFAULT_MAX_GAP_MS = 2500.0


def is_default_params(window_sec: float, stride_sec: float,
                      max_gap_ms: float) -> bool:
    """True, wenn die Kombination dem kanonischen gecachten Satz entspricht."""
    return (window_sec == DEFAULT_WINDOW_SEC
            and stride_sec == DEFAULT_STRIDE_SEC
            and max_gap_ms == DEFAULT_MAX_GAP_MS)


def param_tag(window_sec: float, stride_sec: float, max_gap_ms: float) -> str:
    return f"w{window_sec:g}s{stride_sec:g}_g{int(round(max_gap_ms))}"


def param_windows_dir(pool: str, window_sec: float, stride_sec: float,
                      max_gap_ms: float) -> Path:
    return PARAM_DIR / pool / param_tag(window_sec, stride_sec, max_gap_ms)


def param_windows_path(session_id: str, pool: str, window_sec: float,
                       stride_sec: float, max_gap_ms: float) -> Path:
    return (param_windows_dir(pool, window_sec, stride_sec, max_gap_ms)
            / f"{session_id}_windows.csv")


def _merged_source(session_id: str, pool: str) -> Path:
    """Quell-merged-CSV je nach Pool (legacy bevorzugt die Downsample-View)."""
    if pool == "legacy":
        legacy = DATA_PROC / f"{session_id}_merged_legacy.csv"
        if legacy.exists():
            return legacy
    return DATA_PROC / f"{session_id}_merged.csv"


def ensure_param_windows(session_id: str, pool: str, window_sec: float,
                         stride_sec: float, max_gap_ms: float) -> Path:
    """Pfad zum Param-Window-Cache; baut ihn aus der merged-Quelle, falls er fehlt."""
    out = param_windows_path(session_id, pool, window_sec, stride_sec, max_gap_ms)
    if out.exists():
        return out
    merged = pd.read_csv(_merged_source(session_id, pool))
    w = build_windows(merged, window_sec=window_sec, stride_sec=stride_sec,
                      max_gap_ms=max_gap_ms)
    if pool == "legacy":
        # Why: Legacy-Pool ist 88 Features — eine evtl. Gravity tragende Quelle
        # hart auf den Legacy-Satz zwingen (Modern behält Gravity bewusst).
        w = w.drop(columns=[c for c in GRAVITY_FEATURE_NAMES if c in w.columns])
    w["session_id"] = session_id
    out.parent.mkdir(parents=True, exist_ok=True)
    w.to_csv(out, index=False)
    return out
