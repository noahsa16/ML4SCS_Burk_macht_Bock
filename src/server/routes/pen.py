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
    # Why: when /pen/connect is called outside a session, run pen_logger in
    # discard mode so pre-session strokes don't accumulate on disk. On
    # session start the logger is restarted with no_write=False.
    if state.active:
        result = await _start_pen(state.active.session_id, no_write=False)
    else:
        result = await _start_pen("unsessioned", no_write=True)
    if "ok" in result:
        return result
    return JSONResponse({"error": result["error"]}, status_code=500)


@router.post("/pen/disconnect")
async def pen_disconnect():
    await _stop_pen()
    return {"ok": True}
