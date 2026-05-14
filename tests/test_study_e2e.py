"""End-to-end: /study/start writes markers, full round-trip emits all events."""
from __future__ import annotations

import csv

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Why: cannot `from server import app` — the full lifespan would boot the pen
# subprocess, status loop, and real CSV paths. Mirror the fresh-app + monkeypatch
# pattern from tests/test_study_endpoints.py so the markers CSV lands in tmp.
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
        # Expose markers_dir so the test can read the resulting CSV.
        c._markers_dir = markers_dir  # type: ignore[attr-defined]
        yield c


def test_full_study_round_trip(client):
    r = client.post("/study/start", json={
        "protocol_id": "v1", "person_id": "TEST",
        "description": "e2e", "force_preflight": True,
    })
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    # Force several transitions. First /study/next emits study_start +
    # task_start + task_end for slot 0; second advances into the next slot.
    assert client.post("/study/next").status_code == 200
    assert client.post("/study/next").status_code == 200
    assert client.post("/study/abort").status_code == 200
    assert client.post("/session/stop").status_code == 200

    markers_path = client._markers_dir / f"{sid}_markers.csv"
    assert markers_path.exists(), "markers CSV should be written"
    with markers_path.open() as f:
        events = [row["event"] for row in csv.DictReader(f)]

    for required in ("study_start", "task_start", "task_end", "abort", "study_end"):
        assert required in events, f"missing {required!r} in {events}"
