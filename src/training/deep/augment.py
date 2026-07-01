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
import torch.nn.functional as F


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


def jitter_batch(
    x: torch.Tensor, gen: torch.Generator, sigma: float = 0.03
) -> torch.Tensor:
    """Additives gaussisches Rauschen pro Sample (Sensor-Rausch-Robustheit).

    Mild: die Watch-Sensoren sind ohnehin rauscharm — dient nur der Regularisierung.
    """
    noise = (torch.randn(x.shape, generator=gen) * sigma).to(device=x.device, dtype=x.dtype)
    return x + noise


def _smooth_curve(
    b: int, length: int, gen: torch.Generator, center: float, sigma: float, n_knots: int = 4
) -> torch.Tensor:
    """``(B, length)`` glatte Zufallskurve je Fenster: ``n_knots`` Knoten
    ``~ N(center, sigma)`` linear auf ``length`` interpoliert. CPU."""
    knots = center + sigma * torch.randn(b, n_knots, generator=gen)  # (B, n_knots)
    return F.interpolate(
        knots.unsqueeze(1), size=length, mode="linear", align_corners=True
    ).squeeze(1)


def magnitude_warp_batch(
    x: torch.Tensor, gen: torch.Generator, sigma: float = 0.2, n_knots: int = 4
) -> torch.Tensor:
    """Glatte ZEITVARIANTE Skalierung je Fenster (Um et al. 2017), auf alle Kanaele.

    Anders als ``scale_batch`` (ein Skalar je Fenster) moduliert eine glatte Kurve
    ueber die Zeit -> reichere Amplituden-Variation, weiterhin label-safe.
    """
    b, length, _ = x.shape
    curve = _smooth_curve(b, length, gen, 1.0, sigma, n_knots).to(device=x.device, dtype=x.dtype)
    return x * curve.unsqueeze(-1)


def time_warp_batch(
    x: torch.Tensor, gen: torch.Generator, sigma: float = 0.2, n_knots: int = 4
) -> torch.Tensor:
    """Glatte zeitliche Verzerrung je Fenster + Resample auf gleiche Laenge.

    Modelliert wechselnde Schreibgeschwindigkeit (Soft-Writer / P09) — die Achse,
    die scale/rotate nicht beruehren. Eine glatte positive Geschwindigkeits-Kurve
    wird kumuliert zu einer Zeit-Abbildung; ``x`` wird an den verzerrten Positionen
    linear interpoliert. Erhaelt Shape ``(B, seq_len, C)``; label-safe fuer
    mehrheitlich-eine-Klasse-Fenster.
    """
    b, length, c = x.shape
    speed = _smooth_curve(b, length, gen, 1.0, sigma, n_knots).clamp(min=0.1)  # (B,L) CPU
    cum = torch.cumsum(speed, dim=1)
    cum = cum - cum[:, :1]
    warped = ((cum / cum[:, -1:].clamp(min=1e-8)) * (length - 1)).to(device=x.device)
    idx0 = warped.floor().long().clamp(0, length - 1)
    idx1 = (idx0 + 1).clamp(0, length - 1)
    frac = (warped - idx0.to(warped.dtype)).unsqueeze(-1)         # (B, L, 1)
    g0 = idx0.unsqueeze(-1).expand(-1, -1, c)
    g1 = idx1.unsqueeze(-1).expand(-1, -1, c)
    return torch.gather(x, 1, g0) * (1 - frac) + torch.gather(x, 1, g1) * frac


class Augmenter:
    """Komponiert aktive Transforms; Callable ``(B,seq_len,6) -> (B,seq_len,6)``.

    Haelt einen eigenen CPU-``torch.Generator`` (seed-abgeleitet), getrennt vom
    globalen RNG. Ruehrt ``y`` nie an. Defaults = scale+rotate (der urspruengliche
    Satz); jitter/magnitude/time_warp per Flag zuschaltbar (richerer Satz).
    """

    def __init__(
        self,
        seed: int,
        scale: bool = True,
        rotate: bool = True,
        jitter: bool = False,
        magnitude: bool = False,
        time_warp: bool = False,
        scale_range: tuple[float, float] = (0.8, 1.2),
        max_deg: float = 10.0,
        jitter_sigma: float = 0.03,
        mag_sigma: float = 0.2,
        warp_sigma: float = 0.2,
    ) -> None:
        self.scale = scale
        self.rotate = rotate
        self.jitter = jitter
        self.magnitude = magnitude
        self.time_warp = time_warp
        self.scale_range = scale_range
        self.max_deg = max_deg
        self.jitter_sigma = jitter_sigma
        self.mag_sigma = mag_sigma
        self.warp_sigma = warp_sigma
        self.gen = torch.Generator()
        self.gen.manual_seed(int(seed))

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        # Reihenfolge: erst die Zeit-/Formverzerrer, dann Amplitude, Rauschen zuletzt.
        if self.time_warp:
            x = time_warp_batch(x, self.gen, self.warp_sigma)
        if self.rotate:
            x = rotate_batch(x, self.gen, self.max_deg)
        if self.magnitude:
            x = magnitude_warp_batch(x, self.gen, self.mag_sigma)
        if self.scale:
            lo, hi = self.scale_range
            x = scale_batch(x, self.gen, lo, hi)
        if self.jitter:
            x = jitter_batch(x, self.gen, self.jitter_sigma)
        return x
