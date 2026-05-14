"""Session-Lifecycle und -Quality (start, stop, list, quality, validation, report)."""

import csv
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from ..broadcast import _broadcast
from ..config import (
    DATA_RAW_AIRPODS, DATA_RAW_PEN, DATA_RAW_WATCH,
    SESSIONS_CSV, SESSIONS_FIELDNAMES,
)
from ..csv_io import (
    _delete_session_row, _ensure_csv_header, _next_session_id,
    _pen_sample_count, _read_session_rows, _update_session_row,
    close_airpods_writer, close_watch_writer,
)
from ..config import ROOT
from ..models import SessionStartBody
from ..pen_proc import _start_pen, _stop_pen
from ..quality import (
    _session_quality, _session_quality_cols, _session_validation,
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


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Hard-delete a session: removes sessions.csv row + all raw/processed
    files + cached RF model. Refuses to touch the currently-active session.
    """
    if state.active and state.active.session_id == session_id:
        return JSONResponse(
            {"error": "Cannot delete the active session — stop it first."},
            status_code=409,
        )

    rows = _read_session_rows()
    in_csv = any(r.get("session_id") == session_id for r in rows)

    # Why: collect candidate paths from all known data dirs so an old
    # CSV-less session (manual upload) still gets cleaned up.
    candidates = [
        DATA_RAW_PEN / f"{session_id}_pen.csv",
        DATA_RAW_WATCH / f"{session_id}_watch.csv",
        DATA_RAW_AIRPODS / f"{session_id}_airpods.csv",
        ROOT / "data" / "processed" / f"{session_id}_merged.csv",
        ROOT / "data" / "processed" / f"{session_id}_windows.csv",
        ROOT / "models" / f"rf_{session_id}.joblib",
    ]
    deleted_files: list[str] = []
    for p in candidates:
        try:
            if p.exists():
                p.unlink()
                deleted_files.append(p.name)
        except Exception as exc:
            state.append_event("session", "warn",
                f"Could not delete {p.name} for {session_id}: {exc}",
                {"session_id": session_id})

    csv_removed = _delete_session_row(session_id) if in_csv else False
    if not csv_removed and not deleted_files:
        return JSONResponse(
            {"error": f"Session {session_id} not found"}, status_code=404)

    state.append_event("session", "info", f"Session {session_id} deleted", {
        "session_id": session_id,
        "csv_removed": csv_removed,
        "files": deleted_files,
    })
    await _broadcast({"type": "session_deleted", "session_id": session_id})
    return {"ok": True, "session_id": session_id,
            "csv_removed": csv_removed, "files_deleted": deleted_files}


@router.post("/sessions/{session_id}/flag")
async def flag_session(session_id: str, body: dict | None = None):
    """Manually flag / unflag a session.

    Body: ``{"flagged": true|false, "note": "optional reason"}``.
    A flagged session is forced to ``verdict="skip"`` regardless of σ or
    ML status — quality cols are recomputed and persisted in sessions.csv.
    """
    rows = _read_session_rows()
    row = next((r for r in rows if r.get("session_id") == session_id), None)
    if row is None:
        return JSONResponse({"error": f"Session {session_id} not found"}, status_code=404)

    body = body or {}
    flagged = bool(body.get("flagged"))
    note = (body.get("note") or "").strip()

    updates = {
        "flagged": "yes" if flagged else "",
        "flag_note": note if flagged else "",
    }
    # Recompute the quality snapshot so verdict / issue_codes reflect the
    # flag immediately — same code path session_stop uses.
    try:
        merged = {**row, **updates}
        updates.update(_session_quality_cols(merged))
    except Exception as exc:
        state.append_event("session", "warn",
            f"Quality recompute for {session_id} (flag toggle) failed: {exc}",
            {"session_id": session_id})

    _update_session_row(session_id, updates)
    return {"session_id": session_id, "flagged": flagged, "flag_note": note,
            "verdict": updates.get("verdict", "")}


@router.post("/sessions/{session_id}/mark-test")
async def mark_session_as_test(session_id: str) -> dict:
    """Retroactively flag a study session as a test run.

    Sets study_mode='test', prepends '[TEST] ' to the description if not
    already present, and clears subject_index so the Latin Square counter
    treats this slot as available for a future real study session.
    """
    rows: list[dict] = []
    found = False
    with open(SESSIONS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("session_id") == session_id:
                found = True
                row["study_mode"] = "test"
                row["subject_index"] = ""
                desc = (row.get("description") or "").strip()
                if not desc.upper().startswith("[TEST]"):
                    row["description"] = (f"[TEST] {desc}").rstrip()
            rows.append(row)
    if not found:
        raise HTTPException(404, f"session {session_id!r} not found")
    with open(SESSIONS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SESSIONS_FIELDNAMES})
    return {"ok": True, "session_id": session_id}


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


async def _start_session_internal(
    person_id: str,
    description: str,
    force_preflight: bool,
    *,
    study_mode: str = "free",
    protocol_id: str = "",
    subject_index: int | None = None,
) -> dict:
    if state.active:
        return JSONResponse({"error": "Session already active"}, status_code=409)

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
            "study_mode": study_mode,
            "protocol_id": protocol_id,
            "subject_index": "" if subject_index is None else str(subject_index),
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


@router.post("/session/start")
async def session_start(body: SessionStartBody = SessionStartBody()):
    return await _start_session_internal(
        person_id=body.person_id,
        description=body.description,
        force_preflight=body.force_preflight,
    )


@router.post("/session/stop")
async def session_stop():
    if not state.active:
        return JSONResponse({"error": "No active session"}, status_code=409)

    session_id = state.active.session_id

    # If a study was running on this session, write a final abort marker so
    # downstream analysis knows the schedule didn't complete naturally.
    if state.study is not None:
        from time import time as _t
        from ..csv_io import write_marker as _wm
        for ev in state.study.abort(now_ms=int(_t() * 1000)):
            _wm(state.active.session_id, ev)
        state.study = None
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


    updates = {
        "end_time": end_time,
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "airpods_samples": airpods_samples,
        "status": "completed",
    }
    # Why: compute the quality snapshot AFTER the CSVs are closed so
    # the sample counts and timing reflect the final state on disk.
    try:
        updates.update(_session_quality_cols({
            "session_id": session_id,
            "status": "completed",
            **updates,
        }))
    except Exception as exc:
        state.append_event("session", "warn",
            f"Quality snapshot for {session_id} failed: {exc}", {"session_id": session_id})
    _update_session_row(session_id, updates)

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
