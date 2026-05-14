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
                # Why: pen_logger doesn't write dots until the user touches
                # paper. We promote BLE-pairing to a first-class flag by
                # sniffing the stdout banner — "ONLINE active" is emitted
                # once the handshake completes and the pen will start
                # streaming as soon as it's used.
                if "ONLINE active" in text:
                    state.pen_ble_ready = True
                elif "[BLE] Disconnected" in text:
                    state.pen_ble_ready = False
                state.append_event("pen", "info", text[:500])
    except asyncio.CancelledError:
        pass
    except Exception as e:
        state.append_event("pen", "error", f"pen stdout reader crashed: {e!r}")
    finally:
        if proc.returncode not in (None, 0):
            state.append_event("pen", "error", f"Pen logger exited with code {proc.returncode}")


async def _start_pen(session_id: str, *, no_write: bool = False) -> dict[str, Any]:
    """Startet pen_logger.py als Subprozess für die angegebene Session.

    no_write=True keeps the BLE pairing alive but discards every dot — used
    when the pen is connected before a session starts so pre-session writing
    never hits disk.
    """
    if state.pen_proc and state.pen_proc.returncode is None:
        return {"error": "Pen already running"}
    try:
        # Why: -u forces Python to line-buffer stdout. Otherwise the
        # interpreter block-buffers when stdout is a pipe — short pen
        # sessions (e.g. immediate BLE disconnect) finish before the
        # buffer flushes, and _pipe_pen_output never sees the diagnostic
        # output. -u makes every line land in the event log.
        extra_args = ["--no-write"] if no_write else []
        state.pen_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u",
            str(ROOT / "pen_logger.py"), "--session", session_id, *extra_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        state.pen_session_id = session_id
        state.pen_no_write = no_write
        state.pen_stop_requested = False
        state.pen_ble_ready = False
        state.pen_log_task = asyncio.create_task(_pipe_pen_output(state.pen_proc))
        state.pen_supervisor_task = asyncio.create_task(_supervise_pen(state.pen_proc))
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


async def _supervise_pen(proc: asyncio.subprocess.Process):
    """Auto-restart the pen logger when BLE drops due to idle timeout.

    The Moleskine pen disconnects itself after ~minutes of inactivity to
    save battery. Without supervision the user would lose the "paired"
    indicator (and any in-progress session) until they manually clicked
    Connect again. We watch the subprocess; if it exits while a session /
    no-write mode is still expected and the stop was not requested, we
    relaunch with the same arguments.
    """
    try:
        await proc.wait()
    except asyncio.CancelledError:
        return
    if state.pen_stop_requested:
        return
    # Subprocess died unexpectedly — restart with the same parameters.
    session_id = state.pen_session_id
    no_write = state.pen_no_write
    if not session_id:
        return
    state.append_event("pen", "warn",
                       "Pen logger exited unexpectedly — auto-reconnecting",
                       {"session_id": session_id, "no_write": no_write})
    state.pen_proc = None
    state.pen_ble_ready = False
    await asyncio.sleep(1.0)
    if state.pen_stop_requested:
        return
    await _start_pen(session_id, no_write=no_write)


async def _stop_pen():
    """Stoppt den laufenden Pen-Logger sauber (SIGINT, Timeout, dann SIGKILL)."""
    state.pen_stop_requested = True
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
    sup = getattr(state, "pen_supervisor_task", None)
    if sup:
        sup.cancel()
        state.pen_supervisor_task = None
    state.pen_proc = None
    state.pen_session_id = None
    state.pen_no_write = False
    state.pen_ble_ready = False
