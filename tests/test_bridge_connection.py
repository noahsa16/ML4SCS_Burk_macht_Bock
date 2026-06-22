"""Bridge-Verbindungsstatus: Recency-Gate + Prune toter WS-Clients.

Hintergrund: der „phone connected"-Status hängt an der WS-Registrierung
(`client ∈ {iphone, watch_bridge}` in `ws_client_meta`), nicht am HTTP-
Datenstrom. Zwei Stale-Positive-Lücken werden hier abgesichert:

  1. `_broadcast` entfernte tote Verbindungen nur aus `ws_clients`, nicht
     aus `ws_client_meta` — `_watch_bridge_connected()` blieb dadurch wahr,
     obwohl der Send fehlgeschlagen war.
  2. `_watch_bridge_connected()` hatte kein `last_seen_ms`-Recency-Gate
     (anders als `_watch_connected()` mit 5-s-Fenster) — eine half-open-
     Verbindung, die keine Nachrichten mehr schickt, galt weiter als online.

Das Gate ist bewusst eng auf iphone/watch_bridge gescopt: Dashboard-Clients
senden nach dem `hello` nie wieder und dürfen nicht über Recency geprunt
werden (siehe static/js/core/ws.js).
"""

import asyncio

import pytest

from src.server.broadcast import _broadcast
from src.server.state import state
from src.server.status import _watch_bridge_connected
from src.server.utils import _now_ms


@pytest.fixture
def clean_ws_state():
    saved_clients = set(state.ws_clients)
    saved_meta = dict(state.ws_client_meta)
    state.ws_clients.clear()
    state.ws_client_meta.clear()
    yield
    state.ws_clients.clear()
    state.ws_clients.update(saved_clients)
    state.ws_client_meta.clear()
    state.ws_client_meta.update(saved_meta)


class _FakeWS:
    """Minimal stand-in for a Starlette WebSocket in _broadcast()."""

    def __init__(self, fail: bool):
        self.fail = fail
        self.sent: list = []

    async def send_json(self, msg):
        if self.fail:
            raise RuntimeError("connection dead")
        self.sent.append(msg)


# ── Fix #3: recency gate on _watch_bridge_connected ──────────────────────

def test_bridge_connected_true_for_fresh_iphone(clean_ws_state):
    state.ws_client_meta[1] = {"client": "iphone", "last_seen_ms": _now_ms()}
    assert _watch_bridge_connected() is True


def test_bridge_connected_false_for_stale_iphone(clean_ws_state):
    # Last message 6 s ago — past the 5 s freshness window → treated offline.
    state.ws_client_meta[1] = {"client": "iphone", "last_seen_ms": _now_ms() - 6000}
    assert _watch_bridge_connected() is False


def test_bridge_connected_ignores_fresh_dashboard(clean_ws_state):
    # Dashboards are passive receivers; they are never the bridge.
    state.ws_client_meta[1] = {"client": "dashboard", "last_seen_ms": _now_ms()}
    assert _watch_bridge_connected() is False


# ── Fix #2: _broadcast prunes ws_client_meta for dead sends ───────────────

def test_broadcast_prunes_dead_client_meta(clean_ws_state):
    ws = _FakeWS(fail=True)
    wid = id(ws)
    state.ws_clients.add(ws)
    state.ws_client_meta[wid] = {"client": "iphone", "last_seen_ms": _now_ms()}

    asyncio.run(_broadcast({"type": "status"}))

    assert ws not in state.ws_clients
    assert wid not in state.ws_client_meta


def test_broadcast_keeps_live_client_meta(clean_ws_state):
    ws = _FakeWS(fail=False)
    wid = id(ws)
    state.ws_clients.add(ws)
    state.ws_client_meta[wid] = {"client": "iphone", "last_seen_ms": _now_ms()}

    asyncio.run(_broadcast({"type": "status"}))

    assert ws in state.ws_clients
    assert wid in state.ws_client_meta
    assert ws.sent == [{"type": "status"}]
