"""Passiv-Entscheidungs-Endpoint: Idempotenz und Aggregation.

Der Kern ist die Wiederholungs-Sicherheit: WatchConnectivity kann denselben
``transferUserInfo`` erneut zustellen, und ein doppelt gezaehltes Fenster
wuerde die Schreibzeit des Tages verfaelschen.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.server.routes import passive


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(passive, "PASSIVE_LOG_PATH",
                        tmp_path / "passive_decisions.csv")
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(passive.router)
    return TestClient(app)


def _decision(start_ms: int, writing: bool = True, credit: float = 2.5) -> dict:
    return {
        "start_ms": start_ms,
        "end_ms": start_ms + 5000,
        "logit": 1.5 if writing else -1.5,
        "writing": writing,
        "credit_seconds": credit,
    }


def test_accepts_a_batch(client):
    r = client.post("/passive/decisions",
                    json={"decisions": [_decision(1000), _decision(3500)]})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "received": 2, "new": 2, "total": 2}


def test_redelivery_does_not_double_count(client):
    batch = {"decisions": [_decision(1000), _decision(3500)]}
    client.post("/passive/decisions", json=batch)
    r = client.post("/passive/decisions", json=batch)
    assert r.json()["new"] == 0
    assert r.json()["total"] == 2
    assert client.get("/passive/decisions").json()["writing_seconds"] == 5.0


def test_overlapping_batches_merge_on_start_ms(client):
    client.post("/passive/decisions",
                json={"decisions": [_decision(1000), _decision(3500)]})
    client.post("/passive/decisions",
                json={"decisions": [_decision(3500), _decision(6000)]})
    assert client.get("/passive/decisions").json()["count"] == 3


def test_idle_windows_contribute_no_writing_time(client):
    client.post("/passive/decisions",
                json={"decisions": [_decision(1000, writing=False),
                                    _decision(3500, writing=True)]})
    assert client.get("/passive/decisions").json()["writing_seconds"] == 2.5


def test_empty_log_reads_as_zero(client):
    body = client.get("/passive/decisions").json()
    assert body["count"] == 0
    assert body["writing_seconds"] == 0


def test_decisions_are_returned_in_time_order(client):
    client.post("/passive/decisions",
                json={"decisions": [_decision(6000), _decision(1000),
                                    _decision(3500)]})
    starts = [int(d["start_ms"])
              for d in client.get("/passive/decisions").json()["decisions"]]
    assert starts == sorted(starts)


def test_rejects_a_malformed_decision(client):
    r = client.post("/passive/decisions",
                    json={"decisions": [{"start_ms": "not-a-number"}]})
    assert r.status_code == 422
