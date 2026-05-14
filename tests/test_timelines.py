"""Tests for the pure helpers in src/server/timelines.py.

Targets the two pure-Python transformations that feed _session_facts:
  - _pen_intervals: PEN_DOWN/MOVE/UP state machine → interval list
  - _clock_summary: row list → wall-clock + source-clock stats
"""

from src.server.timelines import _clock_summary, _pen_intervals


def test_pen_intervals_groups_down_move_up_into_single_interval():
    """A clean DOWN → MOVE → MOVE → UP sequence must produce exactly one
    interval whose duration spans the first DOWN to the final UP."""
    rows = [
        {"dot_type": "PEN_DOWN", "source_ts": 1000, "local_ts": 5000},
        {"dot_type": "PEN_MOVE", "source_ts": 1050, "local_ts": 5050},
        {"dot_type": "PEN_MOVE", "source_ts": 1100, "local_ts": 5100},
        {"dot_type": "PEN_UP",   "source_ts": 1200, "local_ts": 5200},
    ]
    out = _pen_intervals(rows)
    assert len(out) == 1
    assert out[0]["source_start_ms"] == 1000
    assert out[0]["source_end_ms"] == 1200
    assert out[0]["duration_ms"] == 200
    # dot_count starts at 1 on DOWN, +1 per MOVE/HOVER, then +1 on UP.
    # DOWN(=1) + MOVE(2) + MOVE(3) + UP(+1 on close) = 4.
    assert out[0]["dot_count"] == 4


def test_pen_intervals_ignores_moves_without_open_down():
    """MOVE/UP events that arrive before any DOWN must be discarded —
    they are framing leftovers, not real strokes."""
    rows = [
        {"dot_type": "PEN_MOVE", "source_ts": 100, "local_ts": 1000},
        {"dot_type": "PEN_UP",   "source_ts": 200, "local_ts": 1100},
        {"dot_type": "PEN_DOWN", "source_ts": 500, "local_ts": 1500},
        {"dot_type": "PEN_UP",   "source_ts": 600, "local_ts": 1600},
    ]
    out = _pen_intervals(rows)
    assert len(out) == 1
    assert out[0]["source_start_ms"] == 500


def test_clock_summary_computes_drift_between_first_and_last_offset():
    """source_to_local_drift_ms = end_offset - start_offset. Used by the
    quality engine to detect a watch/pen clock that's running fast/slow."""
    # First row offset: 1000 - 100 = 900. Last row offset: 5500 - 500 = 5000.
    # Drift: 5000 - 900 = 4100 ms.
    rows = [
        {"source_ts": 100, "local_ts": 1000},
        {"source_ts": 200, "local_ts": 2050},
        {"source_ts": 500, "local_ts": 5500},
    ]
    summary = _clock_summary(rows, "row_count")
    assert summary["source_to_local_offset_start_ms"] == 900
    assert summary["source_to_local_offset_end_ms"] == 5000
    assert summary["source_to_local_drift_ms"] == 4100
    assert summary["row_count"] == 3
    assert summary["start_ms"] == 1000
    assert summary["end_ms"] == 5500


def test_clock_summary_handles_missing_timestamps_gracefully():
    """Rows without source_ts/local_ts must not crash and must not be
    counted toward offset stats."""
    rows = [
        {"source_ts": None, "local_ts": 1000},
        {"source_ts": 200, "local_ts": None},
        {"source_ts": None, "local_ts": None},
    ]
    summary = _clock_summary(rows, "row_count")
    assert summary["source_to_local_drift_ms"] is None
    assert summary["source_to_local_offset_median_ms"] is None
    assert summary["rows_with_local_ts"] == 1
    assert summary["rows_with_source_ts"] == 1
    assert summary["row_count"] == 3
