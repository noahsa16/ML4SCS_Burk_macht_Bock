"""Aggregator für alle FastAPI-Routen.

Jedes Domain-Modul (``dashboard``, ``sessions``, ``pen``, ``watch``,
``airpods``, ``ws``) definiert einen eigenen ``APIRouter``. Hier
hängen wir sie an einen gemeinsamen Top-Level-Router, den ``server.py``
in die App einbindet — externer Import-Pfad bleibt
``from src.server.routes import router``.
"""

from fastapi import APIRouter

from . import airpods, dashboard, pen, sessions, watch, ws
from ._helpers import _new_command_id, _session_preflight_payload

router = APIRouter()
for _mod in (dashboard, sessions, pen, watch, airpods, ws):
    router.include_router(_mod.router)

__all__ = [
    "router",
    "_new_command_id",
    "_session_preflight_payload",
]
