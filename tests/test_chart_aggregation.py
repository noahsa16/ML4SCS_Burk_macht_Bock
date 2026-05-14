"""Smoke test for the 5 Hz chart aggregator.

Feeds synthetic per-axis magnitudes into state, runs the aggregator once,
asserts the resulting chart buffer entry has the right mean and the
sample windows are cleared.
"""
import pytest

from src.server import broadcast
from src.server.state import SessionState


def test_chart_aggregator_means_and_clears():
    state = SessionState()
    state.active = True
    state.chart_window_acc_mags = [0.5, 1.0, 1.5]   # mean = 1.0
    state.chart_window_gyro_mags = [0.2, 0.4]       # mean = 0.3

    broadcast._chart_aggregator_tick(state, pen_writing=False)

    assert len(state.chart_buffer) == 1
    entry = state.chart_buffer[0]
    assert entry["acc_mag"] == 1.0
    assert entry["gyro_mag"] == 0.3
    assert entry["mag"] == 1.0           # backward-compat key
    assert entry["pen_writing"] is False
    assert state.chart_window_acc_mags == []
    assert state.chart_window_gyro_mags == []


def test_chart_aggregator_skips_when_inactive():
    state = SessionState()
    state.active = False
    state.chart_window_acc_mags = [1.0]
    state.chart_window_gyro_mags = [1.0]

    broadcast._chart_aggregator_tick(state, pen_writing=False)

    assert state.chart_buffer == []
    assert state.chart_window_acc_mags == []
    assert state.chart_window_gyro_mags == []


def test_chart_aggregator_trims_to_100():
    state = SessionState()
    state.active = True
    state.chart_buffer = [{"t": i} for i in range(100)]
    state.chart_window_acc_mags = [2.0]
    state.chart_window_gyro_mags = [3.0]

    broadcast._chart_aggregator_tick(state, pen_writing=True)

    assert len(state.chart_buffer) == 100
    assert state.chart_buffer[-1]["acc_mag"] == 2.0
    assert state.chart_buffer[-1]["pen_writing"] is True
    assert state.chart_buffer[0]["t"] == 1


def test_chart_aggregator_active_with_empty_windows_appends_zero_entry():
    """When active but no samples arrived during the bucket, still emit
    a chart point (with zero magnitudes) so the chart stays time-continuous.
    Without this, a quiet 200 ms gap would leave a hole in the live chart."""
    state = SessionState()
    state.active = True
    state.chart_window_acc_mags = []
    state.chart_window_gyro_mags = []

    broadcast._chart_aggregator_tick(state, pen_writing=False)

    assert len(state.chart_buffer) == 1
    entry = state.chart_buffer[0]
    assert entry["acc_mag"] == 0.0
    assert entry["gyro_mag"] == 0.0
    assert entry["pen_writing"] is False
