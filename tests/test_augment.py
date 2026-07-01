# tests/test_augment.py
"""Tests fuer die On-the-fly-IMU-Augmentation (src/training/deep/augment.py)."""
from __future__ import annotations

import torch

from src.training.deep.augment import (
    Augmenter,
    jitter_batch,
    magnitude_warp_batch,
    rotate_batch,
    scale_batch,
    time_warp_batch,
)


def test_scale_batch_preserves_shape():
    x = torch.randn(5, 250, 6)
    gen = torch.Generator().manual_seed(0)
    out = scale_batch(x, gen)
    assert out.shape == x.shape


def test_scale_batch_within_range():
    # x = ones -> out == per-Fenster-Skalar; muss in [lo, hi] liegen.
    x = torch.ones(2000, 1, 6)
    gen = torch.Generator().manual_seed(1)
    out = scale_batch(x, gen, lo=0.8, hi=1.2)
    s = out[:, 0, 0]
    assert float(s.min()) >= 0.8 - 1e-6
    assert float(s.max()) <= 1.2 + 1e-6


def test_scale_batch_one_scalar_per_window():
    # Ein Skalar je Fenster auf ALLE Kanaele -> innerhalb eines Fensters
    # ist out/x ueberall gleich.
    x = torch.randn(4, 30, 6).abs() + 1.0  # kein Nenner ~0
    gen = torch.Generator().manual_seed(2)
    out = scale_batch(x, gen)
    ratio = out / x
    for w in range(4):
        assert torch.allclose(ratio[w], ratio[w].flatten()[0].expand_as(ratio[w]), atol=1e-5)


def test_rotate_batch_preserves_shape():
    x = torch.randn(5, 250, 6)
    gen = torch.Generator().manual_seed(0)
    assert rotate_batch(x, gen).shape == x.shape


def test_rotate_preserves_per_sample_magnitude():
    # Rotation ist orthogonal -> ||R v|| = ||v|| pro Sample, fuer Accel- und
    # Gyro-Triplet getrennt.
    x = torch.randn(4, 50, 6)
    gen = torch.Generator().manual_seed(123)
    out = rotate_batch(x, gen, max_deg=10.0)
    for sl in (slice(0, 3), slice(3, 6)):
        n_in = x[..., sl].norm(dim=-1)
        n_out = out[..., sl].norm(dim=-1)
        assert torch.allclose(n_in, n_out, atol=1e-5)


def test_rotate_zero_angle_is_identity():
    x = torch.randn(3, 20, 6)
    gen = torch.Generator().manual_seed(0)
    out = rotate_batch(x, gen, max_deg=0.0)
    assert torch.allclose(out, x, atol=1e-5)


def test_rotate_same_matrix_on_accel_and_gyro():
    # Identischer Input in beiden Triplets -> identischer Output (gleiche R).
    base = torch.randn(3, 8, 3)
    x = torch.cat([base, base], dim=-1)
    gen = torch.Generator().manual_seed(7)
    out = rotate_batch(x, gen, max_deg=10.0)
    assert torch.allclose(out[..., 0:3], out[..., 3:6], atol=1e-5)


def test_augmenter_preserves_shape():
    x = torch.randn(6, 250, 6)
    assert Augmenter(seed=0)(x).shape == x.shape


def test_augmenter_deterministic_per_seed():
    x = torch.randn(4, 40, 6)
    a1 = Augmenter(seed=42)(x.clone())
    a2 = Augmenter(seed=42)(x.clone())
    a3 = Augmenter(seed=43)(x.clone())
    assert torch.allclose(a1, a2)
    assert not torch.allclose(a1, a3)


def test_augmenter_toggle_transforms():
    x = torch.randn(4, 40, 6)
    # alle aus -> Identitaet (jitter/magnitude/time_warp default aus).
    out = Augmenter(seed=1, scale=False, rotate=False)(x.clone())
    assert torch.allclose(out, x, atol=1e-6)


# --- Richerer Satz: jitter / magnitude / time_warp --------------------------


def test_jitter_preserves_shape_and_perturbs():
    x = torch.randn(4, 50, 6)
    gen = torch.Generator().manual_seed(0)
    out = jitter_batch(x, gen, sigma=0.05)
    assert out.shape == x.shape
    assert not torch.allclose(out, x)          # veraendert
    assert (out - x).abs().mean() < 0.2        # aber mild


def test_magnitude_warp_shape_and_zero_sigma_identity():
    x = torch.randn(3, 60, 6)
    gen = torch.Generator().manual_seed(1)
    assert magnitude_warp_batch(x, gen).shape == x.shape
    # sigma=0 -> Kurve konstant 1.0 -> Identitaet.
    assert torch.allclose(magnitude_warp_batch(x, gen, sigma=0.0), x, atol=1e-5)


def test_time_warp_shape_and_zero_sigma_identity():
    x = torch.randn(3, 60, 6)
    gen = torch.Generator().manual_seed(2)
    assert time_warp_batch(x, gen).shape == x.shape
    # sigma=0 -> gleichmaessige Geschwindigkeit -> Integer-Zeitraster -> Identitaet.
    assert torch.allclose(time_warp_batch(x, gen, sigma=0.0), x, atol=1e-4)


def test_time_warp_preserves_length_various():
    gen = torch.Generator().manual_seed(3)
    for length in (50, 250, 500):
        assert time_warp_batch(torch.randn(2, length, 6), gen).shape == (2, length, 6)


def test_rich_augmenter_all_on_deterministic_and_distinct():
    x = torch.randn(4, 250, 6)
    cfg = dict(jitter=True, magnitude=True, time_warp=True,
               scale_range=(0.7, 1.3), max_deg=20.0)
    a1 = Augmenter(seed=5, **cfg)(x.clone())
    a2 = Augmenter(seed=5, **cfg)(x.clone())
    assert a1.shape == x.shape
    assert torch.allclose(a1, a2)              # deterministisch pro Seed
    # richer unterscheidet sich vom reinen scale+rotate.
    assert not torch.allclose(a1, Augmenter(seed=5)(x.clone()))
