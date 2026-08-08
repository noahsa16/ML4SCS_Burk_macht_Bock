"""Der Quality-Snapshot pro Session wird auf Disk gecacht.

`_session_facts` parst pro Session die komplette Watch-CSV (bei 74 Sessions
1,5 GB → ~70 s). Der In-Memory-Cache überlebt keinen Serverneustart, also
zahlte der erste Aufruf von /sessions/quality diese Zeit jedes Mal neu.
Der Snapshot selbst ist nur ~2,4 KB — persistent cachebar.
"""

from tests.conftest import write_pen_csv, write_watch_csv
from tests.test_quality import _pen_row, _session_row, _watch_row


def _fixture(data_dirs, sid="S001", start_ms=1_700_000_000_000, n=400):
    write_watch_csv(data_dirs.watch / f"{sid}_watch.csv",
                    [_watch_row(start_ms + i * 20, sid=sid, seq=i) for i in range(n)])
    write_pen_csv(data_dirs.pen / f"{sid}_pen.csv",
                  [_pen_row(start_ms + 1000 + i * 25) for i in range(60)])
    return _session_row(sid, start_ms, start_ms + n * 20,
                        pen_samples=60, watch_samples=n)


def test_quality_snapshot_survives_a_restart(data_dirs, monkeypatch):
    """Nach einem Neustart (leerer In-Memory-Cache) darf die Watch-CSV nicht
    erneut geparst werden — sonst kostet der erste Seitenaufruf ~70 s."""
    from src.server import quality as q
    from src.server import timelines as tl

    row = _fixture(data_dirs)
    q._facts_cache.clear()
    first = q._session_quality(row)

    calls = []
    real = tl._load_watch_timeline

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(tl, "_load_watch_timeline", counting)
    monkeypatch.setattr(q, "_load_watch_timeline", counting)

    q._facts_cache.clear()  # Serverneustart
    second = q._session_quality(row)

    assert not calls, "nach dem Neustart darf die CSV nicht neu geparst werden"
    assert second == first


def test_quality_cache_invalidates_when_the_csv_grows(data_dirs, monkeypatch):
    """Wächst die Watch-CSV, muss neu gerechnet werden — sonst zeigt das
    Dashboard veraltete Sample-Zahlen."""
    from src.server import quality as q
    from src.server import timelines as tl

    row = _fixture(data_dirs, n=400)
    q._facts_cache.clear()
    q._session_quality(row)

    calls = []
    real = tl._load_watch_timeline

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(tl, "_load_watch_timeline", counting)
    monkeypatch.setattr(q, "_load_watch_timeline", counting)

    row = _fixture(data_dirs, n=500)  # CSV neu geschrieben
    q._facts_cache.clear()
    q._session_quality(row)

    assert calls, "geänderte CSV muss den Disk-Cache invalidieren"
