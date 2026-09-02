"""Empfang der Passiv-Tracker-Entscheidungen von der Watch.

Die Watch klassifiziert im Hintergrund aus ``CMSensorRecorder``-Daten und
schickt die Fenster-Urteile ueber das iPhone hierher. Anders als der
Roh-IMU-Strom ist das ein kleiner, abgeleiteter Datensatz:
ein Eintrag pro 5-s-Fenster statt 50 Samples pro Sekunde.

**Idempotent per ``start_ms``.** Ein Fenster-Urteil ist eindeutig durch
seinen Startzeitpunkt bestimmt, und WatchConnectivity kann denselben
Transfer wiederholen. Ein erneut geliefertes ``start_ms`` ueberschreibt
den vorhandenen Eintrag, statt ihn ein zweites Mal zu zaehlen — sonst
wuerde eine Wiederholung die Schreibzeit des Tages verdoppeln.

Der Log ist gitignored (abgeleitete Probandendaten) und liegt neben dem
Live-Inference-Log.
"""
from __future__ import annotations

import csv
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import ROOT

router = APIRouter()

PASSIVE_LOG_PATH = ROOT / "data" / "passive_decisions.csv"

FIELDNAMES = ["start_ms", "end_ms", "logit", "writing", "credit_seconds", "source"]


class PassiveDecision(BaseModel):
    start_ms: int
    end_ms: int
    logit: float
    writing: bool
    credit_seconds: float = Field(default=2.5, ge=0)


class PassiveDecisionsBody(BaseModel):
    decisions: list[PassiveDecision]
    source: str = "watch_passive"


def _read_existing() -> dict[int, dict]:
    if not PASSIVE_LOG_PATH.exists():
        return {}
    rows: dict[int, dict] = {}
    with PASSIVE_LOG_PATH.open(newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                rows[int(row["start_ms"])] = row
            except (KeyError, TypeError, ValueError):
                # Why: eine defekte Zeile darf den ganzen Log nicht entwerten.
                continue
    return rows


def _write_all(rows: dict[int, dict]) -> None:
    PASSIVE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PASSIVE_LOG_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for start_ms in sorted(rows):
            writer.writerow(rows[start_ms])
    tmp.replace(PASSIVE_LOG_PATH)


@router.post("/passive/decisions")
def post_passive_decisions(body: PassiveDecisionsBody) -> dict:
    """Nimmt einen Batch entgegen und meldet, wie viel davon neu war."""
    existing = _read_existing()
    before = len(existing)
    for d in body.decisions:
        existing[d.start_ms] = {
            "start_ms": d.start_ms,
            "end_ms": d.end_ms,
            "logit": d.logit,
            "writing": int(d.writing),
            "credit_seconds": d.credit_seconds,
            "source": body.source,
        }
    _write_all(existing)
    return {
        "ok": True,
        "received": len(body.decisions),
        "new": len(existing) - before,
        "total": len(existing),
    }


@router.get("/passive/decisions")
def get_passive_decisions() -> dict:
    """Alle bekannten Urteile plus die daraus abgeleitete Schreibzeit."""
    rows = _read_existing()
    writing_seconds = sum(
        float(r.get("credit_seconds") or 0)
        for r in rows.values()
        if str(r.get("writing")) in ("1", "True", "true")
    )
    return {
        "ok": True,
        "count": len(rows),
        "writing_seconds": writing_seconds,
        "decisions": [rows[k] for k in sorted(rows)],
    }
