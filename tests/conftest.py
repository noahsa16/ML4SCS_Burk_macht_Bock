"""Common test setup: redirect data paths to a tmp dir per test."""

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.server.config import (  # noqa: E402
    AIRPODS_FIELDNAMES, SESSIONS_FIELDNAMES, WATCH_FIELDNAMES,
)
from src.pen_schema import PEN_FIELDNAMES  # noqa: E402


@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    """Point all DATA_RAW_* / SESSIONS_CSV constants at a tmp dir.

    Returns a small bag with the resolved paths so tests can write fixtures.
    """
    pen_dir = tmp_path / "raw" / "pen"
    watch_dir = tmp_path / "raw" / "watch"
    airpods_dir = tmp_path / "raw" / "airpods"
    pen_dir.mkdir(parents=True)
    watch_dir.mkdir(parents=True)
    airpods_dir.mkdir(parents=True)
    sessions_csv = tmp_path / "sessions.csv"
    with open(sessions_csv, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writeheader()

    # Patch every module that imported the constants directly.
    import src.server.config as config
    import src.server.csv_io as csv_io
    import src.server.quality as quality
    import src.server.routes as routes

    for mod in (config, csv_io, quality, routes):
        if hasattr(mod, "DATA_RAW_PEN"):
            monkeypatch.setattr(mod, "DATA_RAW_PEN", pen_dir, raising=False)
        if hasattr(mod, "DATA_RAW_WATCH"):
            monkeypatch.setattr(mod, "DATA_RAW_WATCH", watch_dir, raising=False)
        if hasattr(mod, "DATA_RAW_AIRPODS"):
            monkeypatch.setattr(mod, "DATA_RAW_AIRPODS", airpods_dir, raising=False)
        if hasattr(mod, "SESSIONS_CSV"):
            monkeypatch.setattr(mod, "SESSIONS_CSV", sessions_csv, raising=False)

    # csv_io caches watch CSV writers per path; reset so tests don't see stale handles.
    csv_io._watch_writers.clear() if hasattr(csv_io, "_watch_writers") else None
    csv_io._airpods_writers.clear() if hasattr(csv_io, "_airpods_writers") else None
    csv_io._pen_count_cache.clear() if hasattr(csv_io, "_pen_count_cache") else None
    csv_io._airpods_count_cache.clear() if hasattr(csv_io, "_airpods_count_cache") else None

    # Quality caches results by session id; clear so tests don't see stale facts.
    quality._facts_cache.clear()

    return type("DataDirs", (), {
        "pen": pen_dir,
        "watch": watch_dir,
        "airpods": airpods_dir,
        "sessions": sessions_csv,
    })


def write_pen_csv(path: Path, rows: list[dict]):
    """Write a pen CSV with the canonical schema. Missing keys default to ''."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PEN_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in PEN_FIELDNAMES})


def write_watch_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WATCH_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in WATCH_FIELDNAMES})


def write_airpods_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AIRPODS_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in AIRPODS_FIELDNAMES})


def append_session_row(sessions_csv: Path, row: dict):
    with open(sessions_csv, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow(
            {k: row.get(k, "") for k in SESSIONS_FIELDNAMES}
        )
