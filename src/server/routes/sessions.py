"""Session-Lifecycle und -Quality (start, stop, list, quality, validation, report)."""

import csv
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from ..broadcast import _broadcast
from ..config import (
    DATA_RAW_AIRPODS, DATA_RAW_PEN, DATA_RAW_WATCH,
    SESSIONS_CSV, SESSIONS_FIELDNAMES,
)
from ..csv_io import (
    _ensure_csv_header, _next_session_id, _pen_sample_count,
    _read_session_rows, _update_session_row,
    close_airpods_writer, close_watch_writer,
)
from ..models import SessionStartBody
from ..pen_proc import _start_pen, _stop_pen
from ..quality import (
    _session_quality, _session_validation,
    _session_report, _session_report_markdown,
)
from ..state import ActiveSession, state
from ..utils import _now_ms
from ._helpers import _new_command_id, _session_preflight_payload

router = APIRouter()


@router.get("/sessions")
async def get_sessions():
    return list(reversed(_read_session_rows()))


@router.get("/sessions/quality")
async def get_session_quality():
    rows = _read_session_rows()
    reports = [_session_quality(row) for row in rows]
    def _summary_for(key: str) -> dict[str, int]:
        return {
            "ok": sum(1 for r in reports if r.get(key, {}).get("status") == "ok"),
            "warn": sum(1 for r in reports if r.get(key, {}).get("status") == "warn"),
            "bad": sum(1 for r in reports if r.get(key, {}).get("status") == "bad"),
        }
    ml_summary = _summary_for("ml_readiness")
    recording_summary = _summary_for("recording_health")
    summary = {
        "total": len(reports),
        # Backward-compatible aliases for older dashboard code: ML readiness.
        "ok": ml_summary["ok"],
        "warn": ml_summary["warn"],
        "bad": ml_summary["bad"],
        "ml_readiness": ml_summary,
        "recording_health": recording_summary,
    }
    return {
        "summary": summary,
        "sessions": list(reversed(reports)),
    }


@router.get("/sessions/{session_id}/validation")
async def get_session_validation(session_id: str):
    result = _session_validation(session_id)
    if any(issue["code"].endswith("missing_or_unreadable") for issue in result["issues"]):
        return JSONResponse(result, status_code=404)
    return result


_ALIGNMENT_SIGMA_THRESHOLD = -2.0


def _downsample_xy(x: np.ndarray, y: np.ndarray, n: int):
    """Even-stride downsample to ≤ n points; returns parallel python lists."""
    if len(x) <= n:
        idx = np.arange(len(x))
    else:
        idx = np.linspace(0, len(x) - 1, n).astype(int)
    xs = [float(v) for v in x[idx]]
    ys = [None if not np.isfinite(v) else float(v) for v in y[idx]]
    return xs, ys


@router.get("/sessions/{session_id}/alignment")
async def get_session_alignment(session_id: str):
    """Pen↔IMU stroke-variance alignment diagnostic for the merge step.

    Returns δ, σ-confidence, the variance search curve, plus a downsampled
    watch motion-intensity timeline and stroke windows (raw + shifted) so
    the dashboard can show why the alignment landed where it did.
    """
    from src.alignment import (
        reconstruct_watch_wall_clock,
        strokes_from_dot_types,
    )
    from src.merge.merge import estimate_pen_imu_offset
    from src.merge.prep import load_csv

    pen_path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    watch_path = DATA_RAW_WATCH / f"{session_id}_watch.csv"
    if not pen_path.exists() or not watch_path.exists():
        return JSONResponse(
            {"error": "missing_csv", "pen_exists": pen_path.exists(),
             "watch_exists": watch_path.exists()},
            status_code=404,
        )

    raw_pen = load_csv(pen_path)
    raw_watch = load_csv(watch_path)

    result = estimate_pen_imu_offset(raw_pen, raw_watch)
    if result is None:
        return JSONResponse(
            {"session_id": session_id, "available": False,
             "reason": "insufficient_data_or_legacy_clock"},
            status_code=200,
        )

    sigma = (
        float(result.sigma_minimal_variance)
        if math.isfinite(result.sigma_minimal_variance) else None
    )
    applied = sigma is not None and sigma <= _ALIGNMENT_SIGMA_THRESHOLD
    delta_applied = float(result.delta_sec) if applied else 0.0

    fs = result.fine_var_series.dropna()
    curve_x, curve_y = _downsample_xy(
        fs.index.to_numpy(dtype=float), fs.values.astype(float), 200,
    )

    watch_ts = reconstruct_watch_wall_clock(raw_watch)
    df = pd.DataFrame({
        "t": watch_ts,
        "ax": pd.to_numeric(raw_watch.get("ax"), errors="coerce"),
        "ay": pd.to_numeric(raw_watch.get("ay"), errors="coerce"),
        "az": pd.to_numeric(raw_watch.get("az"), errors="coerce"),
    }).dropna().sort_values("t").reset_index(drop=True)

    if df.empty:
        timeline = {
            "duration_s": 0.0, "watch_var_t": [], "watch_var_y": [],
            "strokes_raw": [], "delta_sec_applied": delta_applied,
        }
    else:
        t0 = df["t"].iloc[0]
        rel_s = (df["t"] - t0).dt.total_seconds().to_numpy()
        diffs = np.diff(rel_s)
        fs_hz_est = (1.0 / np.median(diffs)) if len(diffs) and np.median(diffs) > 0 else 50.0
        win = max(2, int(0.2 * fs_hz_est))
        acc = np.sqrt(df[["ax", "ay", "az"]].pow(2).sum(axis=1)).to_numpy()
        var_vec = pd.Series(acc).rolling(window=win, center=True).std().to_numpy()
        var_t, var_y = _downsample_xy(rel_s, var_vec, 300)

        pen_ts = pd.to_datetime(
            pd.to_numeric(raw_pen.get("local_ts_ms"), errors="coerce"),
            unit="ms", utc=True,
        )
        pen_for = pd.DataFrame({
            "timestamp": pen_ts,
            "dot_type": raw_pen.get("dot_type", ""),
            "x": pd.to_numeric(raw_pen.get("x"), errors="coerce"),
            "y": pd.to_numeric(raw_pen.get("y"), errors="coerce"),
        }).dropna(subset=["timestamp"])
        try:
            strokes = strokes_from_dot_types(pen_for)
        except ValueError:
            strokes = pen_for.iloc[0:0]

        intervals: list[dict] = []
        if not strokes.empty:
            groups = strokes.groupby("StrokeID")["timestamp"].agg(["min", "max"])
            for _, row in groups.iterrows():
                start = (row["min"] - t0).total_seconds()
                end = (row["max"] - t0).total_seconds()
                intervals.append({"start_s": float(start), "end_s": float(end)})

        timeline = {
            "duration_s": float(rel_s[-1]) if len(rel_s) else 0.0,
            "watch_var_t": var_t,
            "watch_var_y": var_y,
            "strokes_raw": intervals,
            "delta_sec_applied": delta_applied,
        }

    improvement = None
    if (
        math.isfinite(result.minimal_variance)
        and result.minimal_variance > 0
        and math.isfinite(result.average_variance)
    ):
        improvement = float(result.average_variance / result.minimal_variance)

    return {
        "session_id": session_id,
        "available": True,
        "delta_sec": float(result.delta_sec),
        "delta_sec_applied": delta_applied,
        "sigma": sigma,
        "sigma_threshold": _ALIGNMENT_SIGMA_THRESHOLD,
        "applied": applied,
        "n_strokes": int(result.n_strokes),
        "n_imu_samples": int(result.n_imu_samples),
        "fs_hz": float(result.fs_hz) if math.isfinite(result.fs_hz) else None,
        "coarse_delta_sec": float(result.coarse_delta_sec),
        "min_variance": float(result.minimal_variance) if math.isfinite(result.minimal_variance) else None,
        "mean_variance": float(result.average_variance) if math.isfinite(result.average_variance) else None,
        "improvement_factor": improvement,
        "variance_curve": [{"d": d, "v": v} for d, v in zip(curve_x, curve_y)],
        "timeline": timeline,
    }


@router.get("/sessions/{session_id}/report")
async def get_session_report(session_id: str, format: str = "json"):
    """Pro-Session-Report — JSON oder Markdown.

    `?format=md` liefert Markdown als Download (`session_<id>_report.md`).
    """
    rows = _read_session_rows()
    row = next((r for r in rows if r.get("session_id") == session_id), None)
    if row is None:
        return JSONResponse({"error": f"Session {session_id} not found"}, status_code=404)
    report = _session_report(row)
    if format.lower() in ("md", "markdown"):
        body = _session_report_markdown(report)
        filename = f"session_{session_id}_report.md"
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return report


@router.post("/session/start")
async def session_start(body: SessionStartBody = SessionStartBody()):
    if state.active:
        return JSONResponse({"error": "Session already active"}, status_code=409)

    person_id = body.person_id
    description = body.description
    force_preflight = body.force_preflight
    preflight = _session_preflight_payload()
    if preflight["blockers"]:
        return JSONResponse({
            "error": "Preflight blocked session start",
            "preflight": preflight,
        }, status_code=428)
    if preflight["warnings"] and not force_preflight:
        return JSONResponse({
            "error": "Preflight warning",
            "preflight": preflight,
        }, status_code=428)

    session_id = _next_session_id()
    start_time = datetime.now(timezone.utc).isoformat()
    command_id = _new_command_id("start", session_id)

    state.reset_for_session()
    state.active = ActiveSession(
        session_id=session_id,
        person_id=person_id,
        description=description,
        start_time=start_time,
    )
    state.watch_command = {
        "command": "start",
        "ok": None,
        "at": _now_ms(),
        "detail": "Start command broadcast to iPhone bridge",
        "session_id": session_id,
        "command_id": command_id,
    }

    _ensure_csv_header(SESSIONS_CSV, SESSIONS_FIELDNAMES)
    with open(SESSIONS_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow({
            "session_id": session_id,
            "person_id": person_id,
            "description": description,
            "start_time": start_time,
            "end_time": "",
            "pen_samples": 0,
            "watch_samples": 0,
            "airpods_samples": 0,
            "status": "active",
        })

    # Falls der Pen noch mit "unsessioned" läuft, neu starten unter der richtigen Session-ID
    if state.pen_proc and state.pen_proc.returncode is None and state.pen_session_id == "unsessioned":
        await _stop_pen()
        await _start_pen(session_id)

    state.append_event("session", "info", f"Session {session_id} started", {
        "person_id": person_id,
        "description": description,
        "command_id": command_id,
    })
    await _broadcast({
        "type": "start",
        "session_id": session_id,
        "person_id": person_id,
        "description": description,
        "command_id": command_id,
    })
    return {
        "session_id": session_id,
        "person_id": person_id,
        "description": description,
        "command_id": command_id,
        "preflight": preflight,
    }


@router.post("/session/stop")
async def session_stop():
    if not state.active:
        return JSONResponse({"error": "No active session"}, status_code=409)

    session_id = state.active.session_id
    end_time = datetime.now(timezone.utc).isoformat()
    command_id = _new_command_id("stop", session_id)

    # Session sofort deaktivieren, damit die Watch beim nächsten Poll aufhört zu senden
    state.active = None

    state.watch_command = {
        "command": "stop",
        "ok": None,
        "at": _now_ms(),
        "detail": "Stop command broadcast to iPhone bridge",
        "session_id": session_id,
        "command_id": command_id,
    }
    state.append_event("session", "info", f"Stop requested for {session_id}", {
        "session_id": session_id,
        "command_id": command_id,
    })
    await _broadcast({"type": "stop", "session_id": session_id, "command_id": command_id})

    await _stop_pen()
    close_watch_writer(DATA_RAW_WATCH / f"{session_id}_watch.csv")
    close_airpods_writer(DATA_RAW_AIRPODS / f"{session_id}_airpods.csv")

    pen_samples = _pen_sample_count(session_id)
    watch_samples = state.watch_sample_count
    airpods_samples = state.airpods_sample_count

    _update_session_row(session_id, {
        "end_time": end_time,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
        "status": "completed",
    })

    state.append_event("session", "info", f"Session {session_id} finalized", {
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
    })
    return {
        "session_id": session_id,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
        "command_id": command_id,
    }
