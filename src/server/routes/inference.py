"""Live-Inference-Modell-Auswahl.

GET /inference/models   - liste verfuegbare Joblibs aus models/ mit Metadata
GET /inference/current  - aktuelles Modell + meta
POST /inference/model   - wechselt das geladene Modell (id im Body)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..inference import MODELS, live

router = APIRouter()


class ModelSwitchBody(BaseModel):
    id: str


@router.get("/inference/models")
async def list_models() -> dict:
    available = live.list_available()
    current = live.model_id
    return {"models": available, "current": current}


@router.get("/inference/current")
async def current_model() -> dict:
    return {"current": live.model_id, "meta": live.model_meta}


@router.post("/inference/model")
async def switch_model(body: ModelSwitchBody) -> dict:
    # Why: nur Whitelist-IDs aus list_available() akzeptieren - Pfad-Traversal
    # via ../../etc/foo unmoeglich machen, ohne ueber path normalisieren zu muessen.
    available_ids = {m["id"] for m in live.list_available()}
    if body.id not in available_ids:
        raise HTTPException(
            status_code=404,
            detail=f"unknown model id: {body.id!r} (available: {sorted(available_ids)})",
        )
    path = MODELS / f"{body.id}.joblib"
    loaded = live.load_model(path)
    if loaded is None:
        raise HTTPException(status_code=500, detail="failed to load model")
    # Buffer leeren - sonst predict() das alte Modell auf den frischen Samples,
    # bevor der Switch in der Sparkline ankommt. Cleaner Restart.
    live.clear_buffer()
    return {"ok": True, "current": live.model_id, "meta": live.model_meta}
