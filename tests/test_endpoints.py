"""FastAPI endpoint smoke tests.

We attach the router to a fresh FastAPI app so the lifespan (status loop,
log rotation) doesn't run during tests. Pen subprocess is monkeypatched
to a no-op so we don't actually spawn pen_logger.py.
"""

import csv
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.config import SESSIONS_FIELDNAMES, WATCH_FIELDNAMES


@pytest.fixture
def client(data_dirs, monkeypatch):
    """A TestClient backed by a router-only FastAPI app."""
    # Reset the global state object so tests don't leak into each other.
    import src.server.state as state_mod
    state_mod.state = state_mod.SessionState()

    # Patch state references in modules that imported it at module load time.
    import src.server.routes as routes_mod
    import src.server.routes.airpods as airpods_routes
    import src.server.routes.dashboard as dashboard_routes
    import src.server.routes.pen as pen_routes
    import src.server.routes.sessions as sessions_routes
    import src.server.routes.watch as watch_routes
    import src.server.routes.ws as ws_routes
    import src.server.csv_io as csv_io_mod
    import src.server.pen_proc as pen_proc_mod
    route_modules = (
        airpods_routes, dashboard_routes, pen_routes,
        sessions_routes, watch_routes, ws_routes,
    )
    for mod in route_modules:
        if hasattr(mod, "state"):
            monkeypatch.setattr(mod, "state", state_mod.state)
    monkeypatch.setattr(csv_io_mod, "state", state_mod.state)
    monkeypatch.setattr(pen_proc_mod, "state", state_mod.state)

    # Don't actually spawn the pen_logger.py subprocess.
    async def fake_start_pen(session_id):
        state_mod.state.pen_session_id = session_id
        return {"ok": True, "session_id": session_id}

    async def fake_stop_pen():
        state_mod.state.pen_session_id = None

    for mod in (sessions_routes, pen_routes):
        monkeypatch.setattr(mod, "_start_pen", fake_start_pen)
        monkeypatch.setattr(mod, "_stop_pen", fake_stop_pen)

    # Don't broadcast over a real websocket either.
    async def fake_broadcast(msg):
        pass
    for mod in (sessions_routes, watch_routes, airpods_routes):
        monkeypatch.setattr(mod, "_broadcast", fake_broadcast)

    # Skip the preflight gate (no iPhone bridge / watch in test env).
    def fake_preflight(**_kwargs):
        return {"ok": True, "can_start": True, "blockers": [], "warnings": [], "status": {}}
    monkeypatch.setattr(sessions_routes, "_session_preflight_payload", fake_preflight)

    app = FastAPI()
    app.include_router(routes_mod.router)
    with TestClient(app) as c:
        yield c


# ── POST /watch ───────────────────────────────────────────────────────────────

def _imu_sample(ts: int) -> dict:
    return {"ts": ts, "ax": 0.1, "ay": 0.2, "az": 0.9,
            "rx": 0.01, "ry": 0.02, "rz": 0.0}


def _flush_watch_writers():
    """The /watch endpoint's CSV writer is buffered and only flushes on close.
    Tests need to force flush before reading the file back."""
    from src.server.csv_io import close_all_watch_writers
    close_all_watch_writers()


def test_watch_accepts_envelope_format(client, data_dirs):
    payload = {
        "samples": [_imu_sample(1000 + i * 20) for i in range(5)],
        "sequence": 0,
        "sampleRateHz": 50.0,
        "watchSentAt": 1_700_000_000_000,
        "phoneReceivedAt": 1_700_000_000_010,
        "source": "watch_phone_bridge",
        "sessionId": "S001",
    }
    resp = client.post("/watch", json=payload)
    assert resp.status_code == 200
    _flush_watch_writers()

    csv_path = data_dirs.watch / "S001_watch.csv"
    assert csv_path.exists()
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    assert all(r["ax"] for r in rows)


def test_watch_accepts_bare_list_format(client, data_dirs):
    """The watch app sometimes posts a raw list — must still parse."""
    payload = [_imu_sample(2000 + i * 20) for i in range(3)]
    resp = client.post("/watch", json=payload)
    assert resp.status_code == 200

    # No sessionId was sent and no active session → goes to "unsessioned".
    csv_path = data_dirs.watch / "unsessioned_watch.csv"
    assert csv_path.exists()


def test_watch_rejects_garbage_json(client):
    resp = client.post("/watch", content=b"this is not json",
                       headers={"content-type": "application/json"})
    assert resp.status_code == 400


def test_watch_skips_non_dict_samples(client, data_dirs):
    """One malformed sample shouldn't reject the whole batch."""
    payload = {
        "samples": [_imu_sample(3000), "garbage", _imu_sample(3020)],
        "sessionId": "S002",
    }
    resp = client.post("/watch", json=payload)
    assert resp.status_code == 200
    _flush_watch_writers()
    with open(data_dirs.watch / "S002_watch.csv") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2


# ── POST /session/start  →  POST /session/stop ───────────────────────────────

def test_session_start_writes_sessions_csv_row(client, data_dirs):
    resp = client.post("/session/start",
                       json={"person_id": "P01", "description": "t"})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert sid == "S001"

    with open(data_dirs.sessions) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["session_id"] == "S001"
    assert rows[0]["person_id"] == "P01"
    assert rows[0]["status"] == "active"
    assert rows[0]["end_time"] == ""


def test_session_stop_finalizes_row(client, data_dirs):
    client.post("/session/start", json={"person_id": "P01"})
    resp = client.post("/session/stop")
    assert resp.status_code == 200

    with open(data_dirs.sessions) as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["status"] == "completed"
    assert rows[-1]["end_time"] != ""


def test_session_stop_uses_disk_truth_for_watch_samples(client, data_dirs):
    """Regression for S019: in the prod race window between writing CSV rows
    and snapshotting state.watch_sample_count, late WatchConnectivity batches
    can land in the CSV while state.active is already None. sessions.csv must
    reflect the on-disk row count, not the in-memory counter.

    We simulate that race deterministically by injecting watch rows directly
    through the disk path while keeping state.watch_sample_count at zero,
    then asserting /session/stop reports the disk truth."""
    import src.server.state as state_mod

    start = client.post("/session/start", json={"person_id": "P01"})
    sid = start.json()["session_id"]

    payload_in = {
        "samples": [_imu_sample(1000 + i * 20) for i in range(5)],
        "sequence": 0, "sampleRateHz": 50.0, "sessionId": sid,
    }
    assert client.post("/watch", json=payload_in).status_code == 200

    # Simulate 3 late-arrival samples that hit the CSV but not the counter
    # (mirrors the real race: state.active=None when the request is handled).
    state_mod.state.watch_sample_count = 5  # pre-race counter snapshot
    from src.server.csv_io import get_watch_writer, close_watch_writer, _watch_count_cache
    _watch_count_cache.pop(sid, None)
    path = data_dirs.watch / f"{sid}_watch.csv"
    w = get_watch_writer(path)
    for i in range(3):
        w.writerow({k: "" for k in WATCH_FIELDNAMES} | {
            "session_id": sid, "ts": 2000 + i * 20,
            "ax": 0.0, "ay": 0.0, "az": 1.0, "rx": 0.0, "ry": 0.0, "rz": 0.0,
        })
    close_watch_writer(path)

    assert client.post("/session/stop").status_code == 200

    with open(data_dirs.sessions) as f:
        rows = list(csv.DictReader(f))
    assert int(rows[-1]["watch_samples"]) == 8


def test_session_stop_without_start_is_409(client):
    resp = client.post("/session/stop")
    assert resp.status_code == 409


def test_flag_session_forces_skip_verdict(client, data_dirs):
    client.post("/session/start", json={"person_id": "P01"})
    sid = client.post("/session/stop").json()["session_id"]

    resp = client.post(f"/sessions/{sid}/flag", json={"flagged": True, "note": "pen bug"})
    assert resp.status_code == 200
    assert resp.json()["flagged"] is True
    assert resp.json()["verdict"] == "skip"

    with open(data_dirs.sessions) as f:
        row = next(r for r in csv.DictReader(f) if r["session_id"] == sid)
    assert row["flagged"] == "yes"
    assert row["flag_note"] == "pen bug"
    assert row["verdict"] == "skip"

    # Unflag → verdict recomputed from heuristic (not "skip" because manual)
    resp = client.post(f"/sessions/{sid}/flag", json={"flagged": False})
    assert resp.status_code == 200
    with open(data_dirs.sessions) as f:
        row = next(r for r in csv.DictReader(f) if r["session_id"] == sid)
    assert row["flagged"] == ""
    assert row["flag_note"] == ""


def test_flag_session_404_for_unknown_id(client):
    resp = client.post("/sessions/S999/flag", json={"flagged": True})
    assert resp.status_code == 404


def test_session_id_skips_stale_csv_via_endpoint(client, data_dirs):
    """End-to-end version of today's bug: a stale pen file blocks ID reuse."""
    (data_dirs.pen / "S005_pen.csv").write_text(
        "local_ts,local_ts_ms,timestamp,x,y,pressure,dot_type,"
        "tilt_x,tilt_y,section,owner,note,page\n"
    )
    resp = client.post("/session/start", json={"person_id": "X"})
    assert resp.json()["session_id"] == "S006"


# ── Quality endpoint (covers streams_do_not_overlap) ──────────────────────────

def test_delete_then_reuse_session_persists_new_data(client, data_dirs):
    """Regression for S004 bug: DELETE a session, then start a new one that
    reuses the freed ID — fresh watch data must land on disk.

    The leak was: delete unlinks the watch CSV but the cached writer in
    `_watch_writers` keeps a handle on the deleted inode. The next session
    under the same ID gets the stale writer and all writes go to /dev/null.
    """
    payload = {
        "samples": [_imu_sample(1000 + i * 20) for i in range(5)],
        "sequence": 0,
        "sampleRateHz": 50.0,
        "watchSentAt": 1_700_000_000_000,
        "phoneReceivedAt": 1_700_000_000_010,
        "source": "watch_phone_bridge",
    }

    # First session that gets deleted after some writes.
    r = client.post("/session/start", json={"person_id": "X"})
    sid = r.json()["session_id"]
    payload["sessionId"] = sid
    assert client.post("/watch", json=payload).status_code == 200
    assert client.post("/session/stop").status_code == 200
    assert client.delete(f"/sessions/{sid}").status_code == 200

    # Second session — _next_session_id frees the ID after delete, so this
    # gets the same SID. New samples must end up on disk.
    r2 = client.post("/session/start", json={"person_id": "Y"})
    assert r2.json()["session_id"] == sid
    payload["sessionId"] = sid
    payload["sequence"] = 1
    payload["samples"] = [_imu_sample(2000 + i * 20) for i in range(7)]
    assert client.post("/watch", json=payload).status_code == 200
    _flush_watch_writers()

    new_csv = data_dirs.watch / f"{sid}_watch.csv"
    assert new_csv.exists(), "CSV must be (re)created for the new session"
    with open(new_csv) as f:
        rows = list(csv.DictReader(f))
    # 7 fresh samples must persist — pre-fix this was 0.
    assert len(rows) == 7


def test_streams_do_not_overlap_via_validation_endpoint(client, data_dirs):
    """Pen at 10:00–10:30, Watch at 11:00–11:30 → overlap-check must fire."""
    sid = "S010"
    pen_start = 1_700_000_000_000
    watch_start = pen_start + 60 * 60 * 1000  # +1 h, no overlap

    # Append a session row that brackets both to bypass the new
    # data_outside_session_window check.
    session_start = pen_start
    session_end = watch_start + 30 * 60 * 1000

    def _iso(ms):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

    with open(data_dirs.sessions, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow({
            "session_id": sid, "person_id": "P", "description": "",
            "start_time": _iso(session_start), "end_time": _iso(session_end),
            "pen_samples": 200, "watch_samples": 200, "status": "completed",
        })

    # Pen and watch CSVs whose wall-clock ranges don't overlap.
    with open(data_dirs.pen / f"{sid}_pen.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["local_ts", "local_ts_ms", "timestamp", "x", "y",
                    "pressure", "dot_type", "tilt_x", "tilt_y",
                    "section", "owner", "note", "page"])
        for i in range(200):
            ts = pen_start + i * 100
            w.writerow([_iso(ts), ts, ts, 10.0, 20.0, 200, "PEN_MOVE",
                        60, 100, 3, 27, 746, 3])

    with open(data_dirs.watch / f"{sid}_watch.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(WATCH_FIELDNAMES)
        for i in range(200):
            ts = watch_start + i * 20
            w.writerow([_iso(ts), ts, sid, i // 10, 50.0,
                        ts, ts, ts, "watch_phone_bridge",
                        ts - 100, 0.1, 0.2, 0.9, 0.0, 0.0, 0.0])

    resp = client.get(f"/sessions/{sid}/validation")
    assert resp.status_code == 200
    issue_codes = {i["code"] for i in resp.json().get("issues", [])}
    assert "streams_do_not_overlap" in issue_codes
