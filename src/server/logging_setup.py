"""
Server-Logging: Python-Logs landen sowohl im rotierenden Logfile (logs/server.log)
als auch im In-Memory event_log, das via /status/debug und WS-Broadcast
auf dem Dashboard erscheint.

setup_logging() wird einmalig beim Server-Start gerufen.
"""

import logging
from logging.handlers import RotatingFileHandler

from .config import LOGS_DIR
from .state import state

_LOG_FILE = LOGS_DIR / "server.log"
_LEVEL_MAP = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class EventLogHandler(logging.Handler):
    """Schreibt Log-Records als event_log-Einträge ins SessionState."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _LEVEL_MAP.get(record.levelno, "info")
            source = record.name.split(".")[0] or "server"
            message = record.getMessage()
            data: dict = {}
            if record.exc_info:
                data["exc"] = logging.Formatter().formatException(record.exc_info)
            state.append_event(source, level, message, data or None)
        except Exception:
            # Logging darf den Server nicht crashen
            pass


def setup_logging() -> None:
    """File-Handler + EventLogHandler an root, uvicorn und fastapi anhängen."""
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    event_handler = EventLogHandler()
    event_handler.setLevel(logging.INFO)

    # Root-Logger: alles, was über logging.* läuft
    root = logging.getLogger()
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    _attach_once(root, file_handler, stream_handler, event_handler)

    # Uvicorn + FastAPI propagieren standardmäßig nicht zum Root —
    # File + Event-Handler direkt an sie hängen. StreamHandler haben sie selbst.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        _attach_once(lg, file_handler, event_handler)


def _attach_once(lg: logging.Logger, *handlers: logging.Handler) -> None:
    existing = {type(h) for h in lg.handlers}
    for h in handlers:
        if type(h) not in existing:
            lg.addHandler(h)
            existing.add(type(h))
