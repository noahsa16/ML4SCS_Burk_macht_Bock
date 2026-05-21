"""LOSO-Cross-Validation fuer die Deep-Sequenz-Modelle.

Spiegelt :mod:`src.training.train_loso` (RF-Headline): identische
Session-Auswahl und identische Burst-Aggregation, damit der Vergleich
fair ist. Statt eines RF wird pro Fold ein Torch-Modell mit Early
Stopping auf einem Person-Holdout trainiert.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score, roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

from src.training.deep.data import load_session_raw
from src.training.deep.models import MODELS
from src.training.train_loso import (
    BURST_SCALES_SEC,
    _burst_metrics,
    _select_sessions,
)

ROOT = Path(__file__).parents[3]
MODEL_DIR = ROOT / "models"

# window-sec -> Sample-Anzahl bei 50 Hz.
WIN_SEQ_LEN: dict[int, int] = {1: 50, 5: 250}

DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def _set_seed(seed: int = 42) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def train_one_model(
    model: torch.nn.Module,
    train_X: np.ndarray,
    train_y: np.ndarray,
    val_X: np.ndarray,
    val_y: np.ndarray,
    max_epochs: int = 60,
    patience: int = 8,
    batch_size: int = 64,
    lr: float = 1e-3,
) -> torch.nn.Module:
    """Trainiere ein Modell mit Early Stopping auf Val-ROC-AUC.

    Das beste Modell (hoechste Val-AUC) wird am Ende zurueckgeladen.
    ``pos_weight`` gleicht die Klassen-Imbalance aus (Pendant zu
    ``class_weight='balanced'`` beim RF).
    """
    model = model.to(DEVICE)
    n_pos = float((train_y == 1).sum())
    n_neg = float((train_y == 0).sum())
    pos_weight = torch.tensor([n_neg / max(n_pos, 1.0)], device=DEVICE)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    ds = TensorDataset(
        torch.from_numpy(train_X),
        torch.from_numpy(train_y.astype(np.float32)),
    )
    # drop_last: BatchNorm1d kollabiert bei Batch-Groesse 1.
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_Xt = torch.from_numpy(val_X).to(DEVICE)

    best_auc = -1.0
    best_state: dict | None = None
    epochs_since_best = 0

    for _ in range(max_epochs):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            val_logits = model(val_Xt).cpu().numpy()
        try:
            val_auc = roc_auc_score(val_y, val_logits)
        except ValueError:
            val_auc = 0.0

        if val_auc > best_auc:
            best_auc = val_auc
            best_state = {
                k: v.detach().cpu().clone() for k, v in model.state_dict().items()
            }
            epochs_since_best = 0
        else:
            epochs_since_best += 1
            if epochs_since_best >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def predict_proba(model: torch.nn.Module, X: np.ndarray) -> np.ndarray:
    """Sigmoid-Wahrscheinlichkeiten fuer die positive Klasse (writing)."""
    model.eval()
    with torch.no_grad():
        logits = model(torch.from_numpy(X).to(DEVICE)).cpu().numpy()
    return 1.0 / (1.0 + np.exp(-logits))
