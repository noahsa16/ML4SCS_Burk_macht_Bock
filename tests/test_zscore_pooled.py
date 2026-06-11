"""Leak-freie pooled Z-Score-Normalisierung (deploy-repräsentativ).

Per-Session-Z-Score normiert die Test-Session mit ihrer EIGENEN (auch
zukünftigen) Statistik — nicht-kausal, nicht live-deploybar. Die ehrliche
Variante fittet μ/σ auf den Trainings-Folds und wendet sie auf den Held-out
an (genau was rf_all_live einbäckt). Test: kein Test-Stat-Leak.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.training.train_loso import _zscore_train_pooled


def _df(sid: str, vals: list[float]) -> pd.DataFrame:
    n = len(vals)
    return pd.DataFrame({
        "session_id": [sid] * n,
        "f": vals,
        "label": [0, 1, 0][:n] + [0] * max(0, n - 3),
        "t_center_ms": np.arange(n, dtype=float) * 500,
    })


def test_pooled_uses_train_stats_not_test_stats():
    # Train centered at 10 (μ=10, σ=1), test centered at 20.
    train = _df("A", [9.0, 10.0, 11.0])
    test = _df("B", [19.0, 20.0, 21.0])
    tr, te = _zscore_train_pooled(train, test, ["f"])
    # Train standardised to ~0 mean:
    assert abs(tr["f"].mean()) < 1e-9
    # Test was normed with TRAIN μ=10/σ=1 -> stays shifted (~+10), NOT centered.
    # If it had (wrongly) used its own stats it would be ~0. Proof: no leak.
    assert te["f"].mean() > 5.0


def test_pooled_does_not_mutate_inputs():
    train = _df("A", [1.0, 2.0, 3.0])
    test = _df("B", [4.0, 5.0, 6.0])
    train_before = train["f"].tolist()
    _zscore_train_pooled(train, test, ["f"])
    assert train["f"].tolist() == train_before  # originals untouched
