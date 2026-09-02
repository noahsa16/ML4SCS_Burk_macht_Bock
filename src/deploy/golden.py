"""Format der Golden-Vektoren: base64-kodierte float32-Bytes.

Base64 statt Dezimalzahlen, weil Python und Swift so exakt dieselben Bits
sehen — bei einer Paritaetspruefung mit Toleranz 1e-4 darf die Eingabe nicht
selbst schon eine Fehlerquelle sein.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures"

FIXTURES: dict[str, Path] = {
    "active": FIXTURE_DIR / "golden_windows_active.json",
    "passive": FIXTURE_DIR / "golden_windows_passive.json",
}


def encode_window(arr: np.ndarray) -> str:
    """(seq_len, n_channels) float32, row-major → base64."""
    a = np.ascontiguousarray(arr, dtype=np.float32)
    return base64.b64encode(a.tobytes()).decode("ascii")


def decode_window(b64: str, seq_len: int, n_channels: int) -> np.ndarray:
    raw = base64.b64decode(b64)
    return np.frombuffer(raw, dtype=np.float32).reshape(seq_len, n_channels).copy()


def load_fixture(kind: str) -> dict:
    return json.loads(FIXTURES[kind].read_text())
