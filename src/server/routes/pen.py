"""Pen-Logger Subprocess-Steuerung (connect / disconnect)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..pen_proc import _start_pen, _stop_pen
from ..state import state

router = APIRouter()


@router.post("/pen/connect")
async def pen_connect():
    if state.pen_proc and state.pen_proc.returncode is None:
        return JSONResponse({"error": "Pen already running"}, status_code=409)
    session_id = state.active.session_id if state.active else "unsessioned"
    result = await _start_pen(session_id)
    if "ok" in result:
        return result
    return JSONResponse({"error": result["error"]}, status_code=500)


@router.post("/pen/disconnect")
async def pen_disconnect():
    await _stop_pen()
    return {"ok": True}
