# src/training/deep/augment.py
"""On-the-fly Augmentation roher IMU-Fenster fuer die Deep-Netze.

Operiert auf Batch-Tensoren der Form ``(B, seq_len, 6)`` -- dem Layout, das
der DataLoader liefert (die Modelle transponieren intern selbst). Kanal-
Layout folgt ``IMU_COLS``: Accel-Triplet 0:3, Gyro-Triplet 3:6.

Label-erhaltend by construction (kein Transform sieht oder aendert ``y``)
und nur im Train-Loop angewandt. Jeder Transform zieht seine Zufallswerte
aus einem uebergebenen CPU-``torch.Generator`` und verschiebt sie dann auf
``x.device`` -- so bleibt es deterministisch und umgeht MPS-Generator-
Eigenheiten.
"""
from __future__ import annotations

import math

import torch


def scale_batch(
    x: torch.Tensor, gen: torch.Generator, lo: float = 0.8, hi: float = 1.2
) -> torch.Tensor:
    """Pro Fenster ein Zufalls-Skalar ``s ~ U(lo, hi)`` auf alle 6 Kanaele.

    Ein Skalar je Fenster (nicht je Kanal) -- modelliert einen "lauter/leiser"
    bewegenden Menschen, ohne die Accel/Gyro-Balance unphysikalisch zu
    verzerren.
    """
    b = x.shape[0]
    s = torch.rand(b, 1, 1, generator=gen)  # CPU
    s = (lo + (hi - lo) * s).to(device=x.device, dtype=x.dtype)
    return x * s


def _rotation_matrices(b: int, gen: torch.Generator, max_deg: float) -> torch.Tensor:
    """``(B, 3, 3)`` Rotationsmatrizen aus Euler-Winkeln ``~ U(-max_deg, max_deg)``.

    ``R = Rz(g) @ Ry(b) @ Rx(a)`` je Fenster. Bei ``max_deg=0`` exakt die
    Identitaet (alle Winkel 0). Auf CPU gebaut; der Aufrufer verschiebt nach
    ``x.device``.
    """
    max_rad = math.radians(max_deg)
    ang = (torch.rand(b, 3, generator=gen) * 2 - 1) * max_rad
    a, be, g = ang.unbind(dim=1)
    z, o = torch.zeros(b), torch.ones(b)
    ca, sa = torch.cos(a), torch.sin(a)
    cb, sb = torch.cos(be), torch.sin(be)
    cg, sg = torch.cos(g), torch.sin(g)
    Rx = torch.stack([o, z, z, z, ca, -sa, z, sa, ca], dim=1).reshape(b, 3, 3)
    Ry = torch.stack([cb, z, sb, z, o, z, -sb, z, cb], dim=1).reshape(b, 3, 3)
    Rz = torch.stack([cg, -sg, z, sg, cg, z, z, z, o], dim=1).reshape(b, 3, 3)
    return Rz @ Ry @ Rx


def rotate_batch(
    x: torch.Tensor, gen: torch.Generator, max_deg: float = 10.0
) -> torch.Tensor:
    """Pro Fenster eine kleine 3D-Rotation, dieselbe ``R`` auf Accel & Gyro.

    ``x`` Shape ``(B, seq_len, 6)`` (Accel 0:3, Gyro 3:6). Beide Triplets
    messen im selben Watch-Frame -> dieselbe Rotation. Erhaelt die
    Vektor-Magnitude jedes Samples (``||R v|| = ||v||``).
    """
    b = x.shape[0]
    R = _rotation_matrices(b, gen, max_deg).to(device=x.device, dtype=x.dtype)
    acc = torch.einsum("bij,bsj->bsi", R, x[..., 0:3])
    gyr = torch.einsum("bij,bsj->bsi", R, x[..., 3:6])
    return torch.cat([acc, gyr], dim=-1)


class Augmenter:
    """Komponiert aktive Transforms; Callable ``(B,seq_len,6) -> (B,seq_len,6)``.

    Haelt einen eigenen CPU-``torch.Generator`` (seed-abgeleitet), getrennt vom
    globalen RNG. Ruehrt ``y`` nie an.
    """

    def __init__(
        self,
        seed: int,
        scale: bool = True,
        rotate: bool = True,
        scale_range: tuple[float, float] = (0.8, 1.2),
        max_deg: float = 10.0,
    ) -> None:
        self.scale = scale
        self.rotate = rotate
        self.scale_range = scale_range
        self.max_deg = max_deg
        self.gen = torch.Generator()
        self.gen.manual_seed(int(seed))

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        if self.rotate:
            x = rotate_batch(x, self.gen, self.max_deg)
        if self.scale:
            lo, hi = self.scale_range
            x = scale_batch(x, self.gen, lo, hi)
        return x
