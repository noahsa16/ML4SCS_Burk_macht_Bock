"""Alignment-Ergebnisse werden auf Disk gecacht.

Die Grid-Suche (coarse 80 + fine 1000 Shifts über jedes IMU-Sample einer
60–100-MB-CSV) lief bisher bei JEDEM Aufruf von /sessions/quality erneut,
für jede Session — die dominante Ursache der Dashboard-Latenz.
"""

from tests.conftest import write_pen_csv, write_watch_csv


def _fixture(data_dirs, sid="S001", n=400):
    base = 1_700_000_000_000
    pen_rows = [
        {"local_ts_ms": base + 2_000 + i * 25, "timestamp": 1000 + i * 25,
         "x": 10.0 + i * 0.1, "y": 20.0, "pressure": 200,
         "dot_type": "PEN_DOWN" if i % 20 == 0 else "PEN_MOVE"}
        for i in range(120)
    ]
    watch_rows = [
        {"local_ts_ms": base + 20 * i, "session_id": sid, "sequence": i,
         "ts": base + 20 * i,
         "ax": 0.1 + (0.4 if 100 <= i < 200 else 0.0), "ay": 0.2, "az": 0.9,
         "rx": 0.0, "ry": 0.0, "rz": 0.0}
        for i in range(n)
    ]
    write_pen_csv(data_dirs.pen / f"{sid}_pen.csv", pen_rows)
    write_watch_csv(data_dirs.watch / f"{sid}_watch.csv", watch_rows)


def test_alignment_is_computed_once_and_reused(data_dirs, monkeypatch):
    """Zweiter Aufruf darf die Grid-Suche nicht erneut ausführen."""
    import src.alignment as alignment
    from src.server import sync as sync_mod

    _fixture(data_dirs)

    calls = []
    real = alignment.match_pen_data

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(alignment, "match_pen_data", counting)

    first = sync_mod._estimate_sync_via_pen_match("S001")
    assert len(calls) == 1, "erster Aufruf muss rechnen"

    second = sync_mod._estimate_sync_via_pen_match("S001")
    assert len(calls) == 1, "zweiter Aufruf muss aus dem Cache kommen"
    assert second == first, "Cache-Treffer muss dasselbe Ergebnis liefern"


def test_alignment_cache_invalidates_when_csv_changes(data_dirs, monkeypatch):
    """Wächst die Watch-CSV (neue Aufnahme, Spill-Nachlieferung), muss neu
    gerechnet werden — sonst zeigt das Dashboard veraltete σ-Werte."""
    import src.alignment as alignment
    from src.server import sync as sync_mod

    _fixture(data_dirs, n=400)

    calls = []
    real = alignment.match_pen_data

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(alignment, "match_pen_data", counting)

    sync_mod._estimate_sync_via_pen_match("S001")
    assert len(calls) == 1

    _fixture(data_dirs, n=500)  # CSV neu geschrieben -> andere mtime/Größe
    sync_mod._estimate_sync_via_pen_match("S001")
    assert len(calls) == 2, "geänderte CSV muss den Cache invalidieren"
