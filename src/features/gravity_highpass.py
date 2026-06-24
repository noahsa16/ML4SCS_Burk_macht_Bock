"""Komplementär-/High-Pass-Filter: trennt die langsam veränderliche Schwerkraft
von der rohen Gesamtbeschleunigung und approximiert CoreMotions userAcceleration.

    gravity_t = alpha * gravity_{t-1} + (1 - alpha) * raw_t
    user_t    = raw_t - gravity_t

Stateful (die laufende Gravity-Schätzung trägt über Aufrufe hinweg), damit der
Filter zum live-resumierbaren Swift-Port passt. alpha nahe 1 = träge Gravity.
Referenz für die Golden-Vektor-Parität (R-Axis/High-Pass).

By construction, the first output sample is [0, 0, 0] (gravity is seeded to raw[0],
so user_0 = raw_0 - raw_0 = 0). This is a parity contract for Swift port.
"""
from __future__ import annotations

import numpy as np


class GravityHighPass:
    def __init__(self, alpha: float = 0.9):
        self.alpha = float(alpha)
        self._gravity: np.ndarray | None = None

    @property
    def state(self) -> list | None:
        return None if self._gravity is None else self._gravity.tolist()

    def restore(self, state) -> None:
        self._gravity = None if state is None else np.asarray(state, dtype=float).copy()

    def reset(self) -> None:
        self._gravity = None

    def process(self, raw: np.ndarray) -> np.ndarray:
        raw = np.asarray(raw, dtype=float)
        out = np.empty_like(raw)
        g = self._gravity
        a = self.alpha
        for i in range(len(raw)):
            g = raw[i].copy() if g is None else a * g + (1.0 - a) * raw[i]
            out[i] = raw[i] - g
        self._gravity = g
        return out
