"""
Pfade, Feldnamen und CSV-Initialisierung.

Alles hier sind Konstanten — kein State, keine Logik.
"""

import csv
from pathlib import Path

from src.pen_schema import PEN_FIELDNAMES  # noqa: F401 — re-exported for other modules

ROOT = Path(__file__).parents[2]
DATA_RAW_WATCH   = ROOT / "data" / "raw" / "watch"
DATA_RAW_PEN     = ROOT / "data" / "raw" / "pen"
DATA_RAW_AIRPODS = ROOT / "data" / "raw" / "airpods"
SESSIONS_CSV   = ROOT / "data" / "sessions.csv"
DASHBOARD_HTML = ROOT / "dashboard.html"
STATIC_DIR     = ROOT / "static"
LOGS_DIR       = ROOT / "logs"

DATA_RAW_WATCH.mkdir(parents=True, exist_ok=True)
DATA_RAW_PEN.mkdir(parents=True, exist_ok=True)
DATA_RAW_AIRPODS.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DATA_RAW_MARKERS = ROOT / "data" / "raw" / "markers"
DATA_RAW_MARKERS.mkdir(parents=True, exist_ok=True)
MARKERS_DIR = DATA_RAW_MARKERS

MARKER_FIELDNAMES = [
    "timestamp_ms",
    "event",
    "task_id",
    "task_name",
    "task_index",
    "task_category",
    "protocol_id",
]

WATCH_FIELDNAMES = [
    "local_ts", "local_ts_ms", "session_id", "sequence", "sample_rate_hz",
    "watch_sent_at", "phone_received_at", "server_received_ms", "source",
    "ts", "ax", "ay", "az", "rx", "ry", "rz",
]
AIRPODS_FIELDNAMES = [
    "local_ts", "local_ts_ms", "session_id", "sequence", "sample_rate_hz",
    "airpods_sent_at", "phone_received_at", "server_received_ms", "source",
    "ts",
    "ax", "ay", "az",
    "rx", "ry", "rz",
    "qw", "qx", "qy", "qz",
    "gx", "gy", "gz",
]
SESSIONS_FIELDNAMES = [
    "session_id", "person_id", "description", "start_time", "end_time",
    "pen_samples", "watch_samples", "airpods_samples", "status",
    # Quality snapshot — written at session_stop, backfillable via
    # scripts/backfill_session_quality.py for older rows.
    "duration_seconds", "ml_status", "recording_status",
    "alignment_sigma", "verdict", "issue_codes",
    # Manual flag — when "yes", forces verdict='skip' regardless of σ/ML
    # status. Set via POST /sessions/{id}/flag from the UI.
    "flagged", "flag_note",
    # Study Mode metadata — empty for legacy / free-recording sessions.
    "study_mode",      # "" | "free" | "study" | "test"
    "protocol_id",     # protocol ID if a study was running, else ""
    "subject_index",   # frozen 1-based Latin Square index, or "" for free/test
]

if not SESSIONS_CSV.exists():
    with open(SESSIONS_CSV, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writeheader()
