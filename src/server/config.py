"""
Pfade, Feldnamen und CSV-Initialisierung.

Alles hier sind Konstanten — kein State, keine Logik.
Wird von allen anderen Modulen importiert, darf also selbst nichts importieren.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).parents[2]
DATA_RAW_WATCH = ROOT / "data" / "raw" / "watch"
DATA_RAW_PEN   = ROOT / "data" / "raw" / "pen"
SESSIONS_CSV   = ROOT / "data" / "sessions.csv"
DASHBOARD_HTML = ROOT / "dashboard.html"

DATA_RAW_WATCH.mkdir(parents=True, exist_ok=True)
DATA_RAW_PEN.mkdir(parents=True, exist_ok=True)

WATCH_FIELDNAMES = [
    "local_ts", "local_ts_ms", "session_id", "sequence", "sample_rate_hz",
    "watch_sent_at", "phone_received_at", "server_received_ms", "source",
    "ts", "ax", "ay", "az", "rx", "ry", "rz",
]
PEN_FIELDNAMES = [
    "local_ts", "local_ts_ms",
    "timestamp", "x", "y", "pressure", "dot_type",
    "tilt_x", "tilt_y", "section", "owner", "note", "page",
]
SESSIONS_FIELDNAMES = [
    "session_id", "person_id", "start_time", "end_time",
    "pen_samples", "watch_samples", "status",
]

if not SESSIONS_CSV.exists():
    with open(SESSIONS_CSV, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writeheader()
