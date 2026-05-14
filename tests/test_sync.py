"""Tests for the pure helpers in src/server/sync.py.

Covers the human-readable diagnostic mapper and the watch-peak detector
that feeds the legacy tap-matching path.
"""

from src.server.sync import _sync_diagnostic, _watch_peaks


def test_sync_diagnostic_high_confidence_reports_aligned():
    """A high-confidence variance-minimization result must produce the
    'aligned' diagnostic so the UI shows green and reports cite δ + σ."""
    result = {
        "method": "stroke_variance_minimization",
        "confidence": "high",
        "delta_ms": -1234.5,
        "sigma_minimal_variance": -5.27,
        "usable": True,
    }
    diag = _sync_diagnostic(result)
    assert diag["status"] == "aligned"
    assert "-1234" in diag["message"] or "-1235" in diag["message"]
    assert "-5.27" in diag["message"]


def test_sync_diagnostic_low_confidence_warns_about_sample_level_merge():
    """Borderline σ → 'weak_signal'. Must still surface δ but warn that
    sample-level merge is unreliable (this is the CLAUDE.md σ≤-3 caveat)."""
    result = {
        "method": "stroke_variance_minimization",
        "confidence": "low",
        "delta_ms": -800.0,
        "sigma_minimal_variance": -2.3,
        "usable": True,
    }
    diag = _sync_diagnostic(result)
    assert diag["status"] == "weak_signal"
    assert diag["label"] == "weak signal"


def test_sync_diagnostic_none_confidence_explains_failure():
    """No alignment found — diagnostic must say so without claiming usability."""
    result = {
        "method": "stroke_variance_minimization",
        "confidence": "none",
        "sigma_minimal_variance": -0.1,
        "reason": "Variance curve flat.",
    }
    diag = _sync_diagnostic(result)
    assert diag["status"] == "no_alignment"
    assert "flat" in diag["message"].lower()


def test_watch_peaks_returns_empty_below_minimum_sample_count():
    """Under 5 candidate rows means no statistics — _watch_peaks must
    bail rather than fabricate peaks from noise."""
    rows = [
        {"source_ts": i * 100, "motion_mag": 1.0}
        for i in range(4)
    ]
    assert _watch_peaks(rows) == []


def test_watch_peaks_detects_only_outliers_above_threshold():
    """Sparse high-magnitude rows surrounded by quiet noise must be picked
    up; quiet baseline rows must not. Enforces _PEAK_MIN_SEPARATION_MS too:
    two clustered peaks within 250 ms collapse to one (keep stronger)."""
    rows = []
    # 20 quiet samples (mag ≈ 0.01)
    for i in range(20):
        rows.append({"source_ts": i * 50, "motion_mag": 0.01})
    # One strong peak, well separated.
    rows.append({"source_ts": 2_000, "motion_mag": 5.0})
    # Two clustered peaks within 250 ms — must collapse to the stronger one.
    rows.append({"source_ts": 3_000, "motion_mag": 3.0})
    rows.append({"source_ts": 3_100, "motion_mag": 7.0})

    peaks = _watch_peaks(rows)
    peak_ts = sorted(p["source_ts"] for p in peaks)
    assert 2_000 in peak_ts
    # Cluster collapsed: the stronger (mag 7.0 at ts 3_100) wins; ts 3_000 gone.
    assert 3_100 in peak_ts
    assert 3_000 not in peak_ts
    assert len(peaks) == 2
