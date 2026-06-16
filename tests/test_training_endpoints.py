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


def test_run_detail_returns_feature_groups_and_roc(client, monkeypatch, tmp_path):
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier
    from src.server import training_runs as tr
    monkeypatch.setattr(tr, "RUNS_ROOT", tmp_path)
    d = tr.run_dir("2026-06-16_12-00_rf_legacy", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "legacy"})
    pd.DataFrame([{"held_out": "P1", "accuracy": 0.9}]).to_csv(d / "cv.csv", index=False)
    cols = ["ax_mean", "ax_jerk_std", "ax_zcr", "ax_spec_centroid",
            "acc_mag_mean", "corr_ax_ay"]
    clf = RandomForestClassifier(n_estimators=4).fit(
        np.random.rand(30, len(cols)), np.random.randint(0, 2, 30))
    joblib.dump({"model": clf, "feature_cols": cols}, d / "model.joblib")
    pd.DataFrame({"label": [0, 1, 0, 1, 1, 0],
                  "proba_raw": [.1, .8, .2, .7, .9, .3]}).to_csv(d / "oof.csv", index=False)
    r = client.get("/training/runs/2026-06-16_12-00_rf_legacy")
    assert r.status_code == 200
    body = r.json()
    groups = {g["group"] for g in body["feature_groups"]}
    assert {"time_stats", "jerk", "zcr", "spectral", "magnitude", "correlation"} & groups
    assert isinstance(body["roc"], list) and len(body["roc"]) >= 2


def test_run_detail_unknown_404(client, monkeypatch, tmp_path):
    from src.server import training_runs as tr
    monkeypatch.setattr(tr, "RUNS_ROOT", tmp_path)
    assert client.get("/training/runs/nope").status_code == 404


def test_status_payload_includes_training_block(monkeypatch):
    import src.server.state as state_mod
    import src.server.status as status_mod
    monkeypatch.setattr(status_mod, "state", state_mod.SessionState())
    payload = status_mod._status_payload()
    assert "training" in payload
    assert "phase" in payload["training"]
