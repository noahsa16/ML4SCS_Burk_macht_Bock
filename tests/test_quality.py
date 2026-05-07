"""Quality engine: synthesize CSVs, assert which issues fire."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import write_pen_csv, write_watch_csv


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def _watch_row(ts_ms: int, sid: str = "S001", seq: int = 0,
               with_accel: bool = True, with_gyro: bool = True) -> dict:
    """A plausible 50 Hz watch sample row."""
    base = {
        "local_ts": _iso(ts_ms),
        "local_ts_ms": ts_ms,
        "session_id": sid,
        "sequence": seq,
        "sample_rate_hz": 50.0,
        "watch_sent_at": ts_ms,
        "phone_received_at": ts_ms,
        "server_received_ms": ts_ms,
        "source": "watch_phone_bridge",
        "ts": ts_ms - 100,  # device clock has its own epoch — offset is fine
    }
    if with_accel:
        base.update(ax=0.01, ay=0.02, az=0.98)
    if with_gyro:
        base.update(rx=0.0, ry=0.0, rz=0.0)
    return base


def _pen_row(ts_ms: int, dot_type: str = "PEN_MOVE", x: float = 10.0,
             y: float = 20.0) -> dict:
    return {
        "local_ts": _iso(ts_ms),
        "local_ts_ms": ts_ms,
        "timestamp": ts_ms - 922 * 86_400_000,  # pen clock is ~922 d behind, like real device
        "x": x, "y": y, "pressure": 200, "dot_type": dot_type,
        "tilt_x": 60, "tilt_y": 100,
        "section": 3, "owner": 27, "note": 746, "page": 3,
    }


def _session_row(sid: str, start_ms: int, end_ms: int,
                 pen_samples: int = 0, watch_samples: int = 0) -> dict:
    return {
        "session_id": sid,
        "person_id": "P01",
        "description": "test",
        "start_time": _iso(start_ms),
        "end_time": _iso(end_ms),
        "pen_samples": pen_samples,
        "watch_samples": watch_samples,
        "status": "completed",
    }


def _issue_codes(facts) -> set[str]:
    return {i["code"] for i in facts["issues"]}


def test_clean_session_has_no_blocking_issues(data_dirs):
    """Happy path: 30 s of 50 Hz watch + 30 s of pen dots, all in window."""
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    end_ms = start_ms + 30_000

    watch_rows = [_watch_row(start_ms + i * 20, seq=i // 10) for i in range(1500)]
    pen_rows = [_pen_row(start_ms + i * 25) for i in range(1200)]

    write_watch_csv(data_dirs.watch / "S001_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S001_pen.csv", pen_rows)
    row = _session_row("S001", start_ms, end_ms,
                       pen_samples=len(pen_rows), watch_samples=len(watch_rows))

    facts = _session_facts(row)
    codes = _issue_codes(facts)

    # No "bad"-severity issues should fire on a clean recording.
    bad = [i for i in facts["issues"]
           if i.get("ml_severity") == "bad" or i.get("recording_severity") == "bad"]
    assert bad == [], f"unexpected bad issues: {bad}"
    assert "data_outside_session_window" not in codes
    assert "no_watch_samples" not in codes
    assert "no_pen_samples" not in codes
    assert "missing_gyroscope" not in codes
    assert "missing_accelerometer" not in codes


def test_stale_data_outside_session_window_fires(data_dirs):
    """The bug we just fixed: pen+watch CSVs from an earlier window."""
    from src.server.quality import _session_facts

    # Session metadata says: tonight at 18:00, runs 30 s.
    session_start = 1_700_000_000_000
    session_end = session_start + 30_000

    # But CSV samples are from 10 hours earlier.
    stale_start = session_start - 10 * 3600 * 1000

    watch_rows = [_watch_row(stale_start + i * 20) for i in range(200)]
    pen_rows = [_pen_row(stale_start + i * 25) for i in range(100)]

    write_watch_csv(data_dirs.watch / "S002_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S002_pen.csv", pen_rows)
    row = _session_row("S002", session_start, session_end,
                       pen_samples=len(pen_rows), watch_samples=len(watch_rows))

    facts = _session_facts(row)
    codes = _issue_codes(facts)
    assert "data_outside_session_window" in codes

    issue = next(i for i in facts["issues"] if i["code"] == "data_outside_session_window")
    assert issue["ml_severity"] == "bad"
    assert issue["recording_severity"] == "bad"


def test_missing_gyroscope_fires(data_dirs):
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    watch_rows = [_watch_row(start_ms + i * 20, with_gyro=False) for i in range(500)]
    write_watch_csv(data_dirs.watch / "S003_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S003_pen.csv", [_pen_row(start_ms + 100)])
    row = _session_row("S003", start_ms, start_ms + 10_000,
                       pen_samples=1, watch_samples=len(watch_rows))

    codes = _issue_codes(_session_facts(row))
    assert "missing_gyroscope" in codes


def test_no_pen_samples_when_file_missing(data_dirs):
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    watch_rows = [_watch_row(start_ms + i * 20) for i in range(500)]
    write_watch_csv(data_dirs.watch / "S004_watch.csv", watch_rows)
    # No pen CSV written.
    row = _session_row("S004", start_ms, start_ms + 10_000,
                       pen_samples=0, watch_samples=len(watch_rows))

    codes = _issue_codes(_session_facts(row))
    assert "no_pen_samples" in codes


def test_count_mismatch_when_sessions_csv_lies(data_dirs):
    """sessions.csv says 1000 watch samples, but CSV only has 100."""
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    watch_rows = [_watch_row(start_ms + i * 20) for i in range(100)]
    pen_rows = [_pen_row(start_ms + i * 25) for i in range(50)]
    write_watch_csv(data_dirs.watch / "S005_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S005_pen.csv", pen_rows)
    row = _session_row("S005", start_ms, start_ms + 10_000,
                       pen_samples=50, watch_samples=1000)

    codes = _issue_codes(_session_facts(row))
    assert "watch_count_mismatch" in codes
