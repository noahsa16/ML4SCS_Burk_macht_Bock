"""Server-Performance-Invarianten: was den Aufnahme-Pfad blockieren würde."""
def test_heavy_session_endpoints_run_off_the_event_loop():
    """Regression 2026-08-08: diese Handler rechnen synchron pandas/numpy über
    60–100-MB-CSVs (Alignment-Grid-Suche pro Session). Als `async def` ohne
    `await` führt FastAPI sie DIREKT auf dem Event-Loop aus — solange sie
    laufen, wird kein `POST /watch` angenommen und kein WS-Tick gesendet.
    Als gewöhnliche `def` wandern sie in den Threadpool.

    Diese Assertion bricht, sobald jemand `async def` zurückschreibt.
    """
    import inspect

    from src.server.routes import sessions

    heavy = (
        sessions.get_session_quality,
        sessions.get_session_validation,
        sessions.get_session_alignment,
        sessions.get_session_report,
    )
    offenders = [f.__name__ for f in heavy if inspect.iscoroutinefunction(f)]
    assert not offenders, (
        f"CPU-schwere Handler dürfen nicht `async def` sein: {offenders}"
    )

