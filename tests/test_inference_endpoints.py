"""HTTP smoke tests for /inference/* endpoints (model list + switch).

Uses the same router-only FastAPI setup as test_endpoints.py.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import src.server.state as state_mod
    state_mod.state = state_mod.SessionState()
    import src.server.routes as routes_mod

    app = FastAPI()
    app.include_router(routes_mod.router)
    with TestClient(app) as c:
        yield c


def test_get_models_lists_available(client):
    resp = client.get("/inference/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "models" in body and "current" in body
    assert isinstance(body["models"], list)
    ids = {m["id"] for m in body["models"]}
    # rf_noah was trained earlier in the test session pipeline; rf_all_live
    # was trained by scripts/ml/train_rf_all_live.py. At least one of them
    # must exist for the picker to make sense.
    assert "rf_noah" in ids or "rf_all_live" in ids


def test_get_models_has_expected_fields(client):
    body = client.get("/inference/models").json()
    for m in body["models"]:
        assert "id" in m
        assert "n_windows" in m
        # person_id / sample_rate_hz are optional but key must exist.
        assert "person_id" in m
        assert "sample_rate_hz" in m


def test_switch_to_unknown_id_returns_404(client):
    resp = client.post("/inference/model", json={"id": "rf_nonexistent"})
    assert resp.status_code == 404


def test_switch_to_known_model_swaps_loaded(client):
    list_resp = client.get("/inference/models").json()
    ids = [m["id"] for m in list_resp["models"]]
    if not ids:
        pytest.skip("no models on disk")

    target = ids[0]
    resp = client.post("/inference/model", json={"id": target})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["current"] == target

    confirm = client.get("/inference/current").json()
    assert confirm["current"] == target


def test_switch_clears_inference_buffer(client):
    """A model switch should reset the rolling buffer so predictions from
    the old model don't leak into the sparkline immediately after."""
    from src.server.inference import live

    # Seed the buffer with some samples.
    import time
    t0 = int(time.time() * 1000)
    for i in range(50):
        live.append_sample(t0 + i * 10, 0.1, 0.2, 0.9, 0.01, 0.02, 0.0)
    assert len(live._buffer) > 0

    list_resp = client.get("/inference/models").json()
    ids = [m["id"] for m in list_resp["models"]]
    if not ids:
        pytest.skip("no models on disk")

    client.post("/inference/model", json={"id": ids[0]})
    assert len(live._buffer) == 0
