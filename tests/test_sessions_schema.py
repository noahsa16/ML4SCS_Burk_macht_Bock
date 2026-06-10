"""Sessions CSV schema migration test."""
from __future__ import annotations

import csv

from src.server.config import SESSIONS_FIELDNAMES
from src.server.csv_io import _ensure_csv_header


def test_legacy_csv_gets_new_columns(tmp_path):
    """Old CSV without study_mode/protocol_id/subject_index migrates cleanly."""
    legacy_fields = [
        f for f in SESSIONS_FIELDNAMES
        if f not in ("study_mode", "protocol_id", "subject_index", "watch_profile")
    ]
    csv_path = tmp_path / "sessions.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=legacy_fields)
        w.writeheader()
        w.writerow({k: "x" for k in legacy_fields})

    _ensure_csv_header(csv_path, SESSIONS_FIELDNAMES)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == SESSIONS_FIELDNAMES
        row = next(reader)
        # Old fields preserved
        assert row["session_id"] == "x"
        # New fields blank
        assert row["study_mode"] == ""
        assert row["protocol_id"] == ""
        assert row["subject_index"] == ""
        assert row["watch_profile"] == ""
