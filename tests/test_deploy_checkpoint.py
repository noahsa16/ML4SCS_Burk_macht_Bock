# tests/test_deploy_checkpoint.py
from pathlib import Path

import pytest
import torch

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in CHECKPOINTS.values()),
    reason="Deployment-Checkpoints liegen unter models/ und sind gitignored",
)


@pytest.mark.parametrize("kind,n_channels", [("active", 6), ("passive", 3)])
def test_loads_with_expected_channel_count(kind, n_channels):
    model, meta = load_deploy_model(CHECKPOINTS[kind])
    assert meta["n_channels"] == n_channels
    assert meta["fs_hz"] == 50
    assert meta["window_sec"] == 5
    assert meta["zscore"] is False


@pytest.mark.parametrize("kind", ["active", "passive"])
def test_model_is_in_eval_mode(kind):
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    assert model.training is False


def test_missing_channels_key_defaults_to_imu():
    # Why: der aktive Checkpoint entstand vor Einfuehrung des Kanalsatz-Feldes
    # und traegt kein meta["channels"] — blindes Lesen waere ein KeyError.
    _, meta = load_deploy_model(CHECKPOINTS["active"])
    assert meta["channels"] == "imu"


def test_passive_checkpoint_declares_raw_accel():
    _, meta = load_deploy_model(CHECKPOINTS["passive"])
    assert meta["channels"] == "raw_accel"


@pytest.mark.parametrize("kind,n_channels", [("active", 6), ("passive", 3)])
def test_forward_pass_shape_and_determinism(kind, n_channels):
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    x = torch.zeros(1, DEPLOY_SEQ_LEN, n_channels, dtype=torch.float32)
    with torch.no_grad():
        a = model(x)
        b = model(x)
    assert a.shape == (1,)
    # eval() muss Dropout abschalten — sonst weichen zwei Laeufe ab.
    assert torch.equal(a, b)
