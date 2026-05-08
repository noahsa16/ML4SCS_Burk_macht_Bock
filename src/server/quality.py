"""
Session-Qualität, Validierung und Reports.

Drei Sichten auf dieselben Fakten — alle gehen über _session_facts():
  _session_quality(row)    Listen-Ansicht (alle Sessions, klein)
  _session_validation(id)  Detail-Ansicht für Dashboard-Modal
  _session_report(row)     Voll angereicherter Report (Export)

Issues kommen aus ISSUE_SPECS (siehe ``issues.py``) — pro Code stehen
check, threshold, rationale und Severity-Map zentral; _make_issue()
liefert konsistente Dicts mit observed/threshold/rationale für Reports
und Tooltips.

Read-only — kein Zugriff auf globalen State, keine Seiteneffekte.

Modulare Aufteilung:
  issues.py     IssueSpec, ISSUE_SPECS, Severity-/Score-Helfer
  timelines.py  CSV → Timeline-Strukturen, Clock-Summaries, AirPods-Stats
  sync.py       Pen↔IMU Sync-Diagnostik (Stroke-Varianz + Tap-Matching)
  quality.py    _session_facts → _build_issues → drei Views (hier)
"""

from datetime import datetime, timezone
from statistics import median
from typing import Any

from .config import DATA_RAW_AIRPODS, DATA_RAW_PEN, DATA_RAW_WATCH
from .issues import (
    IssueSpec, ISSUE_SPECS,  # re-exported für externe Konsumenten
    _COUNT_TOL_FLOOR, _COUNT_TOL_PCT, _COVERAGE_PCT_MIN,
    _PEN_IN_RANGE_PCT_MIN, _SEVERITY_ORDER,
    _SYNC_SIGMA_OK_MAX, _SYNC_SIGMA_WEAK_MAX,
    _TARGET_AIRPODS_HZ, _TARGET_WATCH_HZ,
    _WATCH_HZ_MAX, _WATCH_HZ_MIN,
    _make_issue, _quality_status, _score_payload,
)
from .sync import _estimate_sync_via_pen_match, _sync_diagnostic
from .timelines import (
    _airpods_summary, _clock_summary, _load_pen_timeline,
    _load_watch_timeline, _pen_intervals,
)
from .utils import _as_int, _parse_iso


# ── Fact-Bag: einmal rechnen, mehrmals projizieren ────────────────────────────

# session_id → ((watch_mtime_ns, pen_mtime_ns, sessions_row_hash), facts)
_facts_cache: dict[str, tuple[tuple, dict[str, Any]]] = {}


def _session_facts(row: dict[str, str]) -> dict[str, Any]:
    """
    Berechnet alle abgeleiteten Fakten für eine Session **einmal**.
    Quality-, Validation- und Report-Views lesen daraus.
    """
    sid = row.get("session_id", "")
    watch_path = DATA_RAW_WATCH / f"{sid}_watch.csv"
    pen_path = DATA_RAW_PEN / f"{sid}_pen.csv"
    airpods_path = DATA_RAW_AIRPODS / f"{sid}_airpods.csv"
    watch_mtime = int(watch_path.stat().st_mtime_ns) if watch_path.exists() else 0
    pen_mtime = int(pen_path.stat().st_mtime_ns) if pen_path.exists() else 0
    airpods_mtime = int(airpods_path.stat().st_mtime_ns) if airpods_path.exists() else 0
    cache_key = (watch_mtime, pen_mtime, airpods_mtime, hash(tuple(sorted(row.items()))))
    if sid in _facts_cache and _facts_cache[sid][0] == cache_key:
        return _facts_cache[sid][1]

    watch_rows, watch_err = _load_watch_timeline(sid)
    pen_rows, pen_err = _load_pen_timeline(sid)

    accel_rows = sum(1 for r in watch_rows if r["has_accel"])
    gyro_rows = sum(1 for r in watch_rows if r["has_gyro"])
    server_time_rows = sum(1 for r in watch_rows if r["has_server_ms"])
    pen_server_time_rows = sum(1 for r in pen_rows if r["has_local_ts_ms"])

    # Sequence-Lücken
    last_seq = None
    distinct_seqs: list[int] = []
    for r in watch_rows:
        seq = r.get("sequence")
        if seq is not None and seq != last_seq:
            distinct_seqs.append(seq)
            last_seq = seq
    sequence_gaps = sum(
        cur - prev - 1 for prev, cur in zip(distinct_seqs, distinct_seqs[1:]) if cur > prev + 1
    )

    # Hz-Schätzung
    watch_ts_values = [r["source_ts"] for r in watch_rows if r["source_ts"] is not None]
    watch_diffs = [b - a for a, b in zip(watch_ts_values, watch_ts_values[1:]) if b > a]
    median_dt_ms = median(watch_diffs) if watch_diffs else None
    watch_est_hz = (1000 / median_dt_ms) if median_dt_ms else None

    # Session-Dauer und erwartete Sample-Zahl bei Target-Hz
    start = _parse_iso(row.get("start_time", ""))
    end = _parse_iso(row.get("end_time", ""))
    duration_seconds = (end - start).total_seconds() if start and end and end > start else None
    watch_source_duration = (
        (max(watch_ts_values) - min(watch_ts_values)) / 1000
        if len(watch_ts_values) > 1 else None
    )
    expected_duration = watch_source_duration or duration_seconds
    expected_watch_samples = int(expected_duration * _TARGET_WATCH_HZ) if expected_duration else None

    # Pen-Jahre (für Clock-Mismatch-Info)
    pen_ts_values = [r["source_ts"] for r in pen_rows if r["source_ts"] is not None]
    pen_timestamp_years: list[int] = []
    for ts in pen_ts_values:
        try:
            pen_timestamp_years.append(datetime.fromtimestamp(ts / 1000, tz=timezone.utc).year)
        except (OSError, OverflowError, ValueError):
            pass

    # Clock-Summaries und Intervalle
    watch_clock = _clock_summary(watch_rows, "total_samples")
    pen_clock = _clock_summary(pen_rows, "total_dots")
    intervals = _pen_intervals(pen_rows)

    # Coverage
    watch_local_start = watch_clock.get("start_ms")
    watch_local_end = watch_clock.get("end_ms")
    pen_local_dots = [r for r in pen_rows if r.get("local_ts") is not None]
    pen_dots_in_watch_range = [
        r for r in pen_local_dots
        if watch_local_start is not None and watch_local_end is not None
        and watch_local_start <= r["local_ts"] <= watch_local_end
    ]
    pen_in_range_pct = (
        len(pen_dots_in_watch_range) / len(pen_local_dots) if pen_local_dots else None
    )

    # Gemeinsame Aufzeichnungsdauer (Wall-Clock-Overlap in Sekunden)
    pen_local_start = pen_clock.get("start_ms")
    pen_local_end = pen_clock.get("end_ms")
    common_overlap_seconds = None
    if None not in (watch_local_start, watch_local_end, pen_local_start, pen_local_end):
        ov_start = max(watch_local_start, pen_local_start)
        ov_end = min(watch_local_end, pen_local_end)
        if ov_end > ov_start:
            common_overlap_seconds = round((ov_end - ov_start) / 1000, 3)
        else:
            common_overlap_seconds = 0.0

    # Effektive Schreibzeit (Summe aller PEN_DOWN→PEN_UP-Intervalle)
    writing_ms = sum(
        i["duration_ms"] for i in intervals if i.get("duration_ms") is not None
    )
    writing_seconds = round(writing_ms / 1000, 3) if writing_ms else 0.0
    pen_dur = pen_clock.get("duration_seconds") or 0
    writing_fraction = (writing_seconds / pen_dur) if pen_dur else None

    # Counts vs sessions.csv
    session_watch_samples = _as_int(row.get("watch_samples")) or 0
    session_pen_samples = _as_int(row.get("pen_samples")) or 0
    watch_count_delta = abs(len(watch_rows) - session_watch_samples)
    watch_count_tolerance = max(_COUNT_TOL_FLOOR, int(max(len(watch_rows), session_watch_samples) * _COUNT_TOL_PCT))
    pen_count_delta = abs(len(pen_rows) - session_pen_samples)
    pen_count_tolerance = max(_COUNT_TOL_FLOOR, int(max(len(pen_rows), session_pen_samples) * _COUNT_TOL_PCT))

    sync_estimate = _estimate_sync_via_pen_match(sid)

    # AirPods (lightweight summary; optional stream)
    airpods_summary = _airpods_summary(sid)
    session_airpods_samples = _as_int(row.get("airpods_samples")) or 0
    airpods_count_delta = abs(airpods_summary["row_count"] - session_airpods_samples)
    airpods_count_tolerance = max(
        _COUNT_TOL_FLOOR,
        int(max(airpods_summary["row_count"], session_airpods_samples) * _COUNT_TOL_PCT),
    )
    airpods_expected = (
        int(expected_duration * _TARGET_AIRPODS_HZ) if expected_duration else None
    )

    facts = {
        "session_id": sid,
        "row": row,
        "is_active": row.get("status") == "active",
        "duration_seconds": duration_seconds,
        "watch": {
            "rows": watch_rows,
            "row_count": len(watch_rows),
            "accel_rows": accel_rows,
            "gyro_rows": gyro_rows,
            "server_time_rows": server_time_rows,
            "ts_values": watch_ts_values,
            "median_dt_ms": median_dt_ms,
            "estimated_hz": watch_est_hz,
            "sequence_gaps": sequence_gaps,
            "sequence_batches": len(distinct_seqs),
            "clock": watch_clock,
            "expected_samples": expected_watch_samples,
            "session_csv_count": session_watch_samples,
            "count_delta": watch_count_delta,
            "count_tolerance": watch_count_tolerance,
            "load_error": watch_err,
            "path": str(watch_path),
            "exists": watch_path.exists(),
        },
        "pen": {
            "rows": pen_rows,
            "row_count": len(pen_rows),
            "ts_values": pen_ts_values,
            "server_time_rows": pen_server_time_rows,
            "timestamp_years": pen_timestamp_years,
            "intervals": intervals,
            "writing_seconds": writing_seconds,
            "writing_fraction": writing_fraction,
            "clock": pen_clock,
            "session_csv_count": session_pen_samples,
            "count_delta": pen_count_delta,
            "count_tolerance": pen_count_tolerance,
            "in_range_pct": pen_in_range_pct,
            "load_error": pen_err,
            "path": str(pen_path),
            "exists": pen_path.exists(),
        },
        "airpods": {
            **airpods_summary,
            "session_csv_count": session_airpods_samples,
            "count_delta": airpods_count_delta,
            "count_tolerance": airpods_count_tolerance,
            "expected_samples": airpods_expected,
        },
        "common_overlap_seconds": common_overlap_seconds,
        "sync_estimate": sync_estimate,
        "start_year": start.year if start else None,
        "session_start_ms": int(start.timestamp() * 1000) if start else None,
        "session_end_ms": int(end.timestamp() * 1000) if end else None,
    }

    issues = _build_issues(facts)
    facts["issues"] = issues

    _facts_cache[sid] = (cache_key, facts)
    return facts


def _build_issues(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Erzeugt die angereicherten Issue-Dicts aus dem Fact-Bag."""
    out: list[dict[str, Any]] = []
    w = facts["watch"]
    p = facts["pen"]
    is_active = facts["is_active"]

    # Read-Errors nur für *vorhandene* aber kaputte CSVs — fehlende Dateien
    # behandeln wir als "0 Samples", was no_watch_samples / no_pen_samples auslöst.
    if w["load_error"] and w["exists"]:
        out.append(_make_issue("watch_read_error", observed=w["load_error"]))
    if p["load_error"] and p["exists"]:
        out.append(_make_issue("pen_read_error", observed=p["load_error"]))

    if w["row_count"] == 0:
        out.append(_make_issue("no_watch_samples", observed=0))
    if p["row_count"] == 0:
        out.append(_make_issue("no_pen_samples", observed=0))

    if w["row_count"] and not w["ts_values"]:
        out.append(_make_issue("watch_no_device_time", observed="0 rows mit 'ts'"))
    if p["row_count"] and not p["ts_values"]:
        out.append(_make_issue("pen_no_device_time", observed="0 rows mit 'timestamp'"))

    if w["row_count"] and w["gyro_rows"] == 0:
        out.append(_make_issue("missing_gyroscope", observed="0 rows mit rx/ry/rz"))
    if w["row_count"] and w["accel_rows"] == 0:
        out.append(_make_issue("missing_accelerometer", observed="0 rows mit ax/ay/az"))

    hz = w["estimated_hz"]
    if hz is not None and not (_WATCH_HZ_MIN <= hz <= _WATCH_HZ_MAX):
        out.append(_make_issue(
            "watch_rate_out_of_range",
            observed=f"{hz:.1f} Hz",
        ))

    if w["sequence_gaps"]:
        out.append(_make_issue(
            "sequence_gaps",
            observed=f"{w['sequence_gaps']} fehlende Batch-Nummer(n)",
        ))

    if not is_active and w["row_count"] != w["session_csv_count"]:
        if w["count_delta"] > w["count_tolerance"]:
            out.append(_make_issue(
                "watch_count_mismatch",
                observed=f"delta={w['count_delta']} (csv={w['row_count']}, sessions.csv={w['session_csv_count']})",
                threshold=f"|delta| ≤ {w['count_tolerance']}",
            ))

    if not is_active and p["row_count"] != p["session_csv_count"]:
        if p["count_delta"] > p["count_tolerance"]:
            out.append(_make_issue(
                "pen_count_mismatch",
                observed=f"delta={p['count_delta']} (csv={p['row_count']}, sessions.csv={p['session_csv_count']})",
                threshold=f"|delta| ≤ {p['count_tolerance']}",
            ))

    if p["row_count"] and p["server_time_rows"] == 0:
        out.append(_make_issue(
            "legacy_pen_time",
            observed="0 rows mit local_ts_ms",
        ))
    if w["row_count"] and w["server_time_rows"] == 0:
        out.append(_make_issue(
            "legacy_watch_time",
            observed="0 rows mit server_received_ms",
        ))

    expected = w["expected_samples"]
    if not is_active and expected and w["row_count"] < expected * _COVERAGE_PCT_MIN:
        pct = w["row_count"] / expected if expected else 0
        out.append(_make_issue(
            "low_watch_coverage",
            observed=f"{w['row_count']} von ~{expected} erwartet ({pct:.0%})",
        ))

    if (
        facts["start_year"]
        and p["timestamp_years"]
        and facts["start_year"] not in p["timestamp_years"]
        and p["server_time_rows"] == 0
    ):
        out.append(_make_issue(
            "pen_clock_mismatch",
            observed=f"pen years={sorted(set(p['timestamp_years']))[:3]}, session year={facts['start_year']}",
            ml_override="info", recording_override="info",
        ))

    if p["in_range_pct"] is not None and p["in_range_pct"] < _PEN_IN_RANGE_PCT_MIN:
        out.append(_make_issue(
            "pen_dots_outside_watch_range",
            observed=f"{p['in_range_pct']:.1%}",
        ))

    # ── AirPods (optional stream) ────────────────────────────────────────────
    a = facts.get("airpods", {})
    if a.get("exists") and a.get("row_count") == 0:
        out.append(_make_issue("no_airpods_samples", observed=0))
    if a.get("row_count") and a.get("server_time_rows") == 0:
        out.append(_make_issue(
            "legacy_airpods_time",
            observed="0 rows mit server_received_ms",
        ))
    a_expected = a.get("expected_samples")
    if (
        not is_active
        and a.get("exists")
        and a_expected
        and a.get("row_count", 0) < a_expected * _COVERAGE_PCT_MIN
    ):
        pct = a["row_count"] / a_expected if a_expected else 0
        out.append(_make_issue(
            "low_airpods_coverage",
            observed=f"{a['row_count']} von ~{a_expected} erwartet ({pct:.0%})",
        ))
    if (
        not is_active
        and a.get("exists")
        and a.get("row_count") != a.get("session_csv_count")
        and a.get("count_delta", 0) > a.get("count_tolerance", 0)
    ):
        out.append(_make_issue(
            "airpods_count_mismatch",
            observed=f"delta={a['count_delta']} (csv={a['row_count']}, sessions.csv={a['session_csv_count']})",
            threshold=f"|delta| ≤ {a['count_tolerance']}",
        ))

    # ── Pen↔IMU sync confidence (variance-minimization) ──────────────────────
    sync = facts.get("sync_estimate", {})
    if (
        sync.get("method") == "stroke_variance_minimization"
        and not is_active
        # Only complain when the algorithm actually ran (had inputs); a
        # missing CSV / no strokes is already covered by no_pen_samples
        # / no_watch_samples and shouldn't double-fire.
        and sync.get("sigma_minimal_variance") is not None
    ):
        sigma = sync["sigma_minimal_variance"]
        if sigma > _SYNC_SIGMA_WEAK_MAX:
            out.append(_make_issue(
                "sync_failed",
                observed=f"σ = {sigma:.2f}, δ = {sync.get('delta_ms', 0):.0f} ms",
            ))
        elif sigma > _SYNC_SIGMA_OK_MAX:
            out.append(_make_issue(
                "low_sync_confidence",
                observed=f"σ = {sigma:.2f}, δ = {sync.get('delta_ms', 0):.0f} ms",
            ))

    # Stale-File-Detector: Daten-Range außerhalb des Session-Fensters
    # (typischer Fall: Session-ID wurde recycled und alte CSV wurde appended).
    s_start = facts.get("session_start_ms")
    s_end = facts.get("session_end_ms")
    if not is_active and s_start is not None and s_end is not None:
        tol_ms = 60_000
        outliers: list[str] = []
        for label, clock in (("watch", w["clock"]), ("pen", p["clock"])):
            cs = clock.get("start_ms")
            ce = clock.get("end_ms")
            if cs is None or ce is None:
                continue
            if cs < s_start - tol_ms or ce > s_end + tol_ms:
                lead = max(0, (s_start - cs) // 1000)
                trail = max(0, (ce - s_end) // 1000)
                outliers.append(f"{label}: −{lead}s vor / +{trail}s nach Session")
        if outliers:
            out.append(_make_issue(
                "data_outside_session_window",
                observed="; ".join(outliers),
            ))

    return out


# ── View 1: Listen-Quality (für /sessions/quality) ────────────────────────────

def _session_quality(row: dict[str, str]) -> dict[str, Any]:
    """Quality-Snapshot pro Session — kompakt für die Übersichtsseite."""
    facts = _session_facts(row)
    sid = facts["session_id"]
    issues = facts["issues"]
    w = facts["watch"]
    p = facts["pen"]
    sync = facts["sync_estimate"]

    ml_readiness = _score_payload(issues, "ml_severity")
    recording_health = _score_payload(issues, "recording_severity")

    return {
        "session_id": sid,
        "person_id": row.get("person_id", ""),
        "description": row.get("description", ""),
        "status": row.get("status", ""),
        "duration_seconds": round(facts["duration_seconds"], 1) if facts["duration_seconds"] is not None else None,
        "expected_watch_samples": w["expected_samples"],
        "target_watch_hz": _TARGET_WATCH_HZ,
        "watch": {
            "path": w["path"],
            "exists": w["exists"],
            "rows": w["row_count"],
            "sessions_csv_rows": w["session_csv_count"],
            "estimated_hz": round(w["estimated_hz"], 2) if w["estimated_hz"] else None,
            "median_dt_ms": round(w["median_dt_ms"], 2) if w["median_dt_ms"] else None,
            "has_accelerometer": w["accel_rows"] > 0,
            "accelerometer_rows": w["accel_rows"],
            "has_gyroscope": w["gyro_rows"] > 0,
            "gyroscope_rows": w["gyro_rows"],
            "has_server_received_ms": w["server_time_rows"] > 0,
            "server_received_ms_rows": w["server_time_rows"],
            "sequence_batches": w["sequence_batches"],
            "sequence_gaps": w["sequence_gaps"],
        },
        "pen": {
            "path": p["path"],
            "exists": p["exists"],
            "rows": p["row_count"],
            "sessions_csv_rows": p["session_csv_count"],
            "has_server_time": p["server_time_rows"] > 0,
            "server_time_rows": p["server_time_rows"],
            "writing_seconds": p["writing_seconds"],
            "writing_fraction": round(p["writing_fraction"], 3) if p["writing_fraction"] is not None else None,
            "timestamp_year_min": min(p["timestamp_years"]) if p["timestamp_years"] else None,
            "timestamp_year_max": max(p["timestamp_years"]) if p["timestamp_years"] else None,
        },
        "common_overlap_seconds": facts["common_overlap_seconds"],
        "ml_readiness": ml_readiness,
        "recording_health": recording_health,
        "diagnostics": {
            "sync_estimate": sync,
            "sync_diagnostic": _sync_diagnostic(sync),
            "counts": {
                "watch_rows": w["row_count"],
                "watch_sessions_csv_rows": w["session_csv_count"],
                "watch_count_delta": w["count_delta"],
                "watch_count_tolerance": w["count_tolerance"],
                "pen_rows": p["row_count"],
                "pen_sessions_csv_rows": p["session_csv_count"],
                "pen_count_delta": p["count_delta"],
                "pen_count_tolerance": p["count_tolerance"],
            },
            "coverage": {
                "expected_watch_samples": w["expected_samples"],
                "target_watch_hz": _TARGET_WATCH_HZ,
                "pen_dots_in_watch_range_pct": round(p["in_range_pct"], 4)
                if p["in_range_pct"] is not None else None,
                "watch_device_duration_seconds": w["clock"].get("device_duration_seconds"),
                "pen_device_duration_seconds": p["clock"].get("device_duration_seconds"),
                "common_overlap_seconds": facts["common_overlap_seconds"],
                "writing_seconds": p["writing_seconds"],
                "writing_fraction": round(p["writing_fraction"], 3) if p["writing_fraction"] is not None else None,
            },
        },
        "issues": issues,
        "quality": ml_readiness["status"],  # Legacy-Alias
    }


# ── View 2: Detail-Validation (für /sessions/{id}/validation) ─────────────────

def _session_validation(session_id: str) -> dict[str, Any]:
    """Tiefenanalyse einer einzelnen Session, inkl. Timeline-Daten für den Chart."""
    from .csv_io import _read_session_rows
    from .utils import _safe_file_id

    safe_id = _safe_file_id(session_id)
    # Hole die echte sessions.csv-Zeile, damit count-Vergleiche stimmen.
    # Fallback auf eine minimale Row, falls die Session nicht im Index steht.
    real_row = next(
        (r for r in _read_session_rows() if r.get("session_id") == safe_id),
        {"session_id": safe_id, "status": ""},
    )
    facts = _session_facts(real_row)
    issues = facts["issues"]
    w = facts["watch"]
    p = facts["pen"]
    sync = facts["sync_estimate"]
    watch_clock = w["clock"]
    pen_clock = p["clock"]

    # Detail-Issues, die nur in der tiefen Sicht auftauchen
    extra: list[dict[str, Any]] = []
    streams_overlap = (
        None not in (watch_clock["start_ms"], watch_clock["end_ms"], pen_clock["start_ms"], pen_clock["end_ms"])
        and watch_clock["start_ms"] <= pen_clock["end_ms"]
        and pen_clock["start_ms"] <= watch_clock["end_ms"]
    )
    if (
        None not in (watch_clock["start_ms"], watch_clock["end_ms"], pen_clock["start_ms"], pen_clock["end_ms"])
        and not streams_overlap
    ):
        extra.append(_make_issue(
            "streams_do_not_overlap",
            observed="overlap=0 ms",
        ))

    relative_clock_drift = None
    source_clock_offset_gap = None
    if (
        watch_clock.get("source_to_local_drift_ms") is not None
        and pen_clock.get("source_to_local_drift_ms") is not None
    ):
        relative_clock_drift = (
            pen_clock["source_to_local_drift_ms"] - watch_clock["source_to_local_drift_ms"]
        )
    if (
        watch_clock.get("source_to_local_offset_median_ms") is not None
        and pen_clock.get("source_to_local_offset_median_ms") is not None
    ):
        source_clock_offset_gap = (
            pen_clock["source_to_local_offset_median_ms"]
            - watch_clock["source_to_local_offset_median_ms"]
        )
        if abs(source_clock_offset_gap) > 1000:
            extra.append(_make_issue(
                "source_clocks_not_shared",
                observed=f"|gap| ≈ {abs(source_clock_offset_gap)/86_400_000:.1f} d",
                ml_override="info", recording_override="info",
            ))

    pct = p["in_range_pct"]
    local_session_start = min(
        [v for v in (watch_clock["start_ms"], pen_clock["start_ms"]) if v is not None],
        default=None,
    )
    timeline_intervals = []
    if local_session_start is not None:
        for interval in p["intervals"]:
            start_local = interval.get("local_start_ms")
            end_local = interval.get("local_end_ms")
            if start_local is None or end_local is None:
                continue
            timeline_intervals.append({
                "start_s": round((start_local - local_session_start) / 1000, 3),
                "end_s": round((end_local - local_session_start) / 1000, 3),
                "type": "writing",
                "duration_s": round(max(0, end_local - start_local) / 1000, 3),
                "dot_count": interval.get("dot_count"),
            })

    all_issues = issues + extra
    return {
        "session_id": safe_id,
        "status": _quality_status([i["severity"] for i in all_issues]),
        "watch": watch_clock,
        "pen": pen_clock,
        "overlap": {
            "start_offset_ms": (
                pen_clock["start_ms"] - watch_clock["start_ms"]
                if None not in (pen_clock["start_ms"], watch_clock["start_ms"]) else None
            ),
            "end_offset_ms": (
                watch_clock["end_ms"] - pen_clock["end_ms"]
                if None not in (watch_clock["end_ms"], pen_clock["end_ms"]) else None
            ),
            "streams_overlap": streams_overlap,
            "pen_dots_in_watch_range_pct": round(pct, 4) if pct is not None else None,
            "common_overlap_seconds": facts["common_overlap_seconds"],
        },
        "source_clocks": {
            "watch_source_duration_seconds": watch_clock.get("source_duration_seconds"),
            "pen_source_duration_seconds": pen_clock.get("source_duration_seconds"),
            "watch_source_to_local_drift_ms": watch_clock.get("source_to_local_drift_ms"),
            "pen_source_to_local_drift_ms": pen_clock.get("source_to_local_drift_ms"),
            "relative_pen_vs_watch_clock_drift_ms": round(relative_clock_drift, 3)
            if relative_clock_drift is not None else None,
            "source_clock_offset_gap_ms": round(source_clock_offset_gap, 3)
            if source_clock_offset_gap is not None else None,
        },
        "sync_estimate": sync,
        "sync_diagnostic": _sync_diagnostic(sync),
        "timeline_for_chart": {
            "session_start_ms": local_session_start,
            "watch_start_s": (
                round((watch_clock["start_ms"] - local_session_start) / 1000, 3)
                if None not in (watch_clock["start_ms"], local_session_start) else None
            ),
            "watch_end_s": (
                round((watch_clock["end_ms"] - local_session_start) / 1000, 3)
                if None not in (watch_clock["end_ms"], local_session_start) else None
            ),
            "pen_start_s": (
                round((pen_clock["start_ms"] - local_session_start) / 1000, 3)
                if None not in (pen_clock["start_ms"], local_session_start) else None
            ),
            "pen_end_s": (
                round((pen_clock["end_ms"] - local_session_start) / 1000, 3)
                if None not in (pen_clock["end_ms"], local_session_start) else None
            ),
            "duration_s": (
                round((max(watch_clock["end_ms"] or 0, pen_clock["end_ms"] or 0) - local_session_start) / 1000, 3)
                if local_session_start is not None and (watch_clock["end_ms"] is not None or pen_clock["end_ms"] is not None)
                else None
            ),
            "pen_events": timeline_intervals,
        },
        "issues": all_issues,
    }


# ── View 3: Voll angereicherter Report (für /sessions/{id}/report) ────────────

def _session_report(row: dict[str, str]) -> dict[str, Any]:
    """Vollständiger Report für eine Session — Quality + Validation in einem Dokument."""
    quality = _session_quality(row)
    validation = _session_validation(row.get("session_id", ""))
    return {
        "session_id": row.get("session_id", ""),
        "person_id": row.get("person_id", ""),
        "description": row.get("description", ""),
        "status": row.get("status", ""),
        "start_time": row.get("start_time", ""),
        "end_time": row.get("end_time", ""),
        "duration_seconds": quality["duration_seconds"],
        "target_watch_hz": _TARGET_WATCH_HZ,
        "scores": {
            "ml_readiness": quality["ml_readiness"],
            "recording_health": quality["recording_health"],
        },
        "watch": quality["watch"],
        "pen": quality["pen"],
        "coverage": quality["diagnostics"]["coverage"],
        "counts": quality["diagnostics"]["counts"],
        "timeline_for_chart": validation["timeline_for_chart"],
        "source_clocks": validation["source_clocks"],
        "overlap": validation["overlap"],
        "sync_estimate": quality["diagnostics"]["sync_estimate"],
        "sync_diagnostic": quality["diagnostics"]["sync_diagnostic"],
        "issues": quality["issues"] + [
            i for i in validation["issues"]
            if i["code"] not in {q["code"] for q in quality["issues"]}
        ],
    }


# ── Markdown-Serialisierung ───────────────────────────────────────────────────

def _session_report_markdown(report: dict[str, Any]) -> str:
    """Rendert einen _session_report als lesbare Markdown-Datei."""
    sid = report["session_id"]
    person = report.get("person_id") or "—"
    desc = report.get("description") or "—"
    status = report.get("status") or "—"
    duration = report.get("duration_seconds")

    ml = report["scores"]["ml_readiness"]
    rec = report["scores"]["recording_health"]
    w = report["watch"]
    p = report["pen"]
    cov = report["coverage"]
    sync = report.get("sync_estimate") or {}
    sync_diag = report.get("sync_diagnostic") or {}

    def fmt_secs(v):
        return f"{v:.1f} s" if isinstance(v, (int, float)) and v is not None else "—"

    def fmt_pct(v):
        return f"{v*100:.1f}%" if isinstance(v, (int, float)) and v is not None else "—"

    def fmt_num(v):
        return f"{v:,}" if isinstance(v, int) else (f"{v}" if v is not None else "—")

    lines: list[str] = []
    lines.append(f"# Session {sid} — Quality Report")
    lines.append("")
    lines.append(f"- **Person**: {person}")
    if desc != "—":
        lines.append(f"- **Beschreibung**: {desc}")
    lines.append(f"- **Status**: {status}")
    lines.append(f"- **Dauer**: {fmt_secs(duration)}")
    lines.append(f"- **Start**: {report.get('start_time') or '—'}")
    lines.append(f"- **Ende**: {report.get('end_time') or '—'}")
    lines.append("")

    lines.append("## Scores")
    lines.append("")
    lines.append(f"- **ML readiness**: `{ml['status']}` "
                 f"({len(ml['blockers'])} blocker · {len(ml['warnings'])} warning · {len(ml['info'])} info)")
    lines.append(f"- **Recording health**: `{rec['status']}` "
                 f"({len(rec['blockers'])} blocker · {len(rec['warnings'])} warning · {len(rec['info'])} info)")
    lines.append("")

    lines.append("## Watch Stream")
    lines.append("")
    lines.append(f"- Samples: {fmt_num(w['rows'])} (sessions.csv: {fmt_num(w['sessions_csv_rows'])})")
    lines.append(f"- Geschätzte Rate: **{w['estimated_hz'] or '—'} Hz** "
                 f"(Target {report['target_watch_hz']:.0f} Hz, akzeptiert {_WATCH_HZ_MIN:.0f}–{_WATCH_HZ_MAX:.0f} Hz)")
    lines.append(f"- Accelerometer: {'ja' if w['has_accelerometer'] else 'NEIN'} ({fmt_num(w['accelerometer_rows'])} rows)")
    lines.append(f"- Gyroscope: {'ja' if w['has_gyroscope'] else 'NEIN'} ({fmt_num(w['gyroscope_rows'])} rows)")
    lines.append(f"- Wall-Clock-Stempel: {'ja' if w['has_server_received_ms'] else 'nein'}")
    lines.append(f"- Sequence-Batches: {fmt_num(w['sequence_batches'])} · Lücken: {fmt_num(w['sequence_gaps'])}")
    lines.append("")

    lines.append("## Pen Stream")
    lines.append("")
    lines.append(f"- Dots: {fmt_num(p['rows'])} (sessions.csv: {fmt_num(p['sessions_csv_rows'])})")
    lines.append(f"- Wall-Clock-Stempel (local_ts_ms): {'ja' if p['has_server_time'] else 'NEIN'}")
    lines.append(f"- Effektive Schreibzeit: {fmt_secs(p['writing_seconds'])} "
                 f"({fmt_pct(p['writing_fraction'])} der Pen-Aufnahmedauer)")
    lines.append(f"- Anteil Dots im Watch-Bereich: {fmt_pct(cov.get('pen_dots_in_watch_range_pct'))}")
    lines.append("")

    lines.append("## Coverage")
    lines.append("")
    lines.append(f"- Watch-Aufnahmedauer (Device): {fmt_secs(cov.get('watch_device_duration_seconds'))}")
    lines.append(f"- Pen-Aufnahmedauer (Device): {fmt_secs(cov.get('pen_device_duration_seconds'))}")
    lines.append(f"- Gemeinsames Aufnahme-Fenster (Wall-Clock): {fmt_secs(cov.get('common_overlap_seconds'))}")
    lines.append(f"- Erwartete Watch-Samples bei {report['target_watch_hz']:.0f} Hz: "
                 f"{fmt_num(cov.get('expected_watch_samples'))}")
    lines.append("")

    issues = report.get("issues") or []
    if issues:
        lines.append("## Issues")
        lines.append("")
        sev_icon = {"bad": "🛑", "warn": "⚠️", "info": "ℹ️"}
        for issue in sorted(issues, key=lambda i: -_SEVERITY_ORDER.get(i.get("severity"), 0)):
            sev = issue.get("severity", "info")
            icon = sev_icon.get(sev, "•")
            lines.append(f"### {icon} `{issue['code']}` [{sev}]")
            lines.append("")
            lines.append(f"- **Check**: {issue.get('check') or '—'}")
            lines.append(f"- **Threshold**: `{issue.get('threshold') or '—'}`")
            lines.append(f"- **Beobachtet**: {issue.get('observed') if issue.get('observed') is not None else '—'}")
            lines.append(f"- **Begründung**: {issue.get('rationale') or '—'}")
            ml_sev = issue.get("ml_severity")
            rec_sev = issue.get("recording_severity")
            scope = []
            if ml_sev:
                scope.append(f"ML: {ml_sev}")
            if rec_sev:
                scope.append(f"Recording: {rec_sev}")
            if scope:
                lines.append(f"- **Wirkt auf**: {' · '.join(scope)}")
            lines.append("")
    else:
        lines.append("## Issues")
        lines.append("")
        lines.append("Keine Issues gefunden — Session ist sauber.")
        lines.append("")

    lines.append("## Sync-Diagnose (optional, beeinflusst Score nicht)")
    lines.append("")
    lines.append(f"- Status: `{sync_diag.get('status') or '—'}` ({sync_diag.get('label') or '—'})")
    if sync.get("usable"):
        lines.append(f"- Confidence: {sync.get('confidence')}")
        lines.append(f"- Median-Offset: {sync.get('median_offset_ms')} ms · "
                     f"Drift: {sync.get('estimated_drift_ms')} ms")
        lines.append(f"- Matched events: {len(sync.get('matched_events') or [])}")
    else:
        lines.append(f"- Reason: {sync.get('reason') or '—'}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"_Generated by quality.py · target {report['target_watch_hz']:.0f} Hz · "
                 f"thresholds: hz {_WATCH_HZ_MIN:.0f}–{_WATCH_HZ_MAX:.0f}, "
                 f"coverage ≥{_COVERAGE_PCT_MIN:.0%}, pen-in-range ≥{_PEN_IN_RANGE_PCT_MIN:.0%}_")
    return "\n".join(lines) + "\n"
