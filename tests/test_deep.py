"""Smoke-Tests fuer das Deep-Sequenz-Modell-Paket."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from src.training.deep.data import build_raw_windows, zscore_channels
from src.training.deep.models import CNN1D, MODELS
from src.training.deep.train_loso import (
    _acc_auc,
    fold_metrics,
    predict_proba,
    train_one_model,
)


def _synthetic_merged(n_samples: int = 600) -> pd.DataFrame:
    """600 Samples @ 50 Hz = 12 s; erste Haelfte writing, zweite idle."""
    t0 = 1_700_000_000_000.0
    times = t0 + np.arange(n_samples) * 20.0  # 20 ms Abstand = 50 Hz
    rng = np.random.default_rng(0)
    label = np.where(np.arange(n_samples) < n_samples // 2, 1, 0)
    return pd.DataFrame({
        "local_ts_ms": times,
        "ax": rng.normal(size=n_samples), "ay": rng.normal(size=n_samples),
        "az": rng.normal(size=n_samples), "rx": rng.normal(size=n_samples),
        "ry": rng.normal(size=n_samples), "rz": rng.normal(size=n_samples),
        "label_writing": label,
    })


def test_build_raw_windows_shape():
    merged = _synthetic_merged()
    X, y, t = build_raw_windows(merged, seq_len=50, stride=25)
    # 600 Samples, win=50, stride=25 -> (600-50)/25 + 1 = 23 Fenster
    assert X.shape == (23, 50, 6)
    assert y.shape == (23,)
    assert t.shape == (23,)
    assert X.dtype == np.float32
    assert set(np.unique(y)).issubset({0, 1})


def test_build_raw_windows_seq_len_250():
    merged = _synthetic_merged()
    X, _, _ = build_raw_windows(merged, seq_len=250, stride=25)
    # (600-250)/25 + 1 = 15 Fenster
    assert X.shape == (15, 250, 6)


def test_build_raw_windows_label_threshold():
    merged = _synthetic_merged()
    X, y, _ = build_raw_windows(merged, seq_len=50, stride=25,
                                max_gap_ms=0.0)
    # Fruehe Fenster (ganz in der writing-Haelfte) -> 1, spaete -> 0.
    assert y[0] == 1
    assert y[-1] == 0


def test_build_raw_windows_too_short_returns_empty():
    merged = _synthetic_merged(n_samples=10)
    X, y, t = build_raw_windows(merged, seq_len=50, stride=25)
    assert X.shape == (0, 50, 6)
    assert len(y) == 0 and len(t) == 0


def test_build_raw_windows_missing_column_raises():
    merged = _synthetic_merged().drop(columns=["rz"])
    with pytest.raises(ValueError, match="missing columns"):
        build_raw_windows(merged, seq_len=50)


@pytest.mark.parametrize("seq_len,stride", [(1, 25), (0, 25), (50, 0)])
def test_build_raw_windows_bad_bounds_raise(seq_len, stride):
    merged = _synthetic_merged()
    with pytest.raises(ValueError, match="too small"):
        build_raw_windows(merged, seq_len=seq_len, stride=stride)


def test_build_raw_windows_exclude_boundary_drops_transition():
    """exclude_boundary verwirft Fenster, die den writing<->idle-Uebergang straddeln."""
    merged = _synthetic_merged()  # writing -> idle bei Sample 300
    X_full, _, _ = build_raw_windows(merged, seq_len=50, stride=25, max_gap_ms=0.0)
    X_ex, y_ex, t_ex = build_raw_windows(
        merged, seq_len=50, stride=25, max_gap_ms=0.0, exclude_boundary=(0.4, 0.6)
    )
    assert len(X_ex) < len(X_full)            # mind. ein Uebergangs-Fenster weg
    assert X_ex.shape[1:] == X_full.shape[1:]  # Fensterform unveraendert
    assert len(y_ex) == len(X_ex) == len(t_ex)


def test_zscore_channels_normalises_per_channel():
    rng = np.random.default_rng(1)
    X = rng.normal(loc=5.0, scale=3.0, size=(40, 50, 6)).astype(np.float32)
    Xz = zscore_channels(X)
    flat = Xz.reshape(-1, 6)
    assert np.allclose(flat.mean(axis=0), 0.0, atol=1e-4)
    assert np.allclose(flat.std(axis=0), 1.0, atol=1e-4)
    assert Xz.dtype == np.float32


def test_zscore_channels_constant_channel_safe():
    X = np.ones((10, 50, 6), dtype=np.float32)
    Xz = zscore_channels(X)
    assert np.all(np.isfinite(Xz))


def test_zscore_channels_empty_safe():
    X = np.empty((0, 50, 6), dtype=np.float32)
    assert zscore_channels(X).shape == (0, 50, 6)


@pytest.mark.parametrize("seq_len", [50, 250])
def test_cnn_forward_shape(seq_len):
    model = CNN1D()
    x = torch.randn(8, seq_len, 6)
    out = model(x)
    # Output: ein Logit pro Sample, Shape (batch,)
    assert out.shape == (8,)
    assert torch.all(torch.isfinite(out))


def test_cnn_forward_batch_one():
    model = CNN1D()
    model.eval()
    out = model(torch.randn(1, 50, 6))
    assert out.shape == (1,)
    assert torch.all(torch.isfinite(out))


@pytest.mark.parametrize("name", ["cnn", "lstm", "gru"])
@pytest.mark.parametrize("seq_len", [50, 250])
def test_model_registry_forward(name, seq_len):
    model = MODELS[name]()
    out = model(torch.randn(8, seq_len, 6))
    assert out.shape == (8,)
    assert torch.all(torch.isfinite(out))


def test_models_registry_keys():
    assert set(MODELS.keys()) == {"cnn", "lstm", "gru"}


def test_train_one_model_runs_and_predicts():
    """Mini-Lauf: lernbares Muster, wenige Epochen -- nur Smoke, kein Metrik-Ziel."""
    rng = np.random.default_rng(2)
    # Klasse 1 = hoehere Varianz auf allen Kanaelen; klar trennbar.
    def _make(n, scale):
        return (rng.normal(scale=scale, size=(n, 50, 6))).astype(np.float32)
    X = np.concatenate([_make(32, 0.2), _make(32, 2.0)])
    y = np.concatenate([np.zeros(32), np.ones(32)]).astype(np.int64)
    Xv = np.concatenate([_make(8, 0.2), _make(8, 2.0)])
    yv = np.concatenate([np.zeros(8), np.ones(8)]).astype(np.int64)

    model, best_epoch = train_one_model(
        CNN1D(), X, y, Xv, yv, max_epochs=4, patience=4, batch_size=16
    )
    assert isinstance(best_epoch, int)
    assert -1 <= best_epoch <= 3  # 0-indexiert, max_epochs=4
    proba = predict_proba(model, Xv)
    assert proba.shape == (16,)
    assert np.all((proba >= 0.0) & (proba <= 1.0))


def test_acc_auc_ranges_and_perfect_split():
    """_acc_auc: Wertebereich + perfekt trennbarer Fall."""
    rng = np.random.default_rng(7)
    y = np.concatenate([np.zeros(20), np.ones(20)]).astype(np.int64)
    # Wahrscheinlichkeiten, die die Klassen sauber trennen.
    proba = np.concatenate([rng.uniform(0.0, 0.4, 20), rng.uniform(0.6, 1.0, 20)])
    acc, auc = _acc_auc(proba, y)
    assert acc == 1.0
    assert auc == 1.0
    # Einklassiges y -> AUC undefiniert -> nan, acc weiterhin endlich.
    acc1, auc1 = _acc_auc(np.full(10, 0.7), np.ones(10, dtype=np.int64))
    assert 0.0 <= acc1 <= 1.0
    assert np.isnan(auc1)


def test_fold_metrics_keys_and_ranges():
    """fold_metrics liefert 1-s- + Burst-Metriken auf einem Test-Fold."""
    rng = np.random.default_rng(3)
    n = 120
    proba = rng.uniform(size=n)
    y_true = rng.integers(0, 2, size=n)
    test_df = pd.DataFrame({
        "session_id": ["S001"] * n,
        "t_center_ms": 1_700_000_000_000.0 + np.arange(n) * 500.0,
    })
    m = fold_metrics(proba, y_true, test_df)
    assert {"accuracy", "f1_writing", "roc_auc", "bursts"} <= set(m)
    assert {"5s", "10s", "30s"} == set(m["bursts"])
    assert 0.0 <= m["accuracy"] <= 1.0
