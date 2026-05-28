"""Within-Subject 100-Hz-A/B mit dem 1D-CNN.

Spiegel von ``within_noah_100hz.py`` (RF) -- gleiche Sessions, gleiches
Setup, aber das CNN1D als Modell. Antwortet: bringt 100 Hz dem Sequenz-
Modell etwas, was der RF aus den 88 Features nicht zieht?

seq_len=100, stride=50 -> 1s Fenster / 0.5s Stride bei 100 Hz (gleiche
Zeit-Semantik wie die 50-Hz-Baseline mit seq_len=50/stride=25).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.deep.data import load_session_raw  # noqa: E402
from src.training.deep.models import CNN1D  # noqa: E402
from src.training.deep.train_loso import (  # noqa: E402
    _set_seed, DEVICE, predict_proba, fold_metrics,
)


def train_fixed_epochs(model, X, y, epochs=25, batch_size=64, lr=1e-3):
    """Sauberes Festepochen-Training -- keine Val-Spaehung."""
    model = model.to(DEVICE)
    n_pos = float((y == 1).sum())
    n_neg = float((y == 0).sum())
    pos_weight = torch.tensor([n_neg / max(n_pos, 1.0)], device=DEVICE)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(y.astype(np.float32)))
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=True)
    for _ in range(epochs):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            loss_fn(model(xb), yb).backward()
            opt.step()
    return model


SEQ_LEN = 100   # 1.0 s @ 100 Hz
STRIDE = 50     # 0.5 s @ 100 Hz
MAX_GAP_MS = 2500.0


def _load(sid: str):
    X, y, t = load_session_raw(
        sid, seq_len=SEQ_LEN, stride=STRIDE, max_gap_ms=MAX_GAP_MS,
    )
    return X, y, t


def _holdout_split(X, y, t, frac: float = 0.2):
    """Take last `frac` (zeitlich, nach t_center_ms) als Val-Set fuer Early Stop."""
    order = np.argsort(t)
    X, y, t = X[order], y[order], t[order]
    n = len(X)
    cut = int(n * (1 - frac))
    return X[:cut], y[:cut], t[:cut], X[cut:], y[cut:], t[cut:]


def _report(name: str, proba, y_true, t):
    df = pd.DataFrame({"session_id": ["test"] * len(t), "t_center_ms": t})
    m = fold_metrics(proba, y_true, df)
    print(f"\n=== {name} ===")
    print(f"  acc {m['accuracy']:.3f}   F1(w) {m['f1_writing']:.3f}   AUC {m['roc_auc']:.3f}")
    print(f"  burst AUC @1s/5s/10s/30s: "
          + "  ".join(f"{m['bursts'][k]['roc_auc']:.3f}" for k in m['bursts']))


def run_one_direction(train_sid: str, test_sid: str, epochs: int = 30) -> None:
    _set_seed(42)
    Xtr, ytr, ttr = _load(train_sid)
    Xte, yte, tte = _load(test_sid)
    print(f"\n[{train_sid} -> {test_sid}]  train: {len(Xtr)} fen / "
          f"test: {len(Xte)} fen   (seq_len={SEQ_LEN}, stride={STRIDE})")

    model = train_fixed_epochs(CNN1D(), Xtr, ytr, epochs=epochs)
    print(f"  trained {epochs} epochs (no early-stop, no val-peek)")

    proba = predict_proba(model, Xte)
    _report(f"CNN  Train {train_sid} -> Test {test_sid}", proba, yte, tte)


run_one_direction("S032", "S033")
run_one_direction("S033", "S032")
