"""Smoke-Tests fuer den Fine-Tuning-Loop (modell-agnostisch, kein Download)."""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from src.training.deep.harnet_finetune import (
    _class_weights,
    finetune_model,
    predict_proba,
)


class _Tiny(nn.Module):
    """Winziges (b,3,L)->(b,2)-Netz, um den Loop ohne harnet-Download zu testen."""

    def __init__(self, seq_len: int) -> None:
        super().__init__()
        self.fc = nn.Linear(3 * seq_len, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(x.flatten(1))


def test_class_weights_balanced():
    # 3 neg, 1 pos -> w0 = 4/(2*3), w1 = 4/(2*1) = 2.0
    w = _class_weights(np.array([0, 0, 0, 1])).cpu().numpy()
    assert np.isclose(w[0], 4 / 6)
    assert np.isclose(w[1], 2.0)


def test_finetune_model_runs_and_predicts():
    """Lernbares Muster, wenige Epochen — nur Smoke, kein Metrik-Ziel."""
    rng = np.random.default_rng(2)
    seq_len = 10

    def mk(n: int, scale: float) -> np.ndarray:
        return rng.normal(scale=scale, size=(n, 3, seq_len)).astype(np.float32)

    X = np.concatenate([mk(32, 0.2), mk(32, 2.0)])
    y = np.concatenate([np.zeros(32), np.ones(32)]).astype(np.int64)
    Xv = np.concatenate([mk(8, 0.2), mk(8, 2.0)])
    yv = np.concatenate([np.zeros(8), np.ones(8)]).astype(np.int64)

    model, best_epoch = finetune_model(
        _Tiny(seq_len), X, y, Xv, yv, max_epochs=3, patience=3, batch_size=16
    )
    assert isinstance(best_epoch, int)
    assert -1 <= best_epoch <= 2
    proba = predict_proba(model, Xv)
    assert proba.shape == (16,)
    assert np.all((proba >= 0.0) & (proba <= 1.0))
