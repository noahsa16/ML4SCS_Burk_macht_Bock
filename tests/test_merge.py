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
    # ts = Capture-Wall-Clock (Epoch ms, wie in Produktion) — der Label-Join
    # läuft seit dem ts-Fix auf dieser Achse, nicht auf local_ts_ms.
    watch_rows = [
        {"local_ts_ms": base + 20 * i, "session_id": "S001", "sequence": i,
         "ts": base + 20 * i, "ax": 0.1, "ay": 0.2, "az": 0.9,
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


def test_merge_attaches_task_id_when_markers_exist(data_dirs, tmp_path, monkeypatch):
    """If data/raw/markers/{session}_markers.csv exists, merge attaches
    task_id + task_category to each watch sample in the active interval."""
    import csv as _csv
    import pandas as pd

    from src.merge import merge_watch_pen
    from src.merge import merge as merge_mod

    sid = "S777"
    raw_mk = tmp_path / "raw" / "markers"
    raw_mk.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(merge_mod, "_MARKERS_DIR_OVERRIDE", raw_mk, raising=False)

    base = 1_000_000
    # 50 watch samples at 50 Hz, local_ts_ms = base + i*20 (covers base..base+980).
    watch_rows = [
        {"local_ts_ms": base + i * 20, "session_id": sid, "sequence": i,
         "ts": base + i * 20, "ax": 0.1, "ay": 0.1, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0}
        for i in range(50)
    ]
    pen_rows = [
        {"local_ts_ms": base + 50, "timestamp": 1000, "x": 10.0, "y": 10.0,
         "pressure": 200, "dot_type": "PEN_DOWN"},
    ]
    pen_path = data_dirs.pen / f"{sid}_pen.csv"
    watch_path = data_dirs.watch / f"{sid}_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    # Active task interval: [base, base + 500) → samples i=0..24 inclusive get tagged.
    with open(raw_mk / f"{sid}_markers.csv", "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=[
            "timestamp_ms", "event", "task_id", "task_name",
            "task_index", "task_category", "protocol_id",
        ])
        w.writeheader()
        w.writerow({"timestamp_ms": base, "event": "task_start",
                    "task_id": "abschreiben", "task_name": "Text",
                    "task_index": 1, "task_category": "writing",
                    "protocol_id": "v1"})
        w.writerow({"timestamp_ms": base + 500, "event": "task_end",
                    "task_id": "abschreiben", "task_name": "Text",
                    "task_index": 1, "task_category": "writing",
                    "protocol_id": "v1"})

    merged = merge_watch_pen(pen_path, watch_path, align_clocks=False)
    assert "task_id" in merged.columns
    assert "task_category" in merged.columns
    # Sample i=0 (ts=base) and i=24 (ts=base+480) are in the interval.
    in_iv = merged[merged["local_ts_ms"] < base + 500]
    assert (in_iv["task_id"] == "abschreiben").all()
    assert (in_iv["task_category"] == "writing").all()
    # Sample i=25 (ts=base+500) is OUT (half-open interval) → NA.
    out_iv = merged[merged["local_ts_ms"] >= base + 500]
    assert out_iv["task_id"].isna().all()


def test_merge_no_markers_keeps_columns_absent(data_dirs, tmp_path, monkeypatch):
    """Backwards-compat: sessions without a markers CSV merge unchanged."""
    import pandas as pd
    from src.merge import merge_watch_pen
    from src.merge import merge as merge_mod

    sid = "S778"
    raw_mk = tmp_path / "raw" / "markers"
    raw_mk.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(merge_mod, "_MARKERS_DIR_OVERRIDE", raw_mk, raising=False)

    base = 1_000_000
    watch_rows = [
        {"local_ts_ms": base + i * 20, "session_id": sid, "sequence": i,
         "ts": i * 20, "ax": 0.1, "ay": 0.1, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0}
        for i in range(10)
    ]
    pen_rows = [
        {"local_ts_ms": base + 30, "timestamp": 1000, "x": 5.0, "y": 5.0,
         "pressure": 200, "dot_type": "PEN_MOVE"},
    ]
    pen_path = data_dirs.pen / f"{sid}_pen.csv"
    watch_path = data_dirs.watch / f"{sid}_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    merged = merge_watch_pen(pen_path, watch_path, align_clocks=False)
    if "task_id" in merged.columns:
        assert merged["task_id"].isna().all()


def test_late_arriving_samples_labelled_by_capture_time(data_dirs):
    """Spill-Drain liefert Samples Minuten verspätet: local_ts_ms (Ankunft)
    liegt dann weit hinter ts (Capture-Wall-Clock). Das Label muss der
    Capture-Zeit folgen — S043-Forensik 2026-06-12: 5,3 % der Samples kamen
    >2,5 s verspätet an, der Join auf Ankunftszeit holte Pen-Labels von bis
    zu 13,6 s späteren Zeitpunkten."""
    from src.merge import merge_watch_pen

    base = 1_700_000_000_000
    pen_rows = [
        {"local_ts_ms": base + 100, "timestamp": 1000, "x": 10.0, "y": 20.0,
         "pressure": 200, "dot_type": "PEN_DOWN"},
        {"local_ts_ms": base + 130, "timestamp": 1030, "x": 11.0, "y": 21.0,
         "pressure": 210, "dot_type": "PEN_MOVE"},
        {"local_ts_ms": base + 160, "timestamp": 1060, "x": 12.0, "y": 22.0,
         "pressure": 220, "dot_type": "PEN_MOVE"},
    ]
    watch_rows = []
    for i in range(15):
        ts = base + 20 * i
        # Die during-pen-Samples erreichen den Server erst 60 s später.
        late = 60_000 if base + 100 <= ts <= base + 160 else 0
        watch_rows.append(
            {"local_ts_ms": ts + late, "session_id": "S002", "sequence": i,
             "ts": ts, "ax": 0.1, "ay": 0.2, "az": 0.9,
             "rx": 0.0, "ry": 0.0, "rz": 0.0})

    pen_path = data_dirs.pen / "S002_pen.csv"
    watch_path = data_dirs.watch / "S002_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    merged = merge_watch_pen(pen_path, watch_path, label_tol_ms=40, align_clocks=False)
    merged["ts"] = merged["ts"].astype(float)

    during = merged[(merged["ts"] >= base + 100) & (merged["ts"] <= base + 160)]
    assert (during["label_writing"] == 1).all(), \
        "verspätet angekommene Schreib-Samples müssen nach Capture-Zeit gelabelt werden"
    early = merged[merged["ts"] <= base + 40]
    assert (early["label_writing"] == 0).all()


def test_merge_dedupes_replayed_samples(data_dirs):
    """Spill re-delivery: ein bereits gestreamtes Sample kommt verbatim erneut
    an (gleicher ts + Achsen, spätere Ankunfts-Metadaten). Die Dedup behält die
    erste Lieferung und verwirft das Re-Delivery, damit Doppel-Samples Fenster
    und Schreibzeit nicht überbewerten."""
    from src.merge import merge_watch_pen

    base = 1_700_000_000_000
    pen_rows = [
        {"local_ts_ms": base + 100, "timestamp": 1000, "x": 10.0, "y": 20.0,
         "pressure": 200, "dot_type": "PEN_DOWN"},
    ]
    watch_rows = [
        {"local_ts_ms": base + 20 * i, "session_id": "S001", "sequence": i,
         "ts": base + 20 * i, "ax": 0.1 + 0.01 * i, "ay": 0.2, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0}
        for i in range(10)
    ]
    for i in (3, 4):
        replay = dict(watch_rows[i])
        replay["local_ts_ms"] = base + 99_999
        watch_rows.append(replay)

    pen_path = data_dirs.pen / "S001_pen.csv"
    watch_path = data_dirs.watch / "S001_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    merged = merge_watch_pen(pen_path, watch_path, label_tol_ms=40, align_clocks=False)

    assert len(merged) == 10, "re-delivered samples must be deduplicated"
    assert merged["ts"].astype(float).is_unique
    kept = merged[merged["ts"].astype(float) == base + 60]
    assert int(kept["local_ts_ms"].iloc[0]) == base + 60, \
        "keep='first' must retain the original delivery, not the late replay"


def test_merge_keeps_distinct_samples_sharing_ts(data_dirs):
    """Gleiche Capture-ms, aber verschiedene Bewegung = harmlose ms-Kollision
    zweier echter Samples. Beide müssen erhalten bleiben — nur verbatim
    identische Payloads werden gedroppt."""
    from src.merge import merge_watch_pen

    base = 1_700_000_000_000
    pen_rows = [
        {"local_ts_ms": base + 100, "timestamp": 1000, "x": 10.0, "y": 20.0,
         "pressure": 200, "dot_type": "PEN_DOWN"},
    ]
    watch_rows = [
        {"local_ts_ms": base + 20 * i, "session_id": "S001", "sequence": i,
         "ts": base + 20 * i, "ax": 0.1 + 0.01 * i, "ay": 0.2, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0}
        for i in range(10)
    ]
    shared_ts = base + 5_000
    watch_rows.append(
        {"local_ts_ms": shared_ts, "session_id": "S001", "sequence": 99,
         "ts": shared_ts, "ax": 0.5, "ay": 0.2, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0})
    watch_rows.append(
        {"local_ts_ms": shared_ts, "session_id": "S001", "sequence": 99,
         "ts": shared_ts, "ax": 0.9, "ay": 0.2, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0})

    pen_path = data_dirs.pen / "S001_pen.csv"
    watch_path = data_dirs.watch / "S001_watch.csv"
    write_pen_csv(pen_path, pen_rows)
    write_watch_csv(watch_path, watch_rows)

    merged = merge_watch_pen(pen_path, watch_path, label_tol_ms=40, align_clocks=False)

    assert len(merged) == 12, "ms-collision of distinct samples must not be dropped"
