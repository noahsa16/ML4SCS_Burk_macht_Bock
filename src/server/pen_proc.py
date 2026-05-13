"""
Verwaltung des pen_logger.py Subprozesses.

Der Pen-Logger läuft als eigener Python-Prozess, weil er BLE-Kommunikation
blockierend betreibt. Hier wird er gestartet, gestoppt und sein stdout
in den Event-Log weitergeleitet.
"""

import asyncio
import signal
import sys
from typing import Any

from .config import ROOT
from .state import state


async def _pipe_pen_output(proc: asyncio.subprocess.Process):
    """Liest stdout des Pen-Logger-Prozesses zeilenweise und schreibt ins Event-Log."""
    if not proc.stdout:
        return
    try:
        while True:
            try:
                line = await proc.stdout.readline()
            except ValueError as e:
                # Why: asyncio's StreamReader.readline() has a 64 KB limit and
                # raises LimitOverrunError (a ValueError subclass) when a line
                # exceeds it. Previously this killed the reader task silently;
                # the pipe then filled and stalled pen_logger's BLE loop. Drain
                # the oversized chunk, log it, and keep going.
                state.append_event("pen", "warn", f"pen stdout line too long, draining: {e}")
                try:
                    await proc.stdout.read(65536)
                except Exception:
                    pass
                continue
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text:
                state.append_event("pen", "info", text[:500])
    except asyncio.CancelledError:
        pass
    except Exception as e:
        state.append_event("pen", "error", f"pen stdout reader crashed: {e!r}")
    finally:
        if proc.returncode not in (None, 0):
            state.append_event("pen", "error", f"Pen logger exited with code {proc.returncode}")


async def _start_pen(session_id: str) -> dict[str, Any]:
    """Startet pen_logger.py als Subprozess für die angegebene Session."""
    if state.pen_proc and state.pen_proc.returncode is None:
        return {"error": "Pen already running"}
    try:
        # Why: -u forces Python to line-buffer stdout. Otherwise the
        # interpreter block-buffers when stdout is a pipe — short pen
        # sessions (e.g. immediate BLE disconnect) finish before the
        # buffer flushes, and _pipe_pen_output never sees the diagnostic
        # output. -u makes every line land in the event log.
        state.pen_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u",
            str(ROOT / "pen_logger.py"), "--session", session_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        state.pen_session_id = session_id
        state.pen_log_task = asyncio.create_task(_pipe_pen_output(state.pen_proc))
        state.append_event("pen", "info", "Pen logger started", {
            "session_id": session_id,
            "pid": state.pen_proc.pid,
        })
        return {"ok": True, "session_id": session_id}
    except Exception as e:
        state.pen_proc = None
        state.pen_session_id = None
        state.append_event("pen", "error", "Could not start pen logger", {"error": str(e)})
        return {"error": str(e)}


async def _stop_pen():
    """Stoppt den laufenden Pen-Logger sauber (SIGINT, Timeout, dann SIGKILL)."""
    if state.pen_proc and state.pen_proc.returncode is None:
        try:
            state.pen_proc.send_signal(signal.SIGINT)
            await asyncio.wait_for(state.pen_proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            state.pen_proc.kill()
            await state.pen_proc.wait()
        state.append_event("pen", "info", "Pen logger stopped")
    if state.pen_log_task:
        state.pen_log_task.cancel()
        state.pen_log_task = None
    state.pen_proc = None
    state.pen_session_id = None
