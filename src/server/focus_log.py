"""Append-only CSV der Live-Inference-Ticks fuer den Focus-Tracker.

Jeder _status_loop-Tick mit einer Predict-Antwort wird hier eine Zeile.
Das ist die Datenquelle fuer den /focus-Tab: Schreibphasen heute, Wochen-
Aggregat, langfristige Zeitreihen. Persistiert ueber Server-Restarts -
das war der Grund warum LiveInference.today_writing_seconds NICHT die
Wahrheit war (vgl. focus_tracker_pivot.md).

Schema:
    ts_ms       Server-Wall-Clock (int, Unix-ms) - identisch zum Watch/Pen-CSV
    proba       Wahrscheinlichkeit Schreiben (float 0..1)
    writing     0/1 (proba >= 0.5 nach Modell-Threshold)
    model_id    welches joblib geladen war (rf_noah / rf_all_live / ...)
    fs_hz       beobachtete Buffer-Rate (float)

Schreibfrequenz ~1 Hz -> ~86k Zeilen/Tag, ~3 MB/Tag. Keine Rotation,
keine Compression - die Datei darf wachsen. Read-Side aggregiert pro
Tag, Disk-IO ist bei 1 Hz keine Sorge.
"""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import Optional

from .config import ROOT

log = logging.getLogger(__name__)

INFERENCE_LOG_PATH = ROOT / "data" / "inference_log.csv"
INFERENCE_LOG_FIELDNAMES = ["ts_ms", "proba", "writing", "model_id", "fs_hz"]

_writer: Optional[csv.DictWriter] = None
_file = None


def _ensure_writer() -> Optional[csv.DictWriter]:
    """Lazy-init the file handle + DictWriter. Returns None on filesystem error."""
    global _writer, _file
    if _writer is not None:
        return _writer
    try:
        INFERENCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        is_new = not INFERENCE_LOG_PATH.exists()
        _file = open(INFERENCE_LOG_PATH, "a", newline="")
        _writer = csv.DictWriter(_file, fieldnames=INFERENCE_LOG_FIELDNAMES)
        if is_new:
            _writer.writeheader()
            _file.flush()
        return _writer
    except OSError:
        log.exception("focus_log: failed to open %s", INFERENCE_LOG_PATH)
        return None


def log_tick(inf: dict) -> None:
    """Append one inference tick to the log. Ignores guard ticks.

    `inf` is the dict returned by LiveInference.predict() — see inference.py.
    rate_mismatch- und missing_channels-Ticks tragen proba=0.0 ohne echtes
    Predict; sie würden den "writing time tracked"-Counter fälschlich als
    idle-Zeit zählen, also nicht loggen.
    """
    if not inf or inf.get("rate_mismatch") or inf.get("missing_channels"):
        return
    w = _ensure_writer()
    if w is None:
        return
    try:
        w.writerow({
            "ts_ms": int(time.time() * 1000),
            "proba": round(float(inf.get("proba", 0.0)), 4),
            "writing": 1 if inf.get("writing") else 0,
            "model_id": inf.get("model_id") or "",
            "fs_hz": round(float(inf.get("fs_hz", 0.0)), 1),
        })
        _file.flush()  # type: ignore[union-attr]
    except (OSError, ValueError):
        log.exception("focus_log: failed to append tick")


def close() -> None:
    """Flush + close the log handle. Idempotent. For tests + clean shutdown."""
    global _writer, _file
    try:
        if _file is not None:
            _file.close()
    finally:
        _writer = None
        _file = None
