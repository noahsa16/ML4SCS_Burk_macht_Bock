import asyncio
import csv
import math
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).parent
DATA_RAW_WATCH = ROOT / "data" / "raw" / "watch"
DATA_RAW_PEN   = ROOT / "data" / "raw" / "pen"
SESSIONS_CSV   = ROOT / "data" / "sessions.csv"
DASHBOARD_HTML = ROOT / "dashboard.html"

DATA_RAW_WATCH.mkdir(parents=True, exist_ok=True)
DATA_RAW_PEN.mkdir(parents=True, exist_ok=True)

WATCH_FIELDNAMES = [
    "local_ts", "session_id", "sequence", "sample_rate_hz",
    "watch_sent_at", "phone_received_at", "source",
    "ts", "ax", "ay", "az", "rx", "ry", "rz",
]
SESSIONS_FIELDNAMES = [
    "session_id", "person_id", "start_time", "end_time",
    "pen_samples", "watch_samples", "status",
]

if not SESSIONS_CSV.exists():
    with open(SESSIONS_CSV, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writeheader()


# ── Shared state ──────────────────────────────────────────────────────────────

class SessionState:
    def __init__(self):
        self.active: Optional[dict] = None       # {session_id, person_id, start_time}
        self.pen_proc = None                      # asyncio.subprocess.Process
        self.pen_session_id: Optional[str] = None
        self.watch_sample_count: int = 0
        self.server_start: float = time.time()
        self.ws_clients: set[WebSocket] = set()
        self.last_watch_time: float = 0.0        # for "watch connected" check
        self.chart_buffer: list[dict] = []        # [{t, mag, pen_writing}, ...] max 60
        self.chart_window_mags: list[float] = []  # magnitudes in current 1s window

state = SessionState()


# ── Session CSV helpers ───────────────────────────────────────────────────────

def _next_session_id() -> str:
    nums = []
    try:
        with open(SESSIONS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                sid = row.get("session_id", "")
                if sid.startswith("S") and sid[1:].isdigit():
                    nums.append(int(sid[1:]))
    except Exception:
        pass
    return f"S{(max(nums) + 1 if nums else 1):03d}"


def _pen_sample_count(session_id: str) -> int:
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return 0
    try:
        with open(path, newline="") as f:
            return max(0, sum(1 for _ in f) - 1)  # subtract header
    except Exception:
        return 0


def _pen_last_dot_type(session_id: str) -> str:
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return ""
    try:
        last = None
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                last = row
        return last["dot_type"] if last else ""
    except Exception:
        return ""


def _pen_connected() -> bool:
    return state.pen_proc is not None and state.pen_proc.returncode is None


def _update_session_row(session_id: str, updates: dict):
    rows = []
    try:
        with open(SESSIONS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                if row["session_id"] == session_id:
                    row.update(updates)
                rows.append(row)
    except Exception:
        return
    with open(SESSIONS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


# ── WebSocket broadcast ───────────────────────────────────────────────────────

async def _broadcast(msg: dict):
    dead = set()
    for ws in state.ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    state.ws_clients -= dead


async def _status_loop():
    while True:
        await asyncio.sleep(1.0)
        sid = state.active["session_id"] if state.active else None
        pen_samples = _pen_sample_count(sid) if sid else 0
        pen_connected = _pen_connected()
        pen_writing = _pen_last_dot_type(sid) in ("PEN_DOWN", "PEN_MOVE") if sid else False
        watch_connected = (time.time() - state.last_watch_time) < 5.0 if state.last_watch_time else False

        # Update rolling chart buffer (one point per second)
        if state.active:
            mag = (
                sum(state.chart_window_mags) / len(state.chart_window_mags)
                if state.chart_window_mags else 0.0
            )
            state.chart_buffer.append({
                "t": int(time.time() * 1000),
                "mag": round(mag, 3),
                "pen_writing": pen_writing,
            })
            if len(state.chart_buffer) > 60:
                state.chart_buffer = state.chart_buffer[-60:]
        state.chart_window_mags = []

        await _broadcast({
            "type": "status",
            "session_active": state.active is not None,
            "session_id": sid,
            "person_id": state.active["person_id"] if state.active else None,
            "start_time": state.active["start_time"] if state.active else None,
            "watch_samples": state.watch_sample_count,
            "pen_samples": pen_samples,
            "pen_connected": pen_connected,
            "watch_connected": watch_connected,
            "uptime_seconds": int(time.time() - state.server_start),
            "chart": state.chart_buffer[-10:],
        })


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_status_loop())
    yield
    task.cancel()
    if state.pen_proc and state.pen_proc.returncode is None:
        state.pen_proc.send_signal(signal.SIGINT)


app = FastAPI(lifespan=lifespan)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard():
    return FileResponse(DASHBOARD_HTML)


@app.get("/status")
async def get_status():
    sid = state.active["session_id"] if state.active else None
    return {
        "pen_connected": _pen_connected(),
        "watch_connected": (time.time() - state.last_watch_time) < 5.0 if state.last_watch_time else False,
        "watch_samples": state.watch_sample_count,
        "pen_samples": _pen_sample_count(sid) if sid else 0,
        "session_active": state.active is not None,
        "session_id": sid,
        "person_id": state.active["person_id"] if state.active else None,
        "start_time": state.active["start_time"] if state.active else None,
        "uptime_seconds": int(time.time() - state.server_start),
    }


@app.get("/sessions")
async def get_sessions():
    sessions = []
    try:
        with open(SESSIONS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                sessions.append(row)
    except Exception:
        pass
    return list(reversed(sessions))


@app.post("/session/start")
async def session_start(request: Request):
    if state.active:
        return JSONResponse({"error": "Session already active"}, status_code=409)

    body = await request.json()
    person_id = body.get("person_id", "unknown").strip() or "unknown"
    session_id = _next_session_id()
    start_time = datetime.now(timezone.utc).isoformat()

    state.active = {"session_id": session_id, "person_id": person_id, "start_time": start_time}
    state.watch_sample_count = 0
    state.chart_buffer = []
    state.chart_window_mags = []

    with open(SESSIONS_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow({
            "session_id": session_id,
            "person_id": person_id,
            "start_time": start_time,
            "end_time": "",
            "pen_samples": 0,
            "watch_samples": 0,
            "status": "active",
        })

    if state.pen_proc and state.pen_proc.returncode is None and state.pen_session_id == "unsessioned":
        await _stop_pen()
        await _start_pen(session_id)

    await _broadcast({"type": "start", "session_id": session_id, "person_id": person_id})
    return {"session_id": session_id, "person_id": person_id}


@app.post("/session/stop")
async def session_stop():
    if not state.active:
        return JSONResponse({"error": "No active session"}, status_code=409)

    session_id = state.active["session_id"]
    end_time = datetime.now(timezone.utc).isoformat()

    await _stop_pen()

    pen_samples = _pen_sample_count(session_id)
    watch_samples = state.watch_sample_count

    _update_session_row(session_id, {
        "end_time": end_time,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "status": "completed",
    })

    state.active = None

    await _broadcast({"type": "stop", "session_id": session_id})
    return {"session_id": session_id, "pen_samples": pen_samples, "watch_samples": watch_samples}


async def _stop_pen():
    if state.pen_proc and state.pen_proc.returncode is None:
        try:
            state.pen_proc.send_signal(signal.SIGINT)
            await asyncio.wait_for(state.pen_proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            state.pen_proc.kill()
            await state.pen_proc.wait()
    state.pen_proc = None
    state.pen_session_id = None


async def _start_pen(session_id: str) -> dict:
    if state.pen_proc and state.pen_proc.returncode is None:
        return {"error": "Pen already running"}
    try:
        state.pen_proc = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "pen_logger.py"), "--session", session_id,
        )
        state.pen_session_id = session_id
        return {"ok": True, "session_id": session_id}
    except Exception as e:
        state.pen_proc = None
        state.pen_session_id = None
        return {"error": str(e)}


@app.post("/pen/connect")
async def pen_connect():
    if state.pen_proc and state.pen_proc.returncode is None:
        return JSONResponse({"error": "Pen already running"}, status_code=409)
    session_id = state.active["session_id"] if state.active else "unsessioned"
    result = await _start_pen(session_id)
    if "ok" in result:
        return result
    return JSONResponse({"error": result["error"]}, status_code=500)


@app.post("/pen/disconnect")
async def pen_disconnect():
    await _stop_pen()
    return {"ok": True}


@app.post("/watch/start")
async def watch_cmd_start():
    sid = state.active["session_id"] if state.active else None
    pid = state.active["person_id"] if state.active else "manual"
    await _broadcast({"type": "start", "session_id": sid, "person_id": pid})
    return {"ok": True}


@app.post("/watch/stop")
async def watch_cmd_stop():
    await _broadcast({"type": "stop", "session_id": None})
    return {"ok": True}


@app.post("/watch")
async def receive_watch(request: Request):
    payload = await request.json()
    if isinstance(payload, list):
        envelope, batch = {}, payload
    else:
        envelope = payload
        batch = envelope.get("samples", [])

    session_id = (
        state.active["session_id"] if state.active
        else envelope.get("sessionId", "unsessioned")
    )
    csv_path = DATA_RAW_WATCH / f"{session_id}_watch.csv"
    write_header = not csv_path.exists()

    local_ts = datetime.now(timezone.utc).isoformat()
    state.last_watch_time = time.time()

    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WATCH_FIELDNAMES)
        if write_header:
            w.writeheader()
        for s in batch:
            w.writerow({
                "local_ts":          local_ts,
                "session_id":        session_id,
                "sequence":          envelope.get("sequence"),
                "sample_rate_hz":    envelope.get("sampleRateHz"),
                "watch_sent_at":     envelope.get("watchSentAt"),
                "phone_received_at": envelope.get("phoneReceivedAt"),
                "source":            envelope.get("source"),
                "ts":  s.get("ts"),
                "ax":  s.get("ax"),
                "ay":  s.get("ay"),
                "az":  s.get("az"),
                "rx":  s.get("rx"),
                "ry":  s.get("ry"),
                "rz":  s.get("rz"),
            })
            # Accumulate acc magnitude for live chart
            try:
                mag = math.sqrt(s["ax"]**2 + s["ay"]**2 + s["az"]**2)
                state.chart_window_mags.append(mag)
            except (KeyError, TypeError):
                pass

    if state.active:
        state.watch_sample_count += len(batch)

    return {"ok": True, "samples": len(batch)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.ws_clients.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
