import numpy as np
import pytest
import torch

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model
from src.deploy.golden import FIXTURES, decode_window, encode_window, load_fixture


def test_encode_decode_roundtrips_exactly():
    rng = np.random.default_rng(0)
    arr = rng.standard_normal((DEPLOY_SEQ_LEN, 3)).astype(np.float32)
    back = decode_window(encode_window(arr), DEPLOY_SEQ_LEN, 3)
    # Base64 ueber float32-Bytes ist verlustfrei — hier ist "genau gleich"
    # das richtige Kriterium, nicht "ungefaehr gleich".
    assert np.array_equal(arr, back)


@pytest.mark.skipif(not all(p.exists() for p in FIXTURES.values()),
                    reason="Fixtures noch nicht erzeugt")
@pytest.mark.parametrize("kind,n_channels", [("active", 6), ("passive", 3)])
def test_fixture_shape_and_balance(kind, n_channels):
    fx = load_fixture(kind)
    assert fx["seq_len"] == DEPLOY_SEQ_LEN
    assert fx["n_channels"] == n_channels
    assert len(fx["windows"]) >= 24
    labels = {w["label"] for w in fx["windows"]}
    assert labels == {0, 1}, "Fixture muss beide Klassen enthalten"
    near = [w for w in fx["windows"] if abs(w["proba"] - 0.5) < 0.15]
    assert near, "Fixture muss schwellennahe Faelle enthalten"


@pytest.mark.skipif(
    not all(p.exists() for p in FIXTURES.values())
    or not all(p.exists() for p in CHECKPOINTS.values()),
    reason="Fixtures oder Checkpoints fehlen",
)
@pytest.mark.parametrize("kind", ["active", "passive"])
def test_pytorch_reproduces_stored_logits(kind):
    """P1a: der Checkpoint reproduziert die gespeicherten Logits."""
    fx = load_fixture(kind)
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    for w in fx["windows"]:
        arr = decode_window(w["data_b64"], fx["seq_len"], fx["n_channels"])
        with torch.no_grad():
            got = float(model(torch.from_numpy(arr).unsqueeze(0))[0])
        assert abs(got - w["logit"]) <= 1e-4, f"{w['id']}: {got} vs {w['logit']}"
