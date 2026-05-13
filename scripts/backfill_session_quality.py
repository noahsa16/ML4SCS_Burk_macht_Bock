#!/usr/bin/env python3
"""Backfill the quality columns of every row in sessions.csv.

Run after the schema migration that introduced
duration_seconds / ml_status / recording_status / alignment_sigma /
verdict / issue_codes — these were added later and old rows have
them empty until this script (or a fresh session_stop) fills them.

Usage:
    python scripts/backfill_session_quality.py [--force]

Without ``--force`` only rows where the quality columns are empty
are recomputed; with ``--force`` every row is rewritten regardless.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.server.config import SESSIONS_CSV, SESSIONS_FIELDNAMES
from src.server.csv_io import _ensure_csv_header
from src.server.quality import _session_quality_cols

QUALITY_COLS = (
    "duration_seconds", "ml_status", "recording_status",
    "alignment_sigma", "verdict", "issue_codes",
)


def _row_needs_backfill(row: dict[str, str]) -> bool:
    return any(not (row.get(c) or "").strip() for c in QUALITY_COLS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="recompute every row, even ones already populated")
    args = parser.parse_args()

    _ensure_csv_header(SESSIONS_CSV, SESSIONS_FIELDNAMES)

    with open(SESSIONS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("sessions.csv is empty — nothing to backfill.")
        return

    touched, skipped, failed = 0, 0, 0
    for row in rows:
        if not args.force and not _row_needs_backfill(row):
            skipped += 1
            continue
        sid = row.get("session_id", "")
        try:
            row.update(_session_quality_cols(row))
            touched += 1
            print(f"  {sid}: {row.get('verdict')} · "
                  f"σ={row.get('alignment_sigma') or '—'} · "
                  f"ml={row.get('ml_status')} · "
                  f"dur={row.get('duration_seconds') or '—'}s")
        except Exception as exc:
            failed += 1
            print(f"  {sid}: FAILED — {exc}")

    with open(SESSIONS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in SESSIONS_FIELDNAMES})

    print(f"\nDone — touched {touched}, skipped {skipped}, failed {failed} "
          f"(of {len(rows)} total).")


if __name__ == "__main__":
    main()
