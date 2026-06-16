"""FastAPI-Router für das Web-Training-Cockpit (`/training/*`).

Startet/stoppt RF-LOSO-Läufe, listet die nicht-destruktive Run-Historie,
promotet einen Lauf zur Headline und lädt einen Lauf temporär in die
Live-Inference (Sandbox). RUNS_ROOT wird zur Call-Zeit gelesen, damit Tests
den Pfad monkeypatchen können.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.training import registry
from .. import training as training_mod
from .. import training_runs
from ..inference import live

router = APIRouter(prefix="/training", tags=["training"])


class StartBody(BaseModel):
    model: str = "rf"
    pool: str = "legacy"
    by: str = "person"


@router.get("/models")
def models():
    return registry.list_models()


@router.get("/current")
def current():
    return training_mod.run.snapshot()


@router.post("/start")
async def start(body: StartBody):
    if not registry.validate(body.model, body.pool):
        raise HTTPException(400, f"invalid model/pool: {body.model}/{body.pool}")
    if training_mod.run.is_busy():
        raise HTTPException(409, "a training run is already in progress")
    return await training_mod.run.start(body.model, body.pool, body.by)


@router.post("/stop")
async def stop():
    return await training_mod.run.stop()


@router.get("/runs")
def runs():
    return training_runs.list_runs(training_runs.RUNS_ROOT)


@router.post("/runs/{run_id}/promote")
def promote(run_id: str):
    try:
        training_runs.promote(run_id, root=training_runs.RUNS_ROOT)
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} not found")
    return {"ok": True}


@router.post("/runs/{run_id}/sandbox")
def sandbox(run_id: str):
    path = training_runs.RUNS_ROOT / run_id / "model.joblib"
    if not path.exists():
        raise HTTPException(404, f"no model.joblib for run {run_id}")
    ok = live.load_sandbox(path)
    return {"ok": ok, "model_id": "sandbox"}
