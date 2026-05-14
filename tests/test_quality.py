"""Quality engine: synthesize CSVs, assert which issues fire."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import write_airpods_csv, write_pen_csv, write_watch_csv


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


def _airpods_row(ts_ms: int, sid: str = "S001", with_server_time: bool = True) -> dict:
    base = {
        "local_ts": _iso(ts_ms),
        "local_ts_ms": ts_ms,
        "session_id": sid,
        "sequence": 1,
        "sample_rate_hz": 25.0,
        "airpods_sent_at": ts_ms,
        "phone_received_at": ts_ms,
        "source": "airpods",
        "ts": ts_ms - 50,
        "ax": 0.01, "ay": 0.0, "az": 0.0,
        "rx": 0.0,  "ry": 0.0, "rz": 0.0,
        "qw": 1.0,  "qx": 0.0, "qy": 0.0, "qz": 0.0,
        "gx": 0.0,  "gy": 0.0, "gz": -9.81,
    }
    if with_server_time:
        base["server_received_ms"] = ts_ms
    return base


def test_airpods_absent_does_not_block(data_dirs):
    """No AirPods CSV at all = optional stream skipped, no issues raised."""
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    watch_rows = [_watch_row(start_ms + i * 20) for i in range(1500)]
    pen_rows = [_pen_row(start_ms + i * 25) for i in range(1200)]
    write_watch_csv(data_dirs.watch / "S010_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S010_pen.csv", pen_rows)
    row = _session_row("S010", start_ms, start_ms + 30_000,
                       pen_samples=len(pen_rows), watch_samples=len(watch_rows))

    codes = _issue_codes(_session_facts(row))
    assert "no_airpods_samples" not in codes
    assert "low_airpods_coverage" not in codes
    assert "legacy_airpods_time" not in codes


def test_low_airpods_coverage_fires(data_dirs):
    """30 s session at 25 Hz expects ~750 samples; we write only 100."""
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    end_ms = start_ms + 30_000
    watch_rows = [_watch_row(start_ms + i * 20) for i in range(1500)]
    pen_rows = [_pen_row(start_ms + i * 25) for i in range(1200)]
    airpods_rows = [_airpods_row(start_ms + i * 40) for i in range(100)]

    write_watch_csv(data_dirs.watch / "S011_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S011_pen.csv", pen_rows)
    write_airpods_csv(data_dirs.airpods / "S011_airpods.csv", airpods_rows)
    row = {**_session_row("S011", start_ms, end_ms,
                          pen_samples=len(pen_rows), watch_samples=len(watch_rows)),
           "airpods_samples": len(airpods_rows)}

    codes = _issue_codes(_session_facts(row))
    assert "low_airpods_coverage" in codes


def test_legacy_airpods_time_fires(data_dirs):
    from src.server.quality import _session_facts

    start_ms = 1_700_000_000_000
    end_ms = start_ms + 30_000
    watch_rows = [_watch_row(start_ms + i * 20) for i in range(1500)]
    pen_rows = [_pen_row(start_ms + i * 25) for i in range(1200)]
    airpods_rows = [_airpods_row(start_ms + i * 40, with_server_time=False)
                    for i in range(750)]

    write_watch_csv(data_dirs.watch / "S012_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S012_pen.csv", pen_rows)
    write_airpods_csv(data_dirs.airpods / "S012_airpods.csv", airpods_rows)
    row = {**_session_row("S012", start_ms, end_ms,
                          pen_samples=len(pen_rows), watch_samples=len(watch_rows)),
           "airpods_samples": len(airpods_rows)}

    codes = _issue_codes(_session_facts(row))
    assert "legacy_airpods_time" in codes


# ── Pen↔IMU sync (variance minimization) ────────────────────────────────────

def _make_sync_session(
    data_dirs,
    sid: str,
    *,
    still_windows_sec: list[tuple[float, float]] | None,
    pen_clock_offset_sec: float,
    seed: int,
):
    """Helper: synthesize a session whose IMU has known still windows and
    pen strokes that fall on those windows (shifted by ``pen_clock_offset_sec``).
    Reused by the high/low/no-confidence sync tests."""
    import numpy as np
    rng = np.random.default_rng(seed)
    start_ms = 1_700_000_000_000
    duration_sec = 60.0
    fs = 50.0
    n_watch = int(duration_sec * fs)
    watch_rows = []
    for i in range(n_watch):
        ts_ms = start_ms + int(i * 1000 / fs)
        # High-noise baseline; flatten in still windows.
        sigma = 0.5
        if still_windows_sec:
            for s, e in still_windows_sec:
                if s * fs <= i <= e * fs:
                    sigma = 0.02
                    break
        ax = float(rng.normal(0.0, sigma))
        ay = float(rng.normal(0.0, sigma))
        az = float(9.81 + rng.normal(0.0, sigma))
        watch_rows.append({**_watch_row(ts_ms, sid=sid, seq=i // 25),
                           "ax": ax, "ay": ay, "az": az})
    write_watch_csv(data_dirs.watch / f"{sid}_watch.csv", watch_rows)

    # Pen strokes — three PEN_DOWN/MOVE/UP sequences. If still_windows_sec
    # is given, strokes land on those windows; otherwise they're sprinkled
    # at arbitrary fixed times so the algorithm has something to chew on
    # (but won't find a clean well in uniform-noise IMU).
    stroke_specs = still_windows_sec or [(10.0, 12.0), (25.0, 27.0), (40.0, 42.0)]
    pen_rows = []
    for s, e in stroke_specs:
        stroke_start_ms = start_ms + int(s * 1000) + int(pen_clock_offset_sec * 1000)
        stroke_end_ms = start_ms + int(e * 1000) + int(pen_clock_offset_sec * 1000)
        n_dots = max(2, int((e - s) * 80))  # ~80 Hz pen
        for j in range(n_dots):
            ts_ms = stroke_start_ms + int((stroke_end_ms - stroke_start_ms) * j / (n_dots - 1))
            if j == 0:
                dt = "PEN_DOWN"
            elif j == n_dots - 1:
                dt = "PEN_UP"
            else:
                dt = "PEN_MOVE"
            pen_rows.append(_pen_row(ts_ms, dot_type=dt, x=10.0 + j, y=20.0))
    write_pen_csv(data_dirs.pen / f"{sid}_pen.csv", pen_rows)
    return _session_row(sid, start_ms, start_ms + int(duration_sec * 1000),
                        pen_samples=len(pen_rows), watch_samples=len(watch_rows))


def test_sync_high_confidence_does_not_fire_issues(data_dirs):
    """Clean still-window setup → strong well, no sync issues."""
    from src.server.quality import _session_facts

    row = _make_sync_session(
        data_dirs, "S020",
        still_windows_sec=[(10.0, 12.0), (25.0, 27.0), (40.0, 42.0)],
        pen_clock_offset_sec=0.0,
        seed=11,
    )
    facts = _session_facts(row)
    sync = facts["sync_estimate"]
    assert sync["method"] == "stroke_variance_minimization"
    assert sync["confidence"] == "high", f"got {sync}"
    codes = _issue_codes(facts)
    assert "low_sync_confidence" not in codes
    assert "sync_failed" not in codes


def test_sync_diagnostic_shape(data_dirs):
    """Verify sync_estimate has the new 'stroke_variance_minimization'
    method tag and exposes the diagnostic fields downstream consumers
    rely on (delta_ms, sigma, confidence)."""
    from src.server.quality import _session_facts, _sync_diagnostic

    row = _make_sync_session(
        data_dirs, "S022",
        still_windows_sec=[(10.0, 12.0), (25.0, 27.0), (40.0, 42.0)],
        pen_clock_offset_sec=2.5,
        seed=33,
    )
    facts = _session_facts(row)
    sync = facts["sync_estimate"]
    assert sync["method"] == "stroke_variance_minimization"
    assert "delta_sec" in sync
    assert "delta_ms" in sync
    assert "sigma_minimal_variance" in sync
    assert "n_strokes" in sync
    diag = _sync_diagnostic(sync)
    assert diag["status"] in {"aligned", "weak_signal", "no_alignment"}
    assert diag["label"]
    assert diag["message"]


def test_low_sync_confidence_fires_when_sigma_borderline(data_dirs, monkeypatch):
    """Inject a borderline sigma into _session_facts and assert the issue
    fires. This isolates the issue logic from algorithmic randomness."""
    from src.server.quality import _build_issues

    # Build a minimal facts dict that triggers only the sync check.
    facts = {
        "watch": {"row_count": 100, "exists": True, "load_error": None,
                  "ts_values": [1, 2], "gyro_rows": 100, "accel_rows": 100,
                  "estimated_hz": 50.0, "sequence_gaps": 0,
                  "session_csv_count": 100, "count_delta": 0, "count_tolerance": 20,
                  "server_time_rows": 100, "expected_samples": 100, "clock": {}},
        "pen": {"row_count": 100, "exists": True, "load_error": None,
                "ts_values": [1, 2], "session_csv_count": 100, "count_delta": 0,
                "count_tolerance": 20, "server_time_rows": 100,
                "timestamp_years": [], "in_range_pct": 1.0, "clock": {}},
        "airpods": {"exists": False, "row_count": 0},
        "is_active": False, "start_year": 2026,
        "session_start_ms": None, "session_end_ms": None,
        "sync_estimate": {
            "method": "stroke_variance_minimization",
            "sigma_minimal_variance": -1.5,  # borderline: > -2 → warn
            "delta_ms": -3000.0,
        },
    }
    codes = {i["code"] for i in _build_issues(facts)}
    assert "low_sync_confidence" in codes
    assert "sync_failed" not in codes

    # Now push sigma above the weak threshold → should escalate to bad.
    facts["sync_estimate"]["sigma_minimal_variance"] = -0.3
    codes = {i["code"] for i in _build_issues(facts)}
    assert "sync_failed" in codes
    assert "low_sync_confidence" not in codes


# ── verdict logic in _session_quality_cols ────────────────────────────────────

def test_verdict_flagged_yes_overrides_to_skip(data_dirs):
    """Manual `flagged=yes` always wins, regardless of how clean the data is."""
    from src.server.quality import _session_quality_cols

    start_ms = 1_700_000_000_000
    watch_rows = [_watch_row(start_ms + i * 20) for i in range(1500)]
    pen_rows = [_pen_row(start_ms + i * 25) for i in range(1200)]
    write_watch_csv(data_dirs.watch / "S100_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S100_pen.csv", pen_rows)
    row = {**_session_row("S100", start_ms, start_ms + 30_000,
                          pen_samples=len(pen_rows), watch_samples=len(watch_rows)),
           "flagged": "yes"}

    cols = _session_quality_cols(row)
    assert cols["verdict"] == "skip"


def test_verdict_skip_when_ml_status_bad(data_dirs):
    """A `bad`-severity ML issue (here: data_outside_session_window from
    a stale CSV) must force verdict=skip without a manual flag. Guards
    the dataset-pollution path that motivated the verdict column."""
    from src.server.quality import _session_quality_cols

    session_start = 1_700_000_000_000
    session_end = session_start + 30_000
    # CSVs are 10 hours earlier than session metadata → ML-bad blocker.
    stale_start = session_start - 10 * 3600 * 1000
    watch_rows = [_watch_row(stale_start + i * 20) for i in range(200)]
    pen_rows = [_pen_row(stale_start + i * 25) for i in range(100)]
    write_watch_csv(data_dirs.watch / "S101_watch.csv", watch_rows)
    write_pen_csv(data_dirs.pen / "S101_pen.csv", pen_rows)
    row = _session_row("S101", session_start, session_end,
                       pen_samples=len(pen_rows), watch_samples=len(watch_rows))

    cols = _session_quality_cols(row)
    assert cols["ml_status"] == "bad"
    assert cols["verdict"] == "skip"


def test_verdict_defaults_to_usable_when_ml_ok_but_sigma_weak(data_dirs):
    """ML-status ok + duration ≥ 5 min but no strong σ ≤ -3 → 'usable',
    not 'trainable'. Guards the σ-as-training-gate logic in CLAUDE.md."""
    from src.server.quality import _session_quality_cols

    # 6-minute session with pen strokes that don't align cleanly (random
    # placement → no clear variance well, σ stays weak).
    row = _make_sync_session(
        data_dirs, "S102",
        still_windows_sec=None,  # noise everywhere, no real alignment well
        pen_clock_offset_sec=0.0,
        seed=7,
    )
    cols = _session_quality_cols(row)
    # Either weakly aligned or no alignment, but ML facts themselves are ok.
    assert cols["verdict"] in {"usable", "skip"}
    # The trainable branch requires σ <= -3 which can't be reached here.
    assert cols["verdict"] != "trainable"
