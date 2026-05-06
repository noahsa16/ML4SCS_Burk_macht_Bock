"""
Session-Qualität, Validierung und Reports.

Drei Sichten auf dieselben Fakten — alle gehen über _session_facts():
  _session_quality(row)    Listen-Ansicht (alle Sessions, klein)
  _session_validation(id)  Detail-Ansicht für Dashboard-Modal
  _session_report(row)     Voll angereicherter Report (Export)

Issues kommen aus ISSUE_SPECS — pro Code stehen check, threshold,
rationale und Severity-Map zentral; _make_issue() liefert konsistente
Dicts mit observed/threshold/rationale für Reports und Tooltips.

Read-only — kein Zugriff auf globalen State, keine Seiteneffekte.
"""

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Optional

from .config import DATA_RAW_PEN, DATA_RAW_WATCH
from .utils import _as_float, _as_int, _mad, _parse_iso, _row_local_ms

# ── Watch-Konfiguration: Quelle der Wahrheit ──────────────────────────────────
# Watch streamt CMDeviceMotion bei _TARGET_WATCH_HZ; alle Coverage- und
# Rate-Checks rechnen damit. Wenn der Watch-Code irgendwann auf 100 Hz geht,
# muss hier nur eine Zeile geändert werden.
_TARGET_WATCH_HZ      = 50.0
_WATCH_HZ_MIN         = 40.0   # ±20% Toleranz
_WATCH_HZ_MAX         = 60.0
_COVERAGE_PCT_MIN     = 0.7    # Anteil der erwarteten Samples
_PEN_IN_RANGE_PCT_MIN = 0.80   # vorher 0.95 — lockerer
_COUNT_TOL_FLOOR      = 20     # absolute Mindesttoleranz
_COUNT_TOL_PCT        = 0.02   # relative Toleranz (2%)

# ── Sync-Heuristik: Konstanten ────────────────────────────────────────────────
_TAP_MAX_DURATION_MS         = 1400
_TAP_MAX_DOTS                = 80
_PEAK_MIN_SEPARATION_MS      = 250
_MATCH_SEARCH_WINDOW_MS      = 1600
_CONFIDENCE_HIGH_MIN_MATCHES = 6
_CONFIDENCE_HIGH_MAX_ERROR   = 350
_CONFIDENCE_LOW_MAX_ERROR    = 900
_MAX_CANDIDATES              = 24
_CANDIDATES_KEEP_EACH        = 12

# ── Issue-Definitionen ────────────────────────────────────────────────────────
# Pro Code: was wird geprüft, wie heißt der Threshold, warum gibt es den Check,
# und welche Severity feuert in ml_readiness und recording_health?
# Severity None = der Score ignoriert dieses Issue.

@dataclass(frozen=True)
class IssueSpec:
    check: str
    rationale: str
    threshold_label: str
    ml_severity: Optional[str] = None        # "bad" | "warn" | None
    recording_severity: Optional[str] = None


ISSUE_SPECS: dict[str, IssueSpec] = {
    "no_watch_samples": IssueSpec(
        check="Watch CSV enthält Samples",
        rationale="Ohne Watch-IMU-Samples gibt es keinen Modell-Input.",
        threshold_label="rows > 0",
        ml_severity="bad", recording_severity="bad",
    ),
    "no_pen_samples": IssueSpec(
        check="Pen CSV enthält Dots",
        rationale="Pen-Dots liefern die Ground-Truth-Labels. Ohne sie kein Supervised Training.",
        threshold_label="dots > 0",
        ml_severity="bad", recording_severity="warn",
    ),
    "watch_no_device_time": IssueSpec(
        check="Watch-Spalte 'ts' (Device-Timestamp) ist befüllt",
        rationale="Der Device-Timestamp ist die kanonische ML-Zeitachse. Ohne ihn lassen sich Samples nicht ausrichten.",
        threshold_label="rows mit 'ts' > 0",
        ml_severity="bad", recording_severity="bad",
    ),
    "pen_no_device_time": IssueSpec(
        check="Pen-Spalte 'timestamp' (Device-Timestamp) ist befüllt",
        rationale="Der Device-Timestamp definiert die zeitliche Ordnung der Dots innerhalb des Strichs.",
        threshold_label="dots mit 'timestamp' > 0",
        ml_severity="bad", recording_severity="bad",
    ),
    "missing_gyroscope": IssueSpec(
        check="Watch-Samples enthalten rx/ry/rz (Gyroskop)",
        rationale="Gyroskop ist eine der zwei IMU-Achsen, die das Modell erwartet.",
        threshold_label="gyro_rows > 0",
        ml_severity="bad", recording_severity="bad",
    ),
    "missing_accelerometer": IssueSpec(
        check="Watch-Samples enthalten ax/ay/az (Beschleunigung)",
        rationale="Beschleunigungssensor ist die zweite IMU-Achse. Kommt im selben CMDeviceMotion-Frame wie Gyro — sollte nie einzeln fehlen.",
        threshold_label="accel_rows > 0",
        ml_severity="bad", recording_severity="bad",
    ),
    "watch_rate_out_of_range": IssueSpec(
        check="Geschätzte Watch-Sample-Rate (1000 / median(ts-Diffs))",
        rationale=(
            f"Watch ist auf {_TARGET_WATCH_HZ:.0f} Hz konfiguriert (MotionManager.requestedHz). "
            f"Abweichungen >±20% deuten auf Drops oder Fehlkonfiguration."
        ),
        threshold_label=f"{_WATCH_HZ_MIN:.0f}–{_WATCH_HZ_MAX:.0f} Hz",
        ml_severity="warn", recording_severity="warn",
    ),
    "sequence_gaps": IssueSpec(
        check="Lücken in den Batch-Sequence-Nummern der Watch",
        rationale="Eine fehlende Batch-Nummer entspricht ~10 verlorenen Samples. Trifft sowohl Trainingsdaten-Integrität als auch Pipeline-Diagnose.",
        threshold_label="gaps == 0",
        ml_severity="warn", recording_severity="warn",
    ),
    "watch_count_mismatch": IssueSpec(
        check="Watch-Zeilen in CSV vs. Eintrag in sessions.csv",
        rationale="Größere Abweichung deutet auf nicht abgeschlossenes Flushing oder veraltete Session-Buchhaltung.",
        threshold_label=f"|delta| ≤ max({_COUNT_TOL_FLOOR}, {_COUNT_TOL_PCT:.0%}·rows)",
        ml_severity=None, recording_severity="warn",
    ),
    "pen_count_mismatch": IssueSpec(
        check="Pen-Dots in CSV vs. Eintrag in sessions.csv",
        rationale="Größere Abweichung deutet auf nicht abgeschlossenes Flushing oder veraltete Session-Buchhaltung.",
        threshold_label=f"|delta| ≤ max({_COUNT_TOL_FLOOR}, {_COUNT_TOL_PCT:.0%}·dots)",
        ml_severity=None, recording_severity="warn",
    ),
    "legacy_pen_time": IssueSpec(
        check="Pen-CSV enthält local_ts_ms (Wall-Clock-Empfangszeit)",
        rationale="Ohne local_ts_ms fehlt der Wall-Clock-Anker zum Ausrichten von Pen und Watch. Device-relative Zeit funktioniert für Pen-internes weiterhin.",
        threshold_label="server_time_rows > 0",
        ml_severity=None, recording_severity="warn",
    ),
    "legacy_watch_time": IssueSpec(
        check="Watch-CSV enthält server_received_ms",
        rationale="Ohne server_received_ms fehlt einer der zwei Wall-Clock-Anker. Device-relative Zeit funktioniert weiterhin.",
        threshold_label="server_time_rows > 0",
        ml_severity=None, recording_severity="warn",
    ),
    "low_watch_coverage": IssueSpec(
        check=f"Watch-Zeilen vs. erwartete Samples bei {_TARGET_WATCH_HZ:.0f} Hz × Dauer",
        rationale=(
            f"Bei {_TARGET_WATCH_HZ:.0f} Hz erwarten wir ~{_TARGET_WATCH_HZ:.0f} Samples/s. "
            f"Unter {_COVERAGE_PCT_MIN:.0%} weist auf BLE-Drops oder pausierten Stream hin."
        ),
        threshold_label=f"rows ≥ {_COVERAGE_PCT_MIN:.0%} · expected",
        ml_severity="warn", recording_severity="warn",
    ),
    "pen_clock_mismatch": IssueSpec(
        check="Jahr im Pen-Device-Timestamp vs. Wall-Clock-Session-Jahr",
        rationale="Pen-Device-Uhr ist ggf. nicht gesetzt; ML-Alignment nutzt sowieso Device-relative Zeit.",
        threshold_label="information",
        ml_severity=None, recording_severity=None,
    ),
    "pen_dots_outside_watch_range": IssueSpec(
        check="Anteil der Pen-Dots innerhalb des Watch-local_ts-Bereichs",
        rationale=(
            f"Dots außerhalb des Watch-Capture-Fensters können nicht von IMU gelabelt werden. "
            f"Unter {_PEN_IN_RANGE_PCT_MIN:.0%} deutet auf zeitversetzten Start/Stopp."
        ),
        threshold_label=f"≥ {_PEN_IN_RANGE_PCT_MIN:.0%}",
        ml_severity="warn", recording_severity=None,
    ),
    "watch_read_error": IssueSpec(
        check="Watch-CSV ist lesbar",
        rationale="Korrupte CSV → keine Daten verwendbar.",
        threshold_label="kein I/O-Fehler",
        ml_severity="bad", recording_severity="bad",
    ),
    "pen_read_error": IssueSpec(
        check="Pen-CSV ist lesbar",
        rationale="Korrupte CSV → keine Daten verwendbar.",
        threshold_label="kein I/O-Fehler",
        ml_severity="bad", recording_severity="bad",
    ),
    "streams_do_not_overlap": IssueSpec(
        check="Watch- und Pen-Wall-Clock-Bereiche überlappen sich",
        rationale="Ohne überlappendes Capture-Fenster ist kein Labeling möglich.",
        threshold_label="overlap > 0",
        ml_severity="bad", recording_severity="bad",
    ),
    "source_clocks_not_shared": IssueSpec(
        check="Pen- und Watch-Geräteuhren teilen sich eine Epoche",
        rationale=(
            "Pen-Hardware-Uhr und Watch-Hardware-Uhr sind nicht miteinander synchronisiert "
            "(beim Moleskine-Pen normal — interne Uhr wird ab Werk nie gesetzt). "
            "Für session-level Overlap-Checks irrelevant. Beim sample-level Merge wird ein "
            "Sync-Offset gebraucht (Tap-Event o.ä.) — aktuell offen."
        ),
        threshold_label="|gap| < 1 s",
        ml_severity=None, recording_severity=None,  # rein informativ
    ),
}


# ── Issue-Helper ──────────────────────────────────────────────────────────────

def _make_issue(
    code: str,
    *,
    observed: Any = None,
    threshold: Optional[str] = None,
    message: Optional[str] = None,
    ml_override: Optional[str] = None,
    recording_override: Optional[str] = None,
) -> dict[str, Any]:
    """
    Baut ein angereichertes Issue-Dict.

    `severity` ist die "primäre" Severity (max von ml/recording) — frontend nutzt
    sie für Filterung. `ml_severity` und `recording_severity` werden separat
    für die zwei Score-Ansichten verwendet.
    """
    spec = ISSUE_SPECS.get(code)
    if spec is None:
        # Sicherheits-Fallback: unbekannter Code soll nicht crashen
        check, rationale, threshold_label = code, "", ""
        ml_sev, rec_sev = None, None
    else:
        check = spec.check
        rationale = spec.rationale
        threshold_label = spec.threshold_label
        ml_sev = ml_override if ml_override is not None else spec.ml_severity
        rec_sev = recording_override if recording_override is not None else spec.recording_severity

    primary = _max_severity([ml_sev, rec_sev]) or "info"
    return {
        "code": code,
        "severity": primary,
        "ml_severity": ml_sev,
        "recording_severity": rec_sev,
        "check": check,
        "threshold": threshold or threshold_label,
        "observed": observed,
        "rationale": rationale,
        "message": message or _default_message(code, observed, threshold or threshold_label),
    }


def _default_message(code: str, observed: Any, threshold: str) -> str:
    spec = ISSUE_SPECS.get(code)
    if not spec:
        return code
    parts = [spec.check]
    if observed is not None:
        parts.append(f"beobachtet: {observed}")
    if threshold:
        parts.append(f"erwartet: {threshold}")
    return " — ".join(parts)


_SEVERITY_ORDER = {"bad": 3, "warn": 2, "info": 1, None: 0}


def _max_severity(sevs: list[Optional[str]]) -> Optional[str]:
    best = None
    best_rank = 0
    for s in sevs:
        rank = _SEVERITY_ORDER.get(s, 0)
        if rank > best_rank:
            best = s
            best_rank = rank
    return best


def _quality_status(severities: list[Optional[str]]) -> str:
    s = _max_severity(severities)
    return s if s in ("bad", "warn", "info") else "ok"


def _score_payload(issues: list[dict[str, Any]], sev_key: str) -> dict[str, Any]:
    """Score-Payload für ml_readiness oder recording_health.

    Filtert nur Issues, die in dieser Sicht eine Severity tragen, und sortiert
    sie nach Severity-Buckets (Frontend-Kompatibilität).
    """
    relevant = [i for i in issues if i.get(sev_key)]
    return {
        "status": _quality_status([i[sev_key] for i in relevant]),
        "blockers": [_view_for(i, sev_key) for i in relevant if i[sev_key] == "bad"],
        "warnings": [_view_for(i, sev_key) for i in relevant if i[sev_key] == "warn"],
        "info":     [_view_for(i, sev_key) for i in relevant if i[sev_key] == "info"],
    }


def _view_for(issue: dict[str, Any], sev_key: str) -> dict[str, Any]:
    """Issue-Dict mit `severity` aus ml/recording-Sicht."""
    out = dict(issue)
    out["severity"] = issue[sev_key]
    return out


def _sync_diagnostic(sync: dict[str, Any]) -> dict[str, Any]:
    if sync.get("usable"):
        confidence = sync.get("confidence", "unknown")
        return {
            "status": "estimated",
            "label": "estimated",
            "message": f"Optionale Tap-/Peak-Kalibrierung verfügbar. Heuristik-Confidence: {confidence}.",
        }
    reason = sync.get("reason", "")
    if "Fewer than two" in reason:
        return {
            "status": "needs_explicit_tap_protocol",
            "label": "needs tap protocol",
            "message": "Kein zuverlässiges Tap-Muster erkannt. Reine Diagnose, kein Quality-Failure.",
        }
    return {
        "status": "not_required",
        "label": "not required",
        "message": (
            f"Keine explizite Sync-Kalibrierung nötig. Detail: {reason}"
            if reason else
            "Keine explizite Sync-Kalibrierung erkannt; das ist kein Quality-Failure."
        ),
    }


# ── CSV-Timeline laden ────────────────────────────────────────────────────────

def _load_watch_timeline(session_id: str) -> tuple[list[dict[str, Any]], Optional[str]]:
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
                acc_mag = math.sqrt(ax*ax + ay*ay + az*az) if None not in (ax, ay, az) else None
                gyro_mag = math.sqrt(rx*rx + ry*ry + rz*rz) if None not in (rx, ry, rz) else None
                rows.append({
                    "source_ts": source_ts,
                    "local_ts": local_ts,
                    "motion_mag": (gyro_mag if gyro_mag is not None else 0.0)
                    + 0.35 * (acc_mag if acc_mag is not None else 0.0),
                    "acc_mag": acc_mag,
                    "gyro_mag": gyro_mag,
                    "sequence": _as_int(row.get("sequence")),
                    "has_accel": acc_mag is not None,
                    "has_gyro": gyro_mag is not None,
                    "has_server_ms": _as_int(row.get("server_received_ms")) is not None,
                })
    except Exception as exc:
        return [], f"Could not read watch CSV: {exc}"
    return rows, None


def _load_pen_timeline(session_id: str) -> tuple[list[dict[str, Any]], Optional[str]]:
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
                    "has_local_ts_ms": _as_int(row.get("local_ts_ms")) is not None,
                })
    except Exception as exc:
        return [], f"Could not read pen CSV: {exc}"
    return rows, None


# ── Zeitstempel-Statistiken ───────────────────────────────────────────────────

def _clock_summary(rows: list[dict[str, Any]], count_key: str) -> dict[str, Any]:
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


# ── Watch-Bewegungs-Peaks (für optionale Sync-Heuristik) ──────────────────────

def _watch_peaks(rows: list[dict[str, Any]], max_peaks: int = 80) -> list[dict[str, Any]]:
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
        if last_ts is not None and source_ts - last_ts < _PEAK_MIN_SEPARATION_MS:
            if peaks and mag > peaks[-1]["motion_mag"]:
                peaks[-1] = {"source_ts": source_ts, "motion_mag": round(mag, 6)}
            continue
        peaks.append({"source_ts": source_ts, "motion_mag": round(mag, 6)})
        last_ts = source_ts
    return sorted(peaks, key=lambda r: r["motion_mag"], reverse=True)[:max_peaks]


def _estimate_sync_drift(
    watch_rows: list[dict[str, Any]],
    pen_rows: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
) -> dict[str, Any]:
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
            "usable": False, "confidence": "none", "method": "sync tap matching",
            "reason": "Need local and source timestamps for both streams.",
            "matched_events": [],
        }

    approx_pen_to_watch_offset = median(pen_offsets) - median(watch_offsets)
    peaks = _watch_peaks(watch_rows)
    if not peaks:
        return {
            "usable": False, "confidence": "none", "method": "sync tap matching",
            "reason": "No clear watch motion peaks found.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "matched_events": [],
        }

    pen_downs = [
        r for r in pen_rows
        if r.get("dot_type") == "PEN_DOWN" and r.get("source_ts") is not None
    ]
    short_intervals = [
        i for i in intervals
        if i.get("source_start_ms") is not None
        and i.get("duration_ms") is not None
        and i["duration_ms"] <= _TAP_MAX_DURATION_MS
        and i.get("dot_count", 9999) <= _TAP_MAX_DOTS
    ]
    candidate_ts = [i["source_start_ms"] for i in short_intervals] or [
        r["source_ts"] for r in pen_downs
    ]
    if not candidate_ts:
        return {
            "usable": False, "confidence": "none", "method": "sync tap matching",
            "reason": "No PEN_DOWN candidates found.",
            "approx_pen_to_watch_offset_ms": round(approx_pen_to_watch_offset, 3),
            "matched_events": [],
        }

    candidate_ts = sorted(candidate_ts)
    if len(candidate_ts) > _MAX_CANDIDATES:
        candidate_ts = candidate_ts[:_CANDIDATES_KEEP_EACH] + candidate_ts[-_CANDIDATES_KEEP_EACH:]

    peak_by_ts = sorted(peaks, key=lambda p: p["source_ts"])
    matches: list[dict[str, Any]] = []
    for pen_ts in candidate_ts:
        predicted = pen_ts + approx_pen_to_watch_offset
        nearest = min(peak_by_ts, key=lambda peak: abs(peak["source_ts"] - predicted), default=None)
        if not nearest:
            continue
        error = nearest["source_ts"] - predicted
        if abs(error) <= _MATCH_SEARCH_WINDOW_MS:
            matches.append({
                "pen_source_ms": pen_ts,
                "watch_peak_source_ms": nearest["source_ts"],
                "offset_ms": round(nearest["source_ts"] - pen_ts, 3),
                "error_from_local_anchor_ms": round(error, 3),
                "watch_motion_mag": nearest["motion_mag"],
            })

    if len(matches) < 2:
        return {
            "usable": False, "confidence": "low", "method": "sync tap matching",
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
    max_error = max(abs(e) for e in errors)
    confidence = "high" if len(matches) >= _CONFIDENCE_HIGH_MIN_MATCHES and max_error <= _CONFIDENCE_HIGH_MAX_ERROR else "medium"
    if max_error > _CONFIDENCE_LOW_MAX_ERROR:
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
        "max_abs_error_from_local_anchor_ms": round(max_error, 3),
        "watch_peaks_found": len(peaks),
        "pen_candidates_found": len(candidate_ts),
        "matched_events": matches,
        "note": "Use an explicit start/end tap protocol before trusting this as calibration.",
    }


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
    watch_mtime = int(watch_path.stat().st_mtime_ns) if watch_path.exists() else 0
    pen_mtime = int(pen_path.stat().st_mtime_ns) if pen_path.exists() else 0
    cache_key = (watch_mtime, pen_mtime, hash(tuple(sorted(row.items()))))
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

    sync_estimate = _estimate_sync_drift(watch_rows, pen_rows, intervals)

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
        "common_overlap_seconds": common_overlap_seconds,
        "sync_estimate": sync_estimate,
        "start_year": start.year if start else None,
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
