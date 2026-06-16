"""Strukturiertes Runner→Server-Eventprotokoll (Ansatz B).

Die LOSO-Runner rufen optional ``on_event(dict)``. Im Web-Pfad ist das
``json_line_emitter`` (eine JSON-Zeile pro Event auf stdout); ohne Callback
bleibt das bisherige Print-Verhalten unverändert.
"""
from __future__ import annotations

import json
import sys
from typing import Callable, TextIO

RUN_START = "run_start"
FOLD_START = "fold_start"
FOLD_END = "fold_end"
RUN_END = "run_end"
ERROR = "error"

EventCallback = Callable[[dict], None]


def json_line_emitter(stream: TextIO | None = None) -> EventCallback:
    """Gibt einen Callback zurück, der jedes Event als JSON-Zeile schreibt + flusht."""
    out = stream if stream is not None else sys.stdout

    def _emit(event: dict) -> None:
        out.write(json.dumps(event) + "\n")
        out.flush()

    return _emit
