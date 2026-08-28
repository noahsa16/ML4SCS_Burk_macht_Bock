"""Laedt die Deployment-Checkpoints als einsatzbereite Modelle.

Einziger Ort im Repo, der ``weights_only=False`` verwendet: die
Checkpoint-Metadaten tragen ein ``TorchVersion``-Objekt. Zulaessig, weil
ausschliesslich eigene, im Repo erzeugte Dateien geladen werden.
"""
from __future__ import annotations

from pathlib import Path

import torch

from src.training.deep.models import MODELS

ROOT = Path(__file__).resolve().parents[2]

DEPLOY_SEQ_LEN = 250

CHECKPOINTS: dict[str, Path] = {
    "active": ROOT / "models/runs/pod_20260825/results/hp_grid/legacy"
                     "/tcn_bigru_confirm/models_tcn_bigru-g00-s42/final.pt",
    "passive": ROOT / "models/runs/pod_raw50/hp_grid/modern50"
                      "/tcn6_raw50/models_tcn6-g00-s42/final.pt",
}

_DEFAULT_CHANNELS = "imu"


def load_deploy_model(path: Path) -> tuple[torch.nn.Module, dict]:
    """Baue das Modell aus einem Checkpoint und setze es in den Eval-Modus."""
    bundle = torch.load(path, map_location="cpu", weights_only=False)
    meta = dict(bundle["meta"])
    # Why: Checkpoints von vor dem raw_accel-Kanalsatz tragen kein "channels".
    meta.setdefault("channels", _DEFAULT_CHANNELS)

    model = MODELS[meta["model"]](n_channels=int(meta["n_channels"]))
    model.load_state_dict(bundle["state_dict"], strict=True)
    model.eval()
    return model, meta
