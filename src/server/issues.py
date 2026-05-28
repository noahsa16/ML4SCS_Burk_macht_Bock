"""
Issue-Definitionen, Severity-Logik und Score-Payload-Helfer.

Single Source of Truth für die ISSUE_SPECS-Tabelle: pro Code stehen check,
threshold, rationale und Severity-Map zentral. Auch hier liegen die
Konstanten, die quer durch quality.py / timelines.py / sync.py konsumiert
werden (Target-Hz, Coverage-Schwellen, Sync-Sigma-Grenzen).

Read-only: kein I/O, kein Zugriff auf globalen State.
"""

from dataclasses import dataclass
from typing import Any, Optional


# Confidence threshold on sigma_minimal_variance from pen_match. The Swiss
# reference treats values <= -2 as a clear well; we use the same.
_SYNC_SIGMA_OK_MAX  = -2.0   # at or below: trust the alignment
_SYNC_SIGMA_WEAK_MAX = -1.0  # below: weak signal, warn
                              # above _SYNC_SIGMA_WEAK_MAX: flat curve, fail

# ── Watch-Konfiguration: Quelle der Wahrheit ──────────────────────────────────
# Watch streamt CMDeviceMotion bei einer der Raten in _VALID_WATCH_HZ
# (50 Hz Klassik, 100 Hz seit H1/H3-Commits per Phone-App konfigurierbar).
# Quality-Checks ermitteln den effektiven Target je Session per Nearest-Match
# zur beobachteten Rate, statt eine harte Konstante anzunehmen.
_VALID_WATCH_HZ       = (50.0, 100.0)
_TARGET_WATCH_HZ      = 50.0   # Default fallback, only used when no rate is observable
_WATCH_HZ_TOL_PCT     = 0.20   # ±20% Toleranz um den Nearest-Valid-Target
_TARGET_AIRPODS_HZ    = 25.0   # CMHeadphoneMotionManager: fix bei 25 Hz
_COVERAGE_PCT_MIN     = 0.7    # Anteil der erwarteten Samples
_PEN_IN_RANGE_PCT_MIN = 0.80   # vorher 0.95 — lockerer
_COUNT_TOL_FLOOR      = 20     # absolute Mindesttoleranz
_COUNT_TOL_PCT        = 0.02   # relative Toleranz (2%)


def watch_target_hz(observed_hz: float | None) -> float:
    """Closest valid watch rate (50 or 100) to the observed rate.

    Used by both the rate-range check and the expected-samples coverage
    computation, so a 100 Hz session is no longer flagged out-of-range and
    its coverage check uses the right baseline.
    """
    if observed_hz is None:
        return _TARGET_WATCH_HZ
    return min(_VALID_WATCH_HZ, key=lambda c: abs(observed_hz - c))


def watch_in_range(observed_hz: float | None) -> bool:
    """True iff observed rate is within ±20 % of the closest valid target."""
    if observed_hz is None:
        return True  # not observable -> don't fail
    target = watch_target_hz(observed_hz)
    return abs(observed_hz - target) / target <= _WATCH_HZ_TOL_PCT


# Legacy aliases — historische Range-Konstanten, gleich gehalten zum Default
# damit Bestandsformate in der UI weiterhin "40-60 Hz" als Range zeigen wenn
# kein 100-Hz-Mode aktiv ist.
_WATCH_HZ_MIN         = _TARGET_WATCH_HZ * (1 - _WATCH_HZ_TOL_PCT)
_WATCH_HZ_MAX         = _TARGET_WATCH_HZ * (1 + _WATCH_HZ_TOL_PCT)


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
            f"Watch kann auf {' oder '.join(f'{r:.0f}' for r in _VALID_WATCH_HZ)} Hz "
            f"konfiguriert sein (MotionManager.requestedHz, per Phone-App). "
            f"Quality-Check ermittelt den effektiven Target via Nearest-Valid; "
            f"Abweichungen >±{int(_WATCH_HZ_TOL_PCT*100)}% deuten auf Drops "
            f"oder Fehlkonfiguration."
        ),
        threshold_label=(
            f"±{int(_WATCH_HZ_TOL_PCT*100)} % um nearest "
            f"{{{'/'.join(f'{int(r)}' for r in _VALID_WATCH_HZ)}}} Hz"
        ),
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
        check=f"Watch-Zeilen vs. erwartete Samples bei {{{'/'.join(f'{int(r)}' for r in _VALID_WATCH_HZ)}}} Hz × Dauer (per-Session nearest-match)",
        rationale=(
            "Erwartete Sample-Zahl skaliert mit dem für die Session konfigurierten "
            "Target-Hz (Nearest-Match aus 50/100 Hz). "
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
    "data_outside_session_window": IssueSpec(
        check="Sample-local_ts liegt innerhalb des Session-Start/End-Fensters",
        rationale=(
            "Wenn Watch- oder Pen-Daten Zeitstempel weit außerhalb des in sessions.csv "
            "verzeichneten Zeitfensters tragen, wurden vermutlich Stale-Files einer "
            "wiederverwendeten Session-ID angehängt. Die Daten gehören dann nicht "
            "zur aktuellen Session."
        ),
        threshold_label="Range innerhalb [start − 60 s, end + 60 s]",
        ml_severity="bad", recording_severity="bad",
    ),
    "no_airpods_samples": IssueSpec(
        check="AirPods-CSV enthält Samples",
        rationale=(
            "AirPods-Head-Motion ist als optionaler Feature-Stream gedacht. "
            "Fehlt er, lässt sich das Modell trotzdem trainieren — aber ohne "
            "Kopf-Information."
        ),
        threshold_label="rows > 0",
        ml_severity=None, recording_severity="warn",  # nur recording, ML egal
    ),
    "legacy_airpods_time": IssueSpec(
        check="AirPods-CSV enthält server_received_ms",
        rationale="Ohne server_received_ms fehlt der Wall-Clock-Anker zum Mergen mit Pen/Watch.",
        threshold_label="server_time_rows > 0",
        ml_severity=None, recording_severity="warn",
    ),
    "low_airpods_coverage": IssueSpec(
        check=f"AirPods-Zeilen vs. erwartete Samples bei {_TARGET_AIRPODS_HZ:.0f} Hz × Dauer",
        rationale=(
            f"CMHeadphoneMotionManager streamt fix bei {_TARGET_AIRPODS_HZ:.0f} Hz. "
            f"Unter {_COVERAGE_PCT_MIN:.0%} weist auf Disconnects oder pausierten Stream hin."
        ),
        threshold_label=f"rows ≥ {_COVERAGE_PCT_MIN:.0%} · expected",
        ml_severity=None, recording_severity="warn",
    ),
    "airpods_count_mismatch": IssueSpec(
        check="AirPods-Zeilen in CSV vs. Eintrag in sessions.csv",
        rationale="Größere Abweichung deutet auf nicht abgeschlossenes Flushing oder veraltete Session-Buchhaltung.",
        threshold_label=f"|delta| ≤ max({_COUNT_TOL_FLOOR}, {_COUNT_TOL_PCT:.0%}·rows)",
        ml_severity=None, recording_severity="warn",
    ),
    "low_sync_confidence": IssueSpec(
        check="Pen↔IMU Variance-Alignment liefert klares Minimum",
        rationale=(
            "Der Stroke-Varianz-Algorithmus (Schweizer TH-Zürich-Verfahren) "
            "liefert ein δ aber das Minimum ist nicht stark vom Mittelwert "
            "abgesetzt. Sample-level Merge wird ungenauer, session-level "
            "Overlap aber weiter gültig."
        ),
        threshold_label=f"sigma_minimal_variance ≤ {_SYNC_SIGMA_OK_MAX}",
        ml_severity="warn", recording_severity=None,
    ),
    "sync_failed": IssueSpec(
        check="Pen↔IMU Variance-Alignment findet überhaupt ein Minimum",
        rationale=(
            "Die Varianzkurve ist flach — kein zuverlässiger Pen↔IMU "
            "Zeitversatz erkennbar. Ursachen: zu wenig Strokes, viel "
            "Armbewegung beim Schreiben (z.B. Seite umblättern mid-Stroke), "
            "oder Strokes außerhalb des Watch-Capture-Fensters. "
            "Sample-level Merge sollte nicht verwendet werden."
        ),
        threshold_label=f"sigma_minimal_variance ≤ {_SYNC_SIGMA_WEAK_MAX}",
        ml_severity="bad", recording_severity=None,
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
