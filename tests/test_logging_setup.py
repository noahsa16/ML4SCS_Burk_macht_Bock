"""Logging-Verdrahtung: ein Record darf genau einmal im File landen."""

import logging

from logging.handlers import RotatingFileHandler


def _file_handlers_along_chain(logger: logging.Logger) -> int:
    """Zählt RotatingFileHandler entlang der effektiven Propagationskette."""
    n, lg = 0, logger
    while lg is not None:
        n += sum(1 for h in lg.handlers if isinstance(h, RotatingFileHandler))
        if not lg.propagate:
            break
        lg = lg.parent
    return n


def test_uvicorn_error_records_are_written_once():
    """Regression 2026-08-08: der File-Handler hing an `uvicorn` UND
    `uvicorn.error`. Da uvicorn.error zu uvicorn propagiert, wurde jeder
    Record zweimal ins Logfile geschrieben (35 % der Zeilen waren
    unmittelbare Duplikate, inkl. identischer PID).

    `_attach_once` fängt das nicht ab — es dedupliziert nur je Logger,
    nicht entlang der Kette.
    """
    from src.server.logging_setup import setup_logging

    setup_logging()

    for name in ("uvicorn.error", "uvicorn", "uvicorn.access"):
        n = _file_handlers_along_chain(logging.getLogger(name))
        assert n <= 1, (
            f"{name}: {n} RotatingFileHandler in der Propagationskette "
            f"— jeder Record würde {n}× geschrieben"
        )


def test_setup_logging_is_idempotent():
    """Zweimal aufrufen darf keine Handler verdoppeln."""
    from src.server.logging_setup import setup_logging

    setup_logging()
    before = _file_handlers_along_chain(logging.getLogger("uvicorn.error"))
    setup_logging()
    assert _file_handlers_along_chain(logging.getLogger("uvicorn.error")) == before
