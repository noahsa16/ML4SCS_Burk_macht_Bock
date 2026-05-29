"""Tests for the Focus-Tracker persistence layer and aggregator endpoints."""
from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Point focus_log at a temp file so tests don't pollute the real log."""
    import src.server.focus_log as focus_log_mod
    log_path = tmp_path / "inference_log.csv"
    monkeypatch.setattr(focus_log_mod, "INFERENCE_LOG_PATH", log_path)
    focus_log_mod.close()  # reset any open handle from a previous test
    # Also patch where routes/focus.py imports it from.
    import src.server.routes.focus as focus_route
    monkeypatch.setattr(focus_route, "INFERENCE_LOG_PATH", log_path)
    yield log_path
    focus_log_mod.close()


@pytest.fixture
def client(monkeypatch, isolated_log):
    import src.server.state as state_mod
    state_mod.state = state_mod.SessionState()
    import src.server.routes as routes_mod
    app = FastAPI()
    app.include_router(routes_mod.router)
    with TestClient(app) as c:
        yield c


def test_log_tick_writes_header_and_row(isolated_log):
    from src.server.focus_log import log_tick
    log_tick({"writing": True, "proba": 0.87, "model_id": "rf_noah", "fs_hz": 100.0})

    with open(isolated_log) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["model_id"] == "rf_noah"
    assert rows[0]["writing"] == "1"
    assert float(rows[0]["proba"]) == pytest.approx(0.87, abs=1e-4)


def test_log_tick_ignores_rate_mismatch(isolated_log):
    from src.server.focus_log import log_tick
    log_tick({"rate_mismatch": True, "writing": False, "proba": 0.0,
              "model_id": "rf_noah", "fs_hz": 50.0})
    assert not isolated_log.exists() or isolated_log.stat().st_size == 0


def test_log_tick_ignores_none(isolated_log):
    from src.server.focus_log import log_tick
    log_tick(None)  # predict() returned None
    assert not isolated_log.exists() or isolated_log.stat().st_size == 0


def test_log_tick_ignores_missing_channels(isolated_log):
    """Modern model on a Legacy (gravity-less) stream emits proba=0.0
    missing_channels ticks — they must not be logged as idle writing time."""
    from src.server.focus_log import log_tick
    log_tick({"missing_channels": True, "writing": False, "proba": 0.0,
              "model_id": "rf_all_modern", "fs_hz": 100.0})
    assert not isolated_log.exists() or isolated_log.stat().st_size == 0


def _seed_log(path, ticks):
    """Write a list of (ts_ms, writing) tuples to the log CSV."""
    import src.server.focus_log as focus_log_mod
    focus_log_mod.close()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=focus_log_mod.INFERENCE_LOG_FIELDNAMES)
        w.writeheader()
        for ts_ms, writing in ticks:
            w.writerow({
                "ts_ms": ts_ms,
                "proba": 0.9 if writing else 0.1,
                "writing": 1 if writing else 0,
                "model_id": "rf_noah",
                "fs_hz": 100.0,
            })


def test_focus_today_empty_when_log_missing(client):
    body = client.get("/focus/today").json()
    assert body["total_writing_seconds"] == 0
    assert body["stretches"] == []


def test_focus_today_groups_ticks_into_stretches(client, isolated_log):
    # Today's local midnight as the base, then schedule three writing stretches.
    midnight = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    t0 = int(midnight.timestamp() * 1000)
    ticks = []
    # Stretch 1: 60s of writing
    for i in range(60):
        ticks.append((t0 + i * 1000, True))
    # 10s idle (should break the stretch — gap > 2.5s)
    for i in range(60, 70):
        ticks.append((t0 + i * 1000, False))
    # Stretch 2: 30s writing
    for i in range(70, 100):
        ticks.append((t0 + i * 1000, True))
    _seed_log(isolated_log, ticks)

    body = client.get("/focus/today").json()
    assert len(body["stretches"]) == 2
    # Each stretch should be roughly the full duration of its writing run.
    assert body["stretches"][0]["duration_s"] >= 55
    assert body["stretches"][1]["duration_s"] >= 25
    assert body["total_writing_seconds"] >= 80


def test_focus_today_forgives_short_gaps(client, isolated_log):
    """A 1-second idle blip inside a writing stretch must not split it."""
    midnight = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
    t0 = int(midnight.timestamp() * 1000)
    ticks = []
    for i in range(30):
        ticks.append((t0 + i * 1000, True))
    ticks.append((t0 + 30 * 1000, False))  # single-tick idle gap
    for i in range(31, 60):
        ticks.append((t0 + i * 1000, True))
    _seed_log(isolated_log, ticks)

    body = client.get("/focus/today").json()
    assert len(body["stretches"]) == 1
    assert body["stretches"][0]["duration_s"] >= 55


def test_focus_today_excludes_yesterday(client, isolated_log):
    yesterday = datetime.now() - timedelta(days=1)
    yesterday = yesterday.replace(hour=15, minute=0, second=0, microsecond=0)
    ty = int(yesterday.timestamp() * 1000)
    ticks = [(ty + i * 1000, True) for i in range(60)]
    _seed_log(isolated_log, ticks)

    body = client.get("/focus/today").json()
    assert body["total_writing_seconds"] == 0


def test_focus_week_returns_7_buckets(client, isolated_log):
    body = client.get("/focus/week").json()
    assert len(body["days"]) == 7
    # Oldest first, most recent (today) last.
    assert body["days"][-1]["is_today"] is True
    assert body["days"][0]["is_today"] is False


def test_focus_week_aggregates_per_day(client, isolated_log):
    """30s writing yesterday, 60s today — each day must hold its own total."""
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    ticks = []
    ty = int(yesterday.replace(hour=11, minute=0, second=0, microsecond=0)
             .timestamp() * 1000)
    for i in range(30):
        ticks.append((ty + i * 1000, True))
    tt = int(now.replace(hour=11, minute=0, second=0, microsecond=0)
             .timestamp() * 1000)
    for i in range(60):
        ticks.append((tt + i * 1000, True))
    _seed_log(isolated_log, ticks)

    body = client.get("/focus/week").json()
    today_bucket = next(d for d in body["days"] if d["is_today"])
    yesterday_iso = yesterday.strftime("%Y-%m-%d")
    yest_bucket = next(d for d in body["days"] if d["date"] == yesterday_iso)
    assert today_bucket["writing_seconds"] >= 55
    assert yest_bucket["writing_seconds"] >= 25
