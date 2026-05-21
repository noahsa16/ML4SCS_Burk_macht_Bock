"""Cross-route helpers — Command-IDs und Preflight-Payload.

Liegt absichtlich außerhalb der Domain-Module, damit ``sessions.py`` und
``watch.py`` denselben Helper teilen können, ohne sich gegenseitig zu
importieren.
"""

import uuid

from ..state import state
from ..status import _status_payload
from ..utils import _safe_file_id


def _new_command_id(command: str, session_id: str | None = None) -> str:
    scope = _safe_file_id(session_id or "manual")
    return f"{command}-{scope}-{uuid.uuid4().hex[:8]}"


def _session_preflight_payload(*, test_mode: bool = False) -> dict:
    # Why: test_mode runs (pilots, UI screenshots, dry-runs) don't have to
    # carry the hardware-attached invariants. Watch-related blockers get
    # demoted to warnings so the operator can still see the issue but
    # force_preflight=True (auto-set in test_mode) lets the start through.
    status = _status_payload()
    blockers = []
    warnings = []
    watch_bucket = warnings if test_mode else blockers

    if not status.get("watch_bridge_connected"):
        watch_bucket.append({
            "code": "iphone_bridge_missing",
            "message": "iPhone bridge WebSocket is not connected.",
        })
    if not status.get("watch_polling"):
        watch_bucket.append({
            "code": "watch_not_polling",
            "message": "Apple Watch has not polled the iPhone bridge recently.",
        })
    if not status.get("pen_connected"):
        warnings.append({
            "code": "pen_disconnected",
            "message": "Smart Pen logger is not connected; the session can start, but pen data will be missing.",
        })

    compact_status = {
        "session_active": status.get("session_active"),
        "watch_bridge_connected": status.get("watch_bridge_connected"),
        "watch_polling": status.get("watch_polling"),
        "watch_poll_age_ms": status.get("watch_poll_age_ms"),
        "watch_reachable": status.get("watch_reachable"),
        "watch_running": status.get("watch_running"),
        "watch_command": status.get("watch_command"),
        "iphone_connected": status.get("watch_bridge_connected"),
        "pen_connected": status.get("pen_connected"),
        "pen_pid": status.get("pen_pid"),
        "connected_clients": status.get("connected_clients"),
    }
    return {
        "ok": not blockers and not warnings,
        "can_start": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "status": compact_status,
    }
