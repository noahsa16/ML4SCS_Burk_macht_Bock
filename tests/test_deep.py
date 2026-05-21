"""Smoke-Tests fuer das Deep-Sequenz-Modell-Paket."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from src.training.deep.data import build_raw_windows, zscore_channels
from src.training.deep.models import CNN1D, MODELS


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


from src.training.deep.train_loso import train_one_model, predict_proba


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

    model = train_one_model(
        CNN1D(), X, y, Xv, yv, max_epochs=4, patience=4, batch_size=16
    )
    proba = predict_proba(model, Xv)
    assert proba.shape == (16,)
    assert np.all((proba >= 0.0) & (proba <= 1.0))
