"""
Einstiegspunkt des FastAPI-Servers.

Hier passiert bewusst wenig — die eigentliche Logik steckt in src/server/:
  config.py     Pfade und Feldnamen
  state.py      SessionState + globales state-Objekt
  utils.py      reine Hilfsfunktionen
  csv_io.py     CSV lesen/schreiben
  status.py     Verbindungsstatus und Status-Payload
  quality.py    Session-Qualität und Validierung
  broadcast.py  WebSocket-Broadcast und Status-Loop
  pen_proc.py   Pen-Logger Subprozess
  routes.py     alle FastAPI-Endpunkte
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.server.broadcast import _broadcast, _status_loop
from src.server.config import STATIC_DIR
from src.server.csv_io import close_all_watch_writers
from src.server.logging_setup import setup_logging
from src.server.pen_proc import _stop_pen
from src.server.routes import router
from src.server.state import state


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    state.append_event("server", "info", "FastAPI server started")
    task = asyncio.create_task(_status_loop())
    yield
    task.cancel()
    await _stop_pen()
    close_all_watch_writers()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
