"""FastAPI TestClient smokes for /study/*."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(data_dirs, monkeypatch, tmp_path):
    import src.server.state as state_mod
    state_mod.state = state_mod.SessionState()

    import src.server.routes as routes_mod
    import src.server.routes.airpods as airpods_routes
    import src.server.routes.dashboard as dashboard_routes
    import src.server.routes.pen as pen_routes
    import src.server.routes.sessions as sessions_routes
    import src.server.routes.study as study_routes
    import src.server.routes.watch as watch_routes
    import src.server.routes.ws as ws_routes
    import src.server.csv_io as csv_io_mod
    import src.server.pen_proc as pen_proc_mod
    route_modules = (
        airpods_routes, dashboard_routes, pen_routes,
        sessions_routes, study_routes, watch_routes, ws_routes,
    )
    for mod in route_modules:
        if hasattr(mod, "state"):
            monkeypatch.setattr(mod, "state", state_mod.state)
    monkeypatch.setattr(csv_io_mod, "state", state_mod.state)
    monkeypatch.setattr(pen_proc_mod, "state", state_mod.state)

    markers_dir = tmp_path / "markers"
    markers_dir.mkdir()
    monkeypatch.setattr(csv_io_mod, "MARKERS_DIR", markers_dir)
    monkeypatch.setattr(study_routes, "write_marker", csv_io_mod.write_marker)

    async def fake_start_pen(session_id):
        state_mod.state.pen_session_id = session_id
        return {"ok": True, "session_id": session_id}

    async def fake_stop_pen():
        state_mod.state.pen_session_id = None

    for mod in (sessions_routes, pen_routes):
        monkeypatch.setattr(mod, "_start_pen", fake_start_pen)
        monkeypatch.setattr(mod, "_stop_pen", fake_stop_pen)

    async def fake_broadcast(msg):
        pass
    for mod in (sessions_routes, watch_routes, airpods_routes):
        monkeypatch.setattr(mod, "_broadcast", fake_broadcast)

    def fake_preflight():
        return {"ok": True, "can_start": True, "blockers": [], "warnings": [], "status": {}}
    monkeypatch.setattr(sessions_routes, "_session_preflight_payload", fake_preflight)

    app = FastAPI()
    app.include_router(routes_mod.router)
    with TestClient(app) as c:
        yield c


def test_list_protocols_includes_v1(client):
    r = client.get("/study/protocols")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert "v1" in ids


def test_start_study_returns_session_and_schedule(client):
    r = client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST",
        "description": "endpoint smoke", "force_preflight": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "session_id" in body
    assert body["protocol"]["id"] == "v1"
    assert isinstance(body["schedule"], list)
    assert len(body["schedule"]) == 5  # 3 writing + 2× pause
    client.post("/session/stop")


def test_pause_resume_abort_round_trip(client):
    client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST",
        "description": "x", "force_preflight": True,
    })
    assert client.post("/study/pause").status_code == 200
    assert client.post("/study/pause").status_code == 200
    assert client.post("/study/next").status_code == 200
    assert client.post("/study/abort").status_code == 200
    client.post("/session/stop")


def test_pause_when_inactive_returns_409(client):
    r = client.post("/study/pause")
    assert r.status_code == 409


def test_mark_session_as_test_changes_columns(client):
    # Start a real study (not test_mode) so study_mode='study' is persisted.
    r = client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "REAL_SUBJECT",
        "description": "real run", "force_preflight": True,
    })
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    client.post("/study/abort")
    client.post("/session/stop")

    pre = next(s for s in client.get("/sessions").json() if s["session_id"] == sid)
    assert pre["study_mode"] == "study"
    assert pre.get("subject_index", "") != ""

    r = client.post(f"/sessions/{sid}/mark-test")
    assert r.status_code == 200, r.text

    post = next(s for s in client.get("/sessions").json() if s["session_id"] == sid)
    assert post["study_mode"] == "test"
    assert post.get("subject_index", "") == ""
    assert post["description"].upper().startswith("[TEST]")


def test_mark_session_as_test_404_for_unknown(client):
    r = client.post("/sessions/S999/mark-test")
    assert r.status_code == 404


def test_test_mode_skips_subject_index(client):
    r = client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST_USER",
        "description": "endpoint smoke", "force_preflight": True,
        "test_mode": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["test_mode"] is True
    assert body["subject_index"] is None
    client.post("/session/stop")
