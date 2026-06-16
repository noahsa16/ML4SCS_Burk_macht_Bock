"""WebSocket-Endpunkt + Client-Message-Handling."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..state import state
from ..utils import _now_ms

log = logging.getLogger("server.routes")

router = APIRouter()

# Why: Forensik-Felder des phone_status. Nur deren Änderung wird geloggt —
# der Status kommt ~1/s, Voll-Logging wäre Spam; Zähler (watch_samples …)
# ändern sich jede Sekunde und bleiben bewusst draußen. Hintergrund: beim
# S044-Vorfall (2026-06-12) war der stale stop/start-Push nicht nachweisbar,
# weil Acks und Phone-Sicht nur in-memory lagen.
_PHONE_STATUS_LOG_FIELDS = (
    "watch_reachable",
    "watch_running",
    "watch_session_id",
    "watch_upload_mode",
    "current_session_id",
    "current_command_id",
    "watch_last_command_id",
)


def _handle_ws_client_message(ws_id: int, text: str) -> None:
    """
    Verarbeitet eine eingehende WS-Nachricht. Unterstützte Typen:
      - 'hello': Client identifiziert sich (dashboard, iphone, watch_bridge)
      - 'watch_ack': Watch bestätigt einen Befehl
      - 'phone_status': iPhone-Bridge meldet Watch-Erreichbarkeit
    """
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return
    if not isinstance(msg, dict):
        return

    msg_type = msg.get("type")
    if msg_type == "hello":
        client = str(msg.get("client") or "unknown")
        state.ws_client_meta.setdefault(ws_id, {})["client"] = client
        state.ws_client_meta[ws_id]["last_seen_ms"] = _now_ms()
        if client in {"iphone", "watch_bridge"}:
            state.append_event("phone", "info", "iPhone bridge WebSocket connected")
        return

    state.ws_client_meta.setdefault(ws_id, {})["last_seen_ms"] = _now_ms()

    if msg_type == "watch_ack":
        ok = bool(msg.get("ok"))
        command_id = msg.get("command_id")
        state.watch_command = {
            "command": msg.get("command"),
            "ok": ok,
            "at": _now_ms(),
            "detail": msg.get("detail") or ("Watch acknowledged command" if ok else "Watch command failed"),
            "session_id": msg.get("session_id"),
            "command_id": command_id,
            "reply": msg.get("reply"),
        }
        state.append_event("watch", "info" if ok else "error", state.watch_command["detail"], {
            "command": msg.get("command"),
            "session_id": msg.get("session_id"),
            "command_id": command_id,
        })
        log.log(
            logging.INFO if ok else logging.WARNING,
            "watch_ack ok=%s command=%s session_id=%s command_id=%s detail=%s",
            ok, msg.get("command"), msg.get("session_id"),
            command_id, state.watch_command["detail"],
        )
    elif msg_type == "phone_status":
        meta = state.ws_client_meta.setdefault(ws_id, {})
        prev = meta.get("phone_status") or {}
        changed = {
            k: msg.get(k)
            for k in _PHONE_STATUS_LOG_FIELDS
            if msg.get(k) != prev.get(k)
        }
        if changed:
            log.info("phone_status changed ws_id=%s %s",
                     ws_id, json.dumps(changed, sort_keys=True))
        meta["phone_status"] = msg


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_id = id(websocket)
    peer = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
    state.ws_clients.add(websocket)
    state.ws_client_meta[ws_id] = {
        "client": "unknown",
        "connected_at_ms": _now_ms(),
        "last_seen_ms": _now_ms(),
        "peer": peer,
    }
    log.info("WS accepted ws_id=%s peer=%s", ws_id, peer)
    close_reason = "unknown"
    try:
        while True:
            text = await websocket.receive_text()
            _handle_ws_client_message(ws_id, text)
    except WebSocketDisconnect as e:
        close_reason = f"disconnect code={e.code}"
    except Exception:
        close_reason = "exception"
        log.exception("WS handler exception ws_id=%s peer=%s", ws_id, peer)
    finally:
        meta = state.ws_client_meta.pop(ws_id, {})
        client = meta.get("client", "unknown")
        connected_ms = _now_ms() - int(meta.get("connected_at_ms") or _now_ms())
        log.info("WS closed ws_id=%s peer=%s client=%s lived_ms=%s reason=%s",
                 ws_id, peer, client, connected_ms, close_reason)
        if client in {"iphone", "watch_bridge"}:
            state.append_event(
                "phone", "warn",
                f"iPhone bridge WebSocket disconnected ({close_reason}, lived {connected_ms} ms)",
            )
