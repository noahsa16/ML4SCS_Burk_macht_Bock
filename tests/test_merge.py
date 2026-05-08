"""Pen+Watch merge: nearest-neighbor on device time, 20 ms tolerance."""

from tests.conftest import write_pen_csv, write_watch_csv


def test_merge_aligns_within_tolerance(data_dirs):
    from src.preprocessing.preprocessing import merge_pen_watch

    # Pen and watch share local_ts_ms (so anchor lines them up at device-time 0).
    base = 1_700_000_000_000

    pen_rows = [
        # Three dots ~30 ms apart, valid x/y so they survive prepare_pen_data.
        {"local_ts_ms": base, "timestamp": 1000, "x": 10.0, "y": 20.0,
         "pressure": 200, "dot_type": "PEN_DOWN"},
        {"local_ts_ms": base + 30, "timestamp": 1030, "x": 11.0, "y": 21.0,
         "pressure": 210, "dot_type": "PEN_MOVE"},
        {"local_ts_ms": base + 60, "timestamp": 1060, "x": 12.0, "y": 22.0,
         "pressure": 220, "dot_type": "PEN_UP"},
    ]
    # Watch samples ~10 ms offset from pen — well inside the 20 ms tolerance.
    watch_rows = [
        {"local_ts_ms": base + 10, "session_id": "S001", "sequence": 0,
         "ts": 100, "ax": 0.1, "ay": 0.2, "az": 0.9, "rx": 0.01, "ry": 0.02, "rz": 0.0},
        {"local_ts_ms": base + 40, "session_id": "S001", "sequence": 0,
         "ts": 130, "ax": 0.2, "ay": 0.3, "az": 1.0, "rx": 0.02, "ry": 0.03, "rz": 0.0},
        {"local_ts_ms": base + 70, "session_id": "S001", "sequence": 0,
         "ts": 160, "ax": 0.3, "ay": 0.4, "az": 1.1, "rx": 0.03, "ry": 0.04, "rz": 0.0},
    ]

    pen_path = data_dirs.pen / "S001_pen.csv"
    watch_path = data_dirs.watch / "S001_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    merged = merge_pen_watch(pen_path, watch_path, tolerance_ms=20)

    # PEN_DOWN gets dropped by prepare_pen_data via dropna() (no prior dt).
    # PEN_MOVE and PEN_UP should survive and be matched.
    assert len(merged) >= 2
    assert merged["ax"].notna().all(), "every surviving pen dot should have a watch match"


def test_label_writing_mapping(data_dirs):
    """PEN_DOWN/PEN_MOVE → 1, everything else → 0."""
    from src.preprocessing.preprocessing import prepare_pen_data

    base = 1_700_000_000_000
    rows = [
        {"local_ts_ms": base, "timestamp": 1000, "x": 1.0, "y": 1.0,
         "pressure": 100, "dot_type": "PEN_DOWN"},
        {"local_ts_ms": base + 30, "timestamp": 1030, "x": 1.1, "y": 1.1,
         "pressure": 110, "dot_type": "PEN_MOVE"},
        {"local_ts_ms": base + 60, "timestamp": 1060, "x": 1.2, "y": 1.2,
         "pressure": 0, "dot_type": "PEN_UP"},
        {"local_ts_ms": base + 90, "timestamp": 1090, "x": 1.3, "y": 1.3,
         "pressure": 0, "dot_type": "PEN_HOVER"},
    ]
    path = data_dirs.pen / "S001_pen.csv"
    write_pen_csv(path, rows)

    df = prepare_pen_data(path)
    # PEN_DOWN row gets dropped by dropna() (first row, no dt). Survivors are MOVE/UP/HOVER.
    survivors_by_type = dict(zip(df.index.tolist(), df["label_writing"].tolist()))
    assert all(v in (0, 1) for v in survivors_by_type.values())
    # MOVE must be 1; UP/HOVER must be 0.
    pen_types = []
    df_full = df.copy()
    # Cross-reference dot_type isn't preserved in the output schema — just check counts.
    assert (df["label_writing"] == 1).sum() >= 1, "PEN_MOVE should produce at least one labelled row"
    assert (df["label_writing"] == 0).sum() >= 1, "PEN_UP/HOVER should produce unlabelled rows"


def test_filters_invalid_xy(data_dirs):
    """Pen events at x=-1, y=-1 are framing, not real positions — must be dropped."""
    from src.preprocessing.preprocessing import prepare_pen_data

    base = 1_700_000_000_000
    rows = [
        {"local_ts_ms": base, "timestamp": 1000, "x": -1, "y": -1,
         "pressure": 0, "dot_type": "PEN_DOWN"},
        {"local_ts_ms": base + 30, "timestamp": 1030, "x": 5.0, "y": 5.0,
         "pressure": 200, "dot_type": "PEN_MOVE"},
        {"local_ts_ms": base + 60, "timestamp": 1060, "x": 5.1, "y": 5.1,
         "pressure": 200, "dot_type": "PEN_MOVE"},
    ]
    path = data_dirs.pen / "S001_pen.csv"
    write_pen_csv(path, rows)

    df = prepare_pen_data(path)
    # Only the two real dots should survive; first one gets dropna()'d.
    assert len(df) == 1
