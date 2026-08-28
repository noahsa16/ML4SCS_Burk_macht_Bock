import hashlib
import json

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
    assert len(fx["channel_names"]) == n_channels
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
    assert fx["windows"]
    model, _ = load_deploy_model(CHECKPOINTS[kind])
    for w in fx["windows"]:
        arr = decode_window(w["data_b64"], fx["seq_len"], fx["n_channels"])
        with torch.no_grad():
            got = float(model(torch.from_numpy(arr).unsqueeze(0))[0])
        assert abs(got - w["logit"]) <= 1e-4, f"{w['id']}: {got} vs {w['logit']}"


COREML_DIR = FIXTURES["active"].parents[2] / "models" / "coreml"
COREML_NAMES = {"active": "ScrybeActive", "passive": "ScrybePassive"}


@pytest.mark.skipif(
    not all((COREML_DIR / f"{n}.mlpackage").exists() for n in COREML_NAMES.values()),
    reason="mlpackage noch nicht exportiert",
)
@pytest.mark.parametrize("kind", ["active", "passive"])
def test_coreml_matches_pytorch(kind):
    """P1: das konvertierte Modell stimmt mit PyTorch ueberein."""
    ct = pytest.importorskip("coremltools",
                             reason="nur im .venv-coreml installiert")
    fx = load_fixture(kind)
    assert fx["windows"]
    mlmodel = ct.models.MLModel(
        str(COREML_DIR / f"{COREML_NAMES[kind]}.mlpackage"),
        compute_units=ct.ComputeUnit.CPU_ONLY,
    )
    for w in fx["windows"]:
        arr = decode_window(w["data_b64"], fx["seq_len"], fx["n_channels"])
        out = mlmodel.predict({"window": arr[None, ...].astype(np.float32)})
        got = float(np.ravel(out["logit"])[0])
        assert abs(got - w["logit"]) <= 1e-4, f"{w['id']}: {got} vs {w['logit']}"
        # Bei Schwelle 0.5 muss auch die Klassifikation identisch sein.
        assert (got >= 0) == (w["logit"] >= 0), f"{w['id']}: Klassenwechsel"


WATCH_COREML = {
    "active": COREML_DIR.parents[1] / "watch_streamer" / "WatchStreamer"
                                     / "ScrybeActive.mlpackage",
    "passive": COREML_DIR.parents[1] / "watch_streamer" / "WatchStreamer Watch App"
                                      / "ScrybePassive.mlpackage",
}


def _sha256_dir(path):
    """SHA-256 eines Verzeichnisses (rekursiv, pfadsortiert).

    Spiegelt scripts/pipeline/export_coreml.py::_sha256 (dir-Zweig), damit
    ein .mlpackage auf beiden Seiten dieser Pruefung gleich gehasht wird.
    """
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(path)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


@pytest.mark.parametrize("kind", ["active", "passive"])
def test_watch_copy_matches_committed_sidecar(kind):
    """Die unter watch_streamer/ committete .mlpackage-Kopie muss zu ihrem
    ebenfalls committeten SHA-256-Sidecar passen. Laeuft immer (kein
    models/-Zugriff noetig) -- das ist der Provenienz-Nachweis, der frueher
    nur auf einer einzelnen Maschine existierte (Spec 7.2, Review I6)."""
    copy = WATCH_COREML[kind]
    sidecar = copy.with_suffix(".json")
    assert copy.exists(), f"fehlende watch_streamer-Kopie: {copy}"
    assert sidecar.exists(), f"fehlendes Sidecar: {sidecar}"
    meta = json.loads(sidecar.read_text())
    assert _sha256_dir(copy) == meta["sha256"]


@pytest.mark.skipif(not COREML_DIR.exists(),
                    reason="models/coreml ist gitignored, hier nicht vorhanden")
@pytest.mark.parametrize("kind", ["active", "passive"])
def test_watch_copy_matches_source_model(kind):
    """Ohne diese Pruefung erzwingt nichts, dass die App-Kopie mit dem
    Modell mithaelt, gegen das die Paritaet gemessen wurde -- ein Re-Export,
    der den Kopierschritt vergisst, liesse die Xcode-Tests weiter gruen
    gegen ein konsistentes, aber veraltetes Modell/Fixture-Paar laufen."""
    source = COREML_DIR / f"{COREML_NAMES[kind]}.mlpackage"
    copy = WATCH_COREML[kind]
    assert _sha256_dir(source) == _sha256_dir(copy)
