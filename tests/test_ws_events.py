"""Persistenz von watch_ack / phone_status im Server-Log.

Forensik-Lücke aus dem S044-Vorfall (2026-06-12): stale Push-Commands
ließen sich nicht nachweisen, weil Command-Acks nur in-memory lagen.
Diese Tests sichern zu, dass jede Watch-Bestätigung und jede Änderung
des Phone-Status als Logzeile in logs/server.log landet (via Logger
"server.routes" → RotatingFileHandler).
"""

import json
import logging

import pytest

from src.server.routes.ws import _handle_ws_client_message
from src.server.state import state


@pytest.fixture
def ws_id():
    wid = 999_001
    yield wid
    state.ws_client_meta.pop(wid, None)


def _send(ws_id, payload):
    _handle_ws_client_message(ws_id, json.dumps(payload))


def test_watch_ack_is_logged(caplog, ws_id):
    caplog.set_level(logging.INFO, logger="server.routes")
    _send(ws_id, {
        "type": "watch_ack",
        "ok": True,
        "command": "stop",
        "session_id": "S044",
        "command_id": "stop|S044|abc123",
        "detail": "Watch acknowledged command",
    })
    acks = [r for r in caplog.records if "watch_ack" in r.getMessage()]
    assert len(acks) == 1
    msg = acks[0].getMessage()
    assert "stop" in msg
    assert "S044" in msg
    assert "stop|S044|abc123" in msg


def test_watch_ack_failure_logged_as_warning(caplog, ws_id):
    caplog.set_level(logging.INFO, logger="server.routes")
    _send(ws_id, {
        "type": "watch_ack",
        "ok": False,
        "command": "stop",
        "session_id": "S044",
        "command_id": "x",
        "detail": "Watch rejected command",
    })
    acks = [r for r in caplog.records if "watch_ack" in r.getMessage()]
    assert len(acks) == 1
    assert acks[0].levelno == logging.WARNING


def test_phone_status_logged_only_on_change(caplog, ws_id):
    caplog.set_level(logging.INFO, logger="server.routes")
    status = {
        "type": "phone_status",
        "watch_reachable": True,
        "watch_running": True,
        "watch_session_id": "S044",
        "watch_upload_mode": "Bridge",
        "current_session_id": "S044",
        "current_command_id": "start|S044|abc",
        "watch_last_command_id": "start|S044|abc",
        "watch_samples": 100,
    }
    _send(ws_id, status)
    baseline = [r for r in caplog.records if "phone_status" in r.getMessage()]
    assert len(baseline) == 1

    # identischer Status (nur Sample-Zähler tickt) → keine neue Zeile
    _send(ws_id, {**status, "watch_samples": 200})
    again = [r for r in caplog.records if "phone_status" in r.getMessage()]
    assert len(again) == 1

    # watch_running kippt → neue Zeile, die das geänderte Feld benennt
    _send(ws_id, {**status, "watch_running": False})
    changed = [r for r in caplog.records if "phone_status" in r.getMessage()]
    assert len(changed) == 2
    assert "watch_running" in changed[-1].getMessage()
    # unveränderte Felder werden nicht wiederholt
    assert "watch_upload_mode" not in changed[-1].getMessage()
