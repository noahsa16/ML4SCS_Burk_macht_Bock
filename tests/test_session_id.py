"""Regression: _next_session_id must skip IDs that exist anywhere on disk."""

from tests.conftest import append_session_row, write_pen_csv, write_watch_csv


def test_increments_from_sessions_csv(data_dirs):
    from src.server.csv_io import _next_session_id
    assert _next_session_id() == "S001"

    append_session_row(data_dirs.sessions, {
        "session_id": "S007", "person_id": "p", "start_time": "x",
        "end_time": "y", "pen_samples": 0, "watch_samples": 0, "status": "completed",
    })
    assert _next_session_id() == "S008"


def test_skips_id_with_stale_pen_csv(data_dirs):
    """Today's bug: an orphan pen CSV must not be silently re-used."""
    from src.server.csv_io import _next_session_id

    write_pen_csv(data_dirs.pen / "S042_pen.csv", [])
    assert _next_session_id() == "S043"


def test_skips_id_with_stale_watch_csv(data_dirs):
    from src.server.csv_io import _next_session_id

    write_watch_csv(data_dirs.watch / "S099_watch.csv", [])
    assert _next_session_id() == "S100"


def test_skips_id_with_stale_markers_csv(data_dirs, monkeypatch, tmp_path):
    """A stale markers/Sxxx_markers.csv must also force _next_session_id past it."""
    from src.server import csv_io
    from src.server import config as config_mod

    markers_dir = tmp_path / "raw" / "markers"
    markers_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(csv_io, "MARKERS_DIR", markers_dir, raising=False)
    monkeypatch.setattr(config_mod, "MARKERS_DIR", markers_dir, raising=False)

    (markers_dir / "S077_markers.csv").write_text("timestamp_ms,event\n")
    assert csv_io._next_session_id() == "S078"


def test_takes_max_across_all_sources(data_dirs):
    from src.server.csv_io import _next_session_id

    append_session_row(data_dirs.sessions, {
        "session_id": "S010", "status": "completed",
    })
    write_pen_csv(data_dirs.pen / "S025_pen.csv", [])
    write_watch_csv(data_dirs.watch / "S015_watch.csv", [])
    assert _next_session_id() == "S026"
