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


def test_models_endpoint_lists_rf(client):
    r = client.get("/training/models")
    assert r.status_code == 200
    assert any(m["id"] == "rf" for m in r.json())


def test_start_rejects_invalid_pool(client):
    r = client.post("/training/start", json={"model": "rf", "pool": "nonsense"})
    assert r.status_code == 400


def test_start_409_when_busy(client, monkeypatch):
    from src.server import training as T
    monkeypatch.setattr(T.run, "is_busy", lambda: True)
    r = client.post("/training/start", json={"model": "rf", "pool": "legacy"})
    assert r.status_code == 409


def test_runs_lists_existing(client, monkeypatch, tmp_path):
    from src.server import training_runs as tr
    monkeypatch.setattr(tr, "RUNS_ROOT", tmp_path)
    d = tr.run_dir("2026-06-16_10-00_rf_auto", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "auto", "mean_acc": 0.87})
    r = client.get("/training/runs")
    assert r.status_code == 200
    assert r.json()[0]["run_id"] == "2026-06-16_10-00_rf_auto"


def test_promote_unknown_run_404(client, monkeypatch, tmp_path):
    from src.server import training_runs as tr
    monkeypatch.setattr(tr, "RUNS_ROOT", tmp_path)
    r = client.post("/training/runs/does-not-exist/promote")
    assert r.status_code == 404


def test_sandbox_unknown_run_404(client, monkeypatch, tmp_path):
    from src.server import training_runs as tr
    monkeypatch.setattr(tr, "RUNS_ROOT", tmp_path)
    r = client.post("/training/runs/does-not-exist/sandbox")
    assert r.status_code == 404
