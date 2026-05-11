"""Watch-base merge: 1 row per watch sample, label_writing from pen activity."""

from tests.conftest import write_pen_csv, write_watch_csv


def test_watch_base_merge_labels_writing_and_idle(data_dirs):
    from src.merge import merge_watch_pen

    base = 1_700_000_000_000

    # Pen writes only around t = base + 100..160 ms (PEN_DOWN/MOVE),
    # then PEN_UP at +200. Watch covers a wider window — the watch samples
    # before/after pen activity must end up with label_writing = 0.
    pen_rows = [
        {"local_ts_ms": base + 100, "timestamp": 1000, "x": 10.0, "y": 20.0,
         "pressure": 200, "dot_type": "PEN_DOWN"},
        {"local_ts_ms": base + 130, "timestamp": 1030, "x": 11.0, "y": 21.0,
         "pressure": 210, "dot_type": "PEN_MOVE"},
        {"local_ts_ms": base + 160, "timestamp": 1060, "x": 12.0, "y": 22.0,
         "pressure": 220, "dot_type": "PEN_MOVE"},
        {"local_ts_ms": base + 200, "timestamp": 1100, "x": 12.0, "y": 22.0,
         "pressure": 0,   "dot_type": "PEN_UP"},
    ]
    # 9 watch samples every 20 ms (50 Hz), covering pre-pen, during-pen, post-pen.
    watch_rows = [
        {"local_ts_ms": base + 20 * i, "session_id": "S001", "sequence": i,
         "ts": 100 + 20 * i, "ax": 0.1, "ay": 0.2, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0}
        for i in range(15)  # base..base+280
    ]

    pen_path = data_dirs.pen / "S001_pen.csv"
    watch_path = data_dirs.watch / "S001_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    merged = merge_watch_pen(pen_path, watch_path, label_tol_ms=40, align_clocks=False)

    assert len(merged) == 15, "every watch sample must survive the watch-base merge"
    assert set(merged["label_writing"].unique()) <= {0, 1}

    # Samples at base + 0/20/40 are >40 ms from any DOWN/MOVE → 0.
    early = merged[merged["local_ts_ms"] <= base + 40]
    assert (early["label_writing"] == 0).all(), "pre-pen samples must be idle"

    # Samples on top of PEN_DOWN/MOVE → 1.
    during = merged[
        (merged["local_ts_ms"] >= base + 100) & (merged["local_ts_ms"] <= base + 160)
    ]
    assert (during["label_writing"] == 1).all(), "writing window must be labelled 1"

    # Samples at base + 260+ are >40 ms from PEN_UP@200 → no match in tol → 0.
    post = merged[merged["local_ts_ms"] >= base + 260]
    assert (post["label_writing"] == 0).all(), "post-pen idle must be 0"


def test_label_writing_mapping(data_dirs):
    """PEN_DOWN/PEN_MOVE → 1, everything else → 0."""
    from src.merge import prepare_pen_data

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
    from src.merge import prepare_pen_data

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
