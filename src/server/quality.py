"""
Session-Qualität und Zeitstempel-Validierung.

Dieses Modul analysiert aufgezeichnete Sessions rein aus den CSV-Dateien —
kein Zugriff auf globalen State, keine Seiteneffekte. Alles hier ist
read-only und kann unabhängig getestet werden.
"""

import csv
import math
from datetime import datetime, timezone
from statistics import median
from typing import Any, Optional

from .config import DATA_RAW_PEN, DATA_RAW_WATCH
from .utils import _as_float, _as_int, _mad, _parse_iso, _row_local_ms


# ── Kleine Hilfsfunktionen ────────────────────────────────────────────────────

def _quality_status(issues: list[dict[str, str]]) -> str:
    """Gibt 'bad', 'warn' oder 'ok' zurück — je nach schlimmstem Issue."""
    severities = {issue["severity"] for issue in issues}
    if "bad" in severities:
        return "bad"
    if "warn" in severities:
        return "warn"
    return "ok"


def _issue_buckets(issues: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Gruppiert Issues für stabile API-Antworten und Dashboard-Anzeigen."""
    return {
        "blockers": [i for i in issues if i.get("severity") == "bad"],
        "warnings": [i for i in issues if i.get("severity") == "warn"],
        "info": [i for i in issues if i.get("severity") == "info"],
    }


def _score_payload(issues: list[dict[str, str]]) -> dict[str, Any]:
    """Score-Objekt für ML-Readiness und Recording-Health."""
    buckets = _issue_buckets(issues)
    return {
        "status": _quality_status(issues),
        **buckets,
    }


def _sync_diagnostic(sync: dict[str, Any]) -> dict[str, Any]:
    """
    Übersetzt die optionale Tap-/Peak-Heuristik in eine Diagnose.
    Diese Diagnose darf die Session-Qualität nicht verschlechtern.
    """
    if sync.get("usable"):
        confidence = sync.get("confidence", "unknown")
        return {
            "status": "estimated",
            "label": "estimated",
            "message": (
                "Optional tap/peak calibration estimate is available. "
                f"Heuristic confidence: {confidence}."
            ),
        }
    reason = sync.get("reason", "")
    if "Fewer than two" in reason:
        return {
            "status": "needs_explicit_tap_protocol",
            "label": "needs tap protocol",
            "message": (
                "No reliable tap/peak calibration pattern was found. "
                "This is only a calibration hint, not a session-quality failure."
            ),
        }
    return {
        "status": "not_required",
        "label": "not required",
        "message": (
            "No explicit tap/peak calibration is required for the session score. "
            f"Diagnostic detail: {reason}"
            if reason else
            "No explicit tap/peak calibration pattern was detected; this is not a quality failure."
        ),
    }


# ── CSV-Timeline laden ────────────────────────────────────────────────────────

def _load_watch_timeline(session_id: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    Liest die Watch-CSV und gibt eine Liste von Zeilen mit vorberechneten
    Magnetwerten zurück. Bei Fehler kommt ([], Fehlermeldung).
    """
    path = DATA_RAW_WATCH / f"{session_id}_watch.csv"
    if not path.exists():
        return [], f"Missing watch CSV: {path.name}"
    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                source_ts = _as_int(row.get("ts"))
                local_ts = _row_local_ms(row, "local_ts_ms", "server_received_ms")
                ax = _as_float(row.get("ax"))
                ay = _as_float(row.get("ay"))
                az = _as_float(row.get("az"))
                rx = _as_float(row.get("rx"))
                ry = _as_float(row.get("ry"))
                rz = _as_float(row.get("rz"))
                acc_mag = (
                    math.sqrt(ax * ax + ay * ay + az * az)
                    if None not in (ax, ay, az) else None
                )
                gyro_mag = (
                    math.sqrt(rx * rx + ry * ry + rz * rz)
                    if None not in (rx, ry, rz) else None
                )
                rows.append({
                    "source_ts": source_ts,
                    "local_ts": local_ts,
                    # Kombiniertes Bewegungsmaß für Peak-Erkennung
                    "motion_mag": (gyro_mag if gyro_mag is not None else 0.0)
                    + 0.35 * (acc_mag if acc_mag is not None else 0.0),
                    "acc_mag": acc_mag,
                    "gyro_mag": gyro_mag,
                })
    except Exception as exc:
        return [], f"Could not read watch CSV: {exc}"
    return rows, None


def _load_pen_timeline(session_id: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Liest die Pen-CSV und gibt Dot-Zeilen zurück. Bei Fehler ([], Fehlermeldung)."""
    path = DATA_RAW_PEN / f"{session_id}_pen.csv"
    if not path.exists():
        return [], f"Missing pen CSV: {path.name}"
    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "source_ts": _as_int(row.get("timestamp")),
                    "local_ts": _row_local_ms(row, "local_ts_ms"),
                    "dot_type": row.get("dot_type") or "",
                    "x": _as_float(row.get("x")),
                    "y": _as_float(row.get("y")),
                    "pressure": _as_int(row.get("pressure")),
                })
    except Exception as exc:
        return [], f"Could not read pen CSV: {exc}"
    return rows, None


# ── Zeitstempel-Statistiken ───────────────────────────────────────────────────

def _clock_summary(rows: list[dict[str, Any]], count_key: str) -> dict[str, Any]:
    """
    Berechnet Start/Ende, Dauer und Clock-Drift für einen Datenstrom.
    count_key ist der Name für den Zähler im Ergebnis-Dict (z.B. 'total_samples').
    Die Geräte-Zeitachse ist die kanonische ML-Zeitachse; lokale/serverseitige
    Zeiten bleiben nur Capture-Metadaten.
    """
    source_values = [r["source_ts"] for r in rows if r.get("source_ts") is not None]
    local_values = [r["local_ts"] for r in rows if r.get("local_ts") is not None]
    paired_offsets = [
        r["local_ts"] - r["source_ts"]
        for r in rows
        if r.get("local_ts") is not None and r.get("source_ts") is not None
    ]
    offset_start = paired_offsets[0] if paired_offsets else None
    offset_end = paired_offsets[-1] if paired_offsets else None
    drift_ms = (
        offset_end - offset_start
        if offset_start is not None and offset_end is not None else None
    )
    return {
        "start_ms": min(local_values) if local_values else None,
        "end_ms": max(local_values) if local_values else None,
        "duration_seconds": (
            round((max(local_values) - min(local_values)) / 1000, 3)
            if len(local_values) > 1 else None
        ),
        "device_start_ms": min(source_values) if source_values else None,
        "device_end_ms": max(source_values) if source_values else None,
        "device_duration_seconds": (
            round((max(source_values) - min(source_values)) / 1000, 3)
            if len(source_values) > 1 else None
        ),
        count_key: len(rows),
        "source_start_ms": min(source_values) if source_values else None,
        "source_end_ms": max(source_values) if source_values else None,
        "source_duration_seconds": (
            round((max(source_values) - min(source_values)) / 1000, 3)
            if len(source_values) > 1 else None
        ),
        "source_to_local_offset_start_ms": offset_start,
        "source_to_local_offset_end_ms": offset_end,
        "source_to_local_drift_ms": drift_ms,
        "source_to_local_offset_median_ms": round(median(paired_offsets), 3)
        if paired_offsets else None,
        "source_to_local_offset_min_ms": min(paired_offsets) if paired_offsets else None,
        "source_to_local_offset_max_ms": max(paired_offsets) if paired_offsets else None,
        "source_to_local_offset_mad_ms": round(_mad(paired_offsets), 3)
        if paired_offsets else None,
        "rows_with_local_ts": len(local_values),
        "rows_with_source_ts": len(source_values),
    }


# ── Stift-Intervalle ──────────────────────────────────────────────────────────

def _pen_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Gruppiert PEN_DOWN → PEN_MOVE* → PEN_UP Sequenzen zu Schreib-Intervallen.
    Gibt eine Liste mit Start, Ende, Dauer und Dot-Count zurück.
    """
    intervals: list[dict[str, Any]] = []
    open_start = None
    open_local_start = None
    dot_count = 0
    for row in rows:
        dtype = row.get("dot_type")
        source_ts = row.get("source_ts")
        local_ts = row.get("local_ts")
        if dtype == "PEN_DOWN":
            open_start = source_ts
            open_local_start = local_ts
            dot_count = 1
        elif dtype in ("PEN_MOVE", "PEN_HOVER") and open_start is not None:
            dot_count += 1
        elif dtype == "PEN_UP" and open_start is not None:
            end = source_ts if source_ts is not None else open_start
            local_end = local_ts if local_ts is not None else open_local_start
            intervals.append({
                "source_start_ms": open_start,
                "source_end_ms": end,
                "local_start_ms": open_local_start,
                "local_end_ms": local_end,
                "duration_ms": max(0, end - open_start)
                if None not in (open_start, end) else None,
                "dot_count": dot_count + 1,
            })
            open_start = None
            open_local_start = None
            dot_count = 0
    return intervals


# ── Watch-Bewegungs-Peaks ─────────────────────────────────────────────────────

def _watch_peaks(rows: list[dict[str, Any]], max_peaks: int = 80) -> list[dict[str, Any]]:
    """
    Findet markante Bewegungs-Peaks in den Watch-Daten — nützlich um
    Sync-Taps (Auftippen auf den Tisch) automatisch zu lokalisieren.
    Threshold: Median + max(0.015, 4×MAD).
    """
    candidates = [
        r for r in rows
        if r.get("source_ts") is not None and r.get("motion_mag") is not None
    ]
    if len(candidates) < 5:
        return []
    mags = [float(r["motion_mag"]) for r in candidates]
    center = median(mags)
    spread = _mad(mags, center)
    threshold = center + max(0.015, spread * 4)
    peaks: list[dict[str, Any]] = []
    last_ts = None
    for row in sorted(candidates, key=lambda r: r["source_ts"]):
        mag = float(row["motion_mag"])
        if mag < threshold:
            continue
        source_ts = row["source_ts"]
        # Innerhalb von 250 ms nur den stärksten Peak behalten
        if last_ts is not None and source_ts - last_ts < 250:
            if peaks and mag > peaks[-1]["motion_mag"]:
                peaks[-1] = {"source_ts": source_ts, "motion_mag": round(mag, 6)}
            continue
        peaks.append({"source_ts": source_ts, "motion_mag": round(mag, 6)})
        last_ts = source_ts
    return sorted(peaks, key=lambda r: r["motion_mag"], reverse=True)[:max_peaks]


# ── Sync-Drift-Schätzung ──────────────────────────────────────────────────────

def _estimate_sync_drift(
    watch_rows: list[dict[str, Any]],
    pen_rows: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Versucht die Uhr-Drift zwischen Stift und Watch zu schätzen, indem
    kurze Strich-Starts (PEN_DOWN / kurze Striche) mit Watch-Peaks gematcht werden.
    Das funktioniert gut, wenn beim Aufzeichnen ein klares Start-/End-Tap-Protokoll
    eingehalten wird.
    """
    watch_offsets = [
        r["local_ts"] - r["source_ts"]
        for r in watch_rows
        if r.get("local_ts") is not None and r.get("source_ts") is not None
    ]
    pen_offsets = [
        r["local_ts"] - r["source_ts"]
        for r in pen_rows
        if r.get("local_ts") is not None and r.get("source_ts") is not None
    ]
    if not watch_offsets or not pen_offsets:
        return {
            "usable": False,
            "confidence": "none",
            "method": "sync tap matching",
            "reason": "Need local and source timestamps for both streams.",
            "matched_events": [],
        }

    approx_pen_to_watch_offset = median(pen_offsets) - median(watch_offsets)
    peaks = _watch_peaks(watch_rows)
    if not peaks:
        return {
            "usable": False,
            "confidence": "none",
            "method": "sync tap matching",
            "reason": "No clear watch motion peaks found.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "matched_events": [],
        }

    pen_downs = [
        r for r in pen_rows
        if r.get("dot_type") == "PEN_DOWN" and r.get("source_ts") is not None
    ]
    # Kurze Striche (≤1400 ms, ≤80 Dots) sind gute Tap-Kandidaten
    short_intervals = [
        i for i in intervals
        if i.get("source_start_ms") is not None
        and i.get("duration_ms") is not None
        and i["duration_ms"] <= 1400
        and i.get("dot_count", 9999) <= 80
    ]
    candidate_ts = [i["source_start_ms"] for i in short_intervals] or [
        r["source_ts"] for r in pen_downs
    ]
    if not candidate_ts:
        return {
            "usable": False,
            "confidence": "none",
            "method": "sync tap matching",
            "reason": "No PEN_DOWN candidates found.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "matched_events": [],
        }

    candidate_ts = sorted(candidate_ts)
    if len(candidate_ts) > 24:
        candidate_ts = candidate_ts[:12] + candidate_ts[-12:]

    peak_by_ts = sorted(peaks, key=lambda p: p["source_ts"])
    matches: list[dict[str, Any]] = []
    search_window_ms = 1600
    for pen_ts in candidate_ts:
        predicted = pen_ts + approx_pen_to_watch_offset
        nearest = min(
            peak_by_ts,
            key=lambda peak: abs(peak["source_ts"] - predicted),
            default=None,
        )
        if not nearest:
            continue
        error = nearest["source_ts"] - predicted
        if abs(error) <= search_window_ms:
            matches.append({
                "pen_source_ms": pen_ts,
                "watch_peak_source_ms": nearest["source_ts"],
                "offset_ms": round(nearest["source_ts"] - pen_ts, 3),
                "error_from_local_anchor_ms": round(error, 3),
                "watch_motion_mag": nearest["motion_mag"],
            })

    if len(matches) < 2:
        return {
            "usable": False,
            "confidence": "low",
            "method": "sync tap matching",
            "reason": "Fewer than two matched sync-like events. Add clear start/end tap sync events.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "watch_peaks_found": len(peaks),
            "pen_candidates_found": len(candidate_ts),
            "matched_events": matches,
        }

    matches = sorted(matches, key=lambda m: m["pen_source_ms"])
    offsets = [m["offset_ms"] for m in matches]
    split = max(1, len(matches) // 2)
    start_offset = median(offsets[:split])
    end_offset = median(offsets[split:])
    drift_ms = end_offset - start_offset
    errors = [m["error_from_local_anchor_ms"] for m in matches]
    confidence = "high" if len(matches) >= 6 and max(abs(e) for e in errors) <= 350 else "medium"
    if max(abs(e) for e in errors) > 900:
        confidence = "low"

    return {
        "usable": True,
        "confidence": confidence,
        "method": "PEN_DOWN/short-stroke candidates matched to watch motion peaks",
        "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
        "median_offset_ms": round(median(offsets), 3),
        "start_offset_ms": round(start_offset, 3),
        "end_offset_ms": round(end_offset, 3),
        "estimated_drift_ms": round(drift_ms, 3),
        "max_abs_error_from_local_anchor_ms": round(max(abs(e) for e in errors), 3),
        "watch_peaks_found": len(peaks),
        "pen_candidates_found": len(candidate_ts),
        "matched_events": matches,
        "note": "Use an explicit start/end tap protocol before trusting this as calibration.",
    }


# ── Session-Qualitätsprüfung (einfach, für die Übersichtsseite) ───────────────

def _session_quality(row: dict[str, str]) -> dict[str, Any]:
    """
    Schnelle Qualitätsprüfung einer Session anhand der sessions.csv-Zeile.
    Liefert zwei getrennte Scores:
    - ml_readiness: Ist die Session für Labeling/Training brauchbar?
    - recording_health: Lief die technische Aufnahme sauber?

    Sync-/Clock-Heuristiken bleiben Diagnose und verschlechtern keinen Score.
    """
    sid = row.get("session_id", "")
    watch_path = DATA_RAW_WATCH / f"{sid}_watch.csv"
    pen_path = DATA_RAW_PEN / f"{sid}_pen.csv"
    ml_issues: list[dict[str, str]] = []
    recording_issues: list[dict[str, str]] = []
    info_issues: list[dict[str, str]] = []

    watch_rows = 0
    watch_fieldnames: list[str] = []
    watch_ts_values: list[int] = []
    watch_sequences: list[int] = []
    gyro_rows = 0
    accel_rows = 0
    server_time_rows = 0

    def add_ml(code: str, severity: str, message: str) -> None:
        ml_issues.append({"code": code, "severity": severity, "message": message})

    def add_recording(code: str, severity: str, message: str) -> None:
        recording_issues.append({"code": code, "severity": severity, "message": message})

    def add_info(code: str, message: str) -> None:
        info_issues.append({"code": code, "severity": "info", "message": message})

    if watch_path.exists():
        try:
            with open(watch_path, newline="") as f:
                reader = csv.DictReader(f)
                watch_fieldnames = reader.fieldnames or []
                last_seq = None
                for sample in reader:
                    watch_rows += 1
                    ts = _as_int(sample.get("ts"))
                    if ts is not None:
                        watch_ts_values.append(ts)
                    seq = _as_int(sample.get("sequence"))
                    if seq is not None and seq != last_seq:
                        watch_sequences.append(seq)
                        last_seq = seq
                    if all(_as_float(sample.get(k)) is not None for k in ("rx", "ry", "rz")):
                        gyro_rows += 1
                    if all(_as_float(sample.get(k)) is not None for k in ("ax", "ay", "az")):
                        accel_rows += 1
                    if _as_int(sample.get("server_received_ms")) is not None:
                        server_time_rows += 1
        except Exception as exc:
            msg = f"Could not read watch CSV: {exc}"
            add_ml("watch_read_error", "bad", msg)
            add_recording("watch_read_error", "bad", msg)

    pen_rows = 0
    pen_fieldnames: list[str] = []
    pen_server_time_rows = 0
    pen_timestamp_years: list[int] = []
    pen_ts_values: list[int] = []

    if pen_path.exists():
        try:
            with open(pen_path, newline="") as f:
                reader = csv.DictReader(f)
                pen_fieldnames = reader.fieldnames or []
                for dot in reader:
                    pen_rows += 1
                    if _as_int(dot.get("local_ts_ms")) is not None:
                        pen_server_time_rows += 1
                    pen_ts = _as_int(dot.get("timestamp"))
                    if pen_ts:
                        pen_ts_values.append(pen_ts)
                        try:
                            pen_timestamp_years.append(
                                datetime.fromtimestamp(pen_ts / 1000, tz=timezone.utc).year
                            )
                        except (OSError, OverflowError, ValueError):
                            pass
        except Exception as exc:
            msg = f"Could not read pen CSV: {exc}"
            add_ml("pen_read_error", "bad", msg)
            add_recording("pen_read_error", "bad", msg)

    watch_diffs = [
        b - a for a, b in zip(watch_ts_values, watch_ts_values[1:])
        if b > a
    ]
    median_dt_ms = median(watch_diffs) if watch_diffs else None
    watch_est_hz = (1000 / median_dt_ms) if median_dt_ms else None

    sequence_gaps = 0
    for prev, cur in zip(watch_sequences, watch_sequences[1:]):
        if cur > prev + 1:
            sequence_gaps += cur - prev - 1

    start = _parse_iso(row.get("start_time", ""))
    end = _parse_iso(row.get("end_time", ""))
    duration_seconds = None
    expected_watch_samples = None
    if start and end and end > start:
        duration_seconds = (end - start).total_seconds()
        watch_source_duration = (
            (max(watch_ts_values) - min(watch_ts_values)) / 1000
            if len(watch_ts_values) > 1 else None
        )
        expected_duration = watch_source_duration or duration_seconds
        expected_watch_samples = int(expected_duration * 50)

    session_watch_samples = _as_int(row.get("watch_samples")) or 0
    session_pen_samples = _as_int(row.get("pen_samples")) or 0
    is_active_session = row.get("status") == "active"

    if watch_rows == 0:
        add_ml("no_watch_samples", "bad", "No watch samples were recorded.")
        add_recording("no_watch_samples", "bad", "No watch samples were recorded.")
    if pen_rows == 0:
        add_ml("no_pen_samples", "bad", "No pen dots were recorded for ground truth.")
        add_recording("no_pen_samples", "warn", "No pen dots were recorded for ground truth.")
    if watch_rows and not watch_ts_values:
        add_ml("watch_no_device_time", "bad", "Watch rows have no usable device timestamp column 'ts'.")
        add_recording("watch_no_device_time", "bad", "Watch rows have no usable device timestamp column 'ts'.")
    if pen_rows and not pen_ts_values:
        add_ml("pen_no_device_time", "bad", "Pen rows have no usable device timestamp column 'timestamp'.")
        add_recording("pen_no_device_time", "bad", "Pen rows have no usable device timestamp column 'timestamp'.")
    if watch_rows and gyro_rows == 0:
        msg = "Watch samples do not contain rx/ry/rz gyroscope values."
        add_ml("missing_gyroscope", "bad", msg)
        add_recording("missing_gyroscope", "bad", msg)
    if watch_rows and accel_rows == 0:
        msg = "Watch samples do not contain ax/ay/az accelerometer values."
        add_ml("missing_accelerometer", "warn", msg)
        add_recording("missing_accelerometer", "warn", msg)
    if watch_est_hz is not None and not (40 <= watch_est_hz <= 60):
        msg = f"Estimated watch sample rate is {watch_est_hz:.1f} Hz."
        add_ml("watch_rate_out_of_range", "warn", msg)
        add_recording("watch_rate_out_of_range", "warn", msg)
    if sequence_gaps:
        msg = f"Detected {sequence_gaps} missing watch batch sequence(s)."
        add_ml("sequence_gaps", "warn", msg)
        add_recording("sequence_gaps", "warn", msg)
    watch_count_delta = abs(watch_rows - session_watch_samples)
    watch_count_tolerance = max(5, int(max(watch_rows, session_watch_samples) * 0.01))
    if not is_active_session and watch_rows != session_watch_samples:
        msg = f"sessions.csv has {session_watch_samples}, file has {watch_rows}."
        severity = "info" if watch_count_delta <= watch_count_tolerance else "warn"
        if severity == "warn":
            add_recording("watch_count_mismatch", "warn", msg)
        else:
            add_info("watch_count_mismatch", msg)
    pen_count_delta = abs(pen_rows - session_pen_samples)
    pen_count_tolerance = max(3, int(max(pen_rows, session_pen_samples) * 0.01))
    if not is_active_session and pen_rows != session_pen_samples:
        msg = f"sessions.csv has {session_pen_samples}, file has {pen_rows}."
        severity = "info" if pen_count_delta <= pen_count_tolerance else "warn"
        if severity == "warn":
            add_recording("pen_count_mismatch", "warn", msg)
        else:
            add_info("pen_count_mismatch", msg)
    if pen_rows and pen_server_time_rows == 0:
        add_recording(
            "legacy_pen_time",
            "warn",
            "Pen CSV has no local_ts_ms capture metadata; device timestamps are still usable.",
        )
    if watch_rows and server_time_rows == 0:
        add_recording("legacy_watch_time", "warn", "Watch CSV has no server_received_ms column.")
    if not is_active_session and expected_watch_samples and watch_rows < expected_watch_samples * 0.7:
        msg = "Watch rows are far below expected 50 Hz device/session duration."
        add_ml("low_watch_coverage", "warn", msg)
        add_recording("low_watch_coverage", "warn", msg)
    if start and pen_timestamp_years and start.year not in pen_timestamp_years and pen_server_time_rows == 0:
        add_info(
            "pen_clock_mismatch",
            "Pen internal timestamp year differs from wall-clock session year; device-relative time is used.",
        )

    watch_timeline, _watch_timeline_error = _load_watch_timeline(sid)
    pen_timeline, _pen_timeline_error = _load_pen_timeline(sid)
    watch_clock = _clock_summary(watch_timeline, "total_samples")
    pen_clock = _clock_summary(pen_timeline, "total_dots")
    intervals = _pen_intervals(pen_timeline)
    sync_estimate = _estimate_sync_drift(watch_timeline, pen_timeline, intervals)

    watch_local_start = watch_clock.get("start_ms")
    watch_local_end = watch_clock.get("end_ms")
    pen_local_dots = [r for r in pen_timeline if r.get("local_ts") is not None]
    pen_dots_in_watch_range = [
        r for r in pen_local_dots
        if watch_local_start is not None and watch_local_end is not None
        and watch_local_start <= r["local_ts"] <= watch_local_end
    ]
    pen_range_pct = (
        len(pen_dots_in_watch_range) / len(pen_local_dots)
        if pen_local_dots else None
    )
    if pen_range_pct is not None and pen_range_pct < 0.95:
        add_ml(
            "pen_dots_outside_watch_range",
            "warn",
            f"Only {pen_range_pct:.1%} of pen dots fall inside the watch capture range.",
        )

    ml_readiness = _score_payload(ml_issues)
    recording_health = _score_payload(recording_issues)
    combined_issues = []
    seen_issues = set()
    for issue in ml_issues + recording_issues + info_issues:
        key = (issue.get("code"), issue.get("severity"))
        if key in seen_issues:
            continue
        seen_issues.add(key)
        combined_issues.append(issue)
    return {
        "session_id": sid,
        "person_id": row.get("person_id", ""),
        "description": row.get("description", ""),
        "status": row.get("status", ""),
        "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        "expected_watch_samples_50hz": expected_watch_samples,
        "clock_model": {
            "canonical_ml_timeline": "device_relative_ms",
            "watch_device_timestamp": "ts",
            "pen_device_timestamp": "timestamp",
            "server_times": "capture metadata only",
        },
        "watch": {
            "path": str(watch_path),
            "exists": watch_path.exists(),
            "rows": watch_rows,
            "sessions_csv_rows": session_watch_samples,
            "estimated_hz": round(watch_est_hz, 2) if watch_est_hz else None,
            "median_dt_ms": round(median_dt_ms, 2) if median_dt_ms else None,
            "has_accelerometer": accel_rows > 0,
            "accelerometer_rows": accel_rows,
            "has_gyroscope": gyro_rows > 0,
            "gyroscope_rows": gyro_rows,
            "has_server_received_ms": server_time_rows > 0,
            "server_received_ms_rows": server_time_rows,
            "sequence_batches": len(watch_sequences),
            "sequence_gaps": sequence_gaps,
            "schema": watch_fieldnames,
        },
        "pen": {
            "path": str(pen_path),
            "exists": pen_path.exists(),
            "rows": pen_rows,
            "sessions_csv_rows": session_pen_samples,
            "has_server_time": pen_server_time_rows > 0,
            "server_time_rows": pen_server_time_rows,
            "timestamp_year_min": min(pen_timestamp_years) if pen_timestamp_years else None,
            "timestamp_year_max": max(pen_timestamp_years) if pen_timestamp_years else None,
            "schema": pen_fieldnames,
        },
        "ml_readiness": ml_readiness,
        "recording_health": recording_health,
        "diagnostics": {
            "clock_model": {
                "canonical_ml_timeline": "device_relative_ms",
                "watch_device_timestamp": "ts",
                "pen_device_timestamp": "timestamp",
                "server_times": "capture metadata only",
            },
            "sync_estimate": sync_estimate,
            "sync_diagnostic": _sync_diagnostic(sync_estimate),
            "counts": {
                "watch_rows": watch_rows,
                "watch_sessions_csv_rows": session_watch_samples,
                "watch_count_delta": watch_count_delta,
                "watch_count_tolerance": watch_count_tolerance,
                "pen_rows": pen_rows,
                "pen_sessions_csv_rows": session_pen_samples,
                "pen_count_delta": pen_count_delta,
                "pen_count_tolerance": pen_count_tolerance,
            },
            "coverage": {
                "expected_watch_samples_50hz": expected_watch_samples,
                "pen_dots_in_watch_range_pct": round(pen_range_pct, 4)
                if pen_range_pct is not None else None,
                "watch_device_duration_seconds": watch_clock.get("device_duration_seconds"),
                "pen_device_duration_seconds": pen_clock.get("device_duration_seconds"),
            },
            "info": info_issues,
        },
        "issues": combined_issues,
        "quality": ml_readiness["status"],
    }


# ── Detaillierte Session-Validierung (für /sessions/{id}/validation) ──────────

def _session_validation(session_id: str) -> dict[str, Any]:
    """
    Tiefe Validierung einer einzelnen Session: Zeitstempel-Überlappung,
    Clock-Drift, Sync-Schätzung und Timeline-Aufbereitung für den Dashboard-Chart.
    """
    from .utils import _safe_file_id  # lokaler Import vermeidet Zirkularität nicht — hier OK

    safe_id = _safe_file_id(session_id)
    watch_rows, watch_error = _load_watch_timeline(safe_id)
    pen_rows, pen_error = _load_pen_timeline(safe_id)
    issues = []
    if watch_error:
        issues.append({"code": "watch_missing_or_unreadable", "severity": "bad", "message": watch_error})
    if pen_error:
        issues.append({"code": "pen_missing_or_unreadable", "severity": "bad", "message": pen_error})

    watch = _clock_summary(watch_rows, "total_samples")
    pen = _clock_summary(pen_rows, "total_dots")
    intervals = _pen_intervals(pen_rows)

    if not watch_rows and not watch_error:
        issues.append({
            "code": "no_watch_samples",
            "severity": "bad",
            "message": "Watch CSV exists but contains no samples.",
        })
    if not pen_rows and not pen_error:
        issues.append({
            "code": "no_pen_dots",
            "severity": "warn",
            "message": "Pen CSV exists but contains no dots.",
        })

    watch_start = watch["start_ms"]
    watch_end = watch["end_ms"]
    pen_start = pen["start_ms"]
    pen_end = pen["end_ms"]
    streams_overlap = (
        None not in (watch_start, watch_end, pen_start, pen_end)
        and watch_start <= pen_end and pen_start <= watch_end
    )
    dots_with_local = [r for r in pen_rows if r.get("local_ts") is not None]
    dots_in_watch_range = [
        r for r in dots_with_local
        if watch_start is not None and watch_end is not None
        and watch_start <= r["local_ts"] <= watch_end
    ]
    pct = len(dots_in_watch_range) / len(dots_with_local) if dots_with_local else None

    if watch_rows and not any(r.get("local_ts") is not None for r in watch_rows):
        issues.append({
            "code": "watch_no_local_timeline",
            "severity": "warn",
            "message": "Watch rows have no local_ts_ms/server_received_ms/local_ts capture metadata.",
        })
    if pen_rows and not dots_with_local:
        issues.append({
            "code": "pen_no_local_timeline",
            "severity": "warn",
            "message": "Pen rows have no local_ts_ms/local_ts capture metadata.",
        })
    if None not in (watch_start, watch_end, pen_start, pen_end) and not streams_overlap:
        issues.append({
            "code": "streams_do_not_overlap",
            "severity": "bad",
            "message": "Pen and watch local timelines do not overlap.",
        })
    if pct is not None and pct < 0.95:
        issues.append({
            "code": "pen_dots_outside_watch_range",
            "severity": "warn",
            "message": f"Only {pct:.1%} of pen dots fall inside the watch local range.",
        })

    relative_clock_drift = None
    source_clock_offset_gap = None
    if (
        watch.get("source_to_local_drift_ms") is not None
        and pen.get("source_to_local_drift_ms") is not None
    ):
        relative_clock_drift = (
            pen["source_to_local_drift_ms"] - watch["source_to_local_drift_ms"]
        )
    if (
        watch.get("source_to_local_offset_median_ms") is not None
        and pen.get("source_to_local_offset_median_ms") is not None
    ):
        source_clock_offset_gap = (
            pen["source_to_local_offset_median_ms"]
            - watch["source_to_local_offset_median_ms"]
        )
        if abs(source_clock_offset_gap) > 1000:
            issues.append({
                "code": "source_clocks_not_shared",
                "severity": "info",
                "message": (
                    "Pen and watch source timestamps are not on the same clock. "
                    f"Median source-to-local offsets differ by {source_clock_offset_gap:.0f}ms; "
                    "device-relative timestamps are used for ML alignment."
                ),
            })

    sync = _estimate_sync_drift(watch_rows, pen_rows, intervals)
    if not sync.get("usable"):
        issues.append({
            "code": "sync_drift_not_estimated",
            "severity": "info",
            "message": sync.get("reason", "Sync drift could not be estimated."),
        })

    local_session_start = min(
        [v for v in (watch_start, pen_start) if v is not None],
        default=None,
    )
    timeline_intervals = []
    if local_session_start is not None:
        for interval in intervals:
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

    return {
        "session_id": safe_id,
        "status": _quality_status(issues),
        "timestamp_sources": {
            "canonical_ml_timeline": "device_relative_ms",
            "watch_source": "watch ts",
            "pen_source": "pen timestamp",
            "local_timeline": "local_ts_ms if present, else server_received_ms/local_ts fallback",
            "note": (
                "Device timestamps define within-stream timing. Local/server times are "
                "used only as capture metadata and, when available, as a coarse session anchor."
            ),
        },
        "watch": watch,
        "pen": pen,
        "overlap": {
            "start_offset_ms": (
                pen_start - watch_start if None not in (pen_start, watch_start) else None
            ),
            "end_offset_ms": (
                watch_end - pen_end if None not in (watch_end, pen_end) else None
            ),
            "streams_overlap": streams_overlap,
            "pen_dots_in_watch_range_pct": round(pct, 4) if pct is not None else None,
        },
        "source_clocks": {
            "watch_source_duration_seconds": watch.get("source_duration_seconds"),
            "pen_source_duration_seconds": pen.get("source_duration_seconds"),
            "watch_source_to_local_drift_ms": watch.get("source_to_local_drift_ms"),
            "pen_source_to_local_drift_ms": pen.get("source_to_local_drift_ms"),
            "relative_pen_vs_watch_clock_drift_ms": round(relative_clock_drift, 3)
            if relative_clock_drift is not None else None,
            "source_clock_offset_gap_ms": round(source_clock_offset_gap, 3)
            if source_clock_offset_gap is not None else None,
            "watch_source_to_local_offset_median_ms": watch.get("source_to_local_offset_median_ms"),
            "pen_source_to_local_offset_median_ms": pen.get("source_to_local_offset_median_ms"),
        },
        "sync_estimate": sync,
        "sync_diagnostic": _sync_diagnostic(sync),
        "timeline_for_chart": {
            "session_start_ms": local_session_start,
            "watch_start_s": (
                round((watch_start - local_session_start) / 1000, 3)
                if None not in (watch_start, local_session_start) else None
            ),
            "watch_end_s": (
                round((watch_end - local_session_start) / 1000, 3)
                if None not in (watch_end, local_session_start) else None
            ),
            "pen_start_s": (
                round((pen_start - local_session_start) / 1000, 3)
                if None not in (pen_start, local_session_start) else None
            ),
            "pen_end_s": (
                round((pen_end - local_session_start) / 1000, 3)
                if None not in (pen_end, local_session_start) else None
            ),
            "duration_s": (
                round((max(watch_end or 0, pen_end or 0) - local_session_start) / 1000, 3)
                if local_session_start is not None and (watch_end is not None or pen_end is not None)
                else None
            ),
            "pen_events": timeline_intervals,
        },
        "device_timeline": {
            "watch_start_ms": watch.get("device_start_ms"),
            "watch_end_ms": watch.get("device_end_ms"),
            "watch_duration_seconds": watch.get("device_duration_seconds"),
            "pen_start_ms": pen.get("device_start_ms"),
            "pen_end_ms": pen.get("device_end_ms"),
            "pen_duration_seconds": pen.get("device_duration_seconds"),
        },
        "issues": issues,
    }
