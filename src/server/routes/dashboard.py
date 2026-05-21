"""Dashboard, Status- und Debug-Endpunkte (HTML + In-Memory-State only)."""

import dataclasses
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..config import DASHBOARD_HTML
from ..csv_io import _read_session_rows
from ..state import state
from ..status import _status_payload
from ._helpers import _session_preflight_payload

router = APIRouter()


@router.get("/")
async def dashboard():
    # no-store verhindert, dass der Browser die Dashboard-HTML cached.
    # CSS/Markup-Änderungen erscheinen damit beim nächsten normalen Reload,
    # ohne dass wir ständig Cache-Buster ans <script src> hängen müssen.
    return FileResponse(
        DASHBOARD_HTML,
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@router.get("/status")
async def get_status():
    return _status_payload()


@router.get("/session/preflight")
async def session_preflight(test_mode: bool = False):
    return _session_preflight_payload(test_mode=test_mode)


@router.get("/debug/package")
async def debug_package():
    status = _status_payload()
    return {
        "version": "debug_package_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preflight": _session_preflight_payload(),
        "status": status,
        "active_session": dataclasses.asdict(state.active) if state.active else None,
        "watch_command": state.watch_command,
        "connected_clients": list(state.ws_client_meta.values()),
        "recent_events": list(state.event_log)[-200:],
        "recent_samples": list(state.sample_log)[-200:],
        "recent_sessions": list(reversed(_read_session_rows()))[:20],
    }
