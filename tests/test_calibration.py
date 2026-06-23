"""Kalibrierungs-Primitive (`src/evaluation/calibration.py`).

Reliability-Kurve + Expected Calibration Error — die geteilte, getestete
Mathematik hinter dem Reliability-Diagramm und der Decision-Scale-Auswertung.
Letzter Bin ist rechts-inklusiv (sonst fällt proba == 1.0 durch); leere
Eingabe → ECE = nan.
"""
from __future__ import annotations

import numpy as np

from src.evaluation.calibration import (
    expected_calibration_error,
    reliability_curve,
)


def test_ece_zero_when_predictions_match_frequencies():
    # Bin 0.5-0.6: mean_pred 0.5, frac_pos 0.5 -> perfekt kalibriert.
    y = np.array([1, 0])
    p = np.array([0.5, 0.5])
    assert expected_calibration_error(y, p, n_bins=10) == 0.0


def test_ece_equals_gap_when_overconfident():
    # Modell sagt 0.9, real nur 50 % -> ECE = |0.5 - 0.9| = 0.4.
    y = np.array([1, 0])
    p = np.array([0.9, 0.9])
    assert np.isclose(expected_calibration_error(y, p, n_bins=10), 0.4)


def test_ece_weights_bins_by_count():
    # Zwei volle Bins, je perfekt-extrem: |0-0.1| und |1-0.9|, gleich gewichtet.
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.1, 0.9, 0.9])
    # (2/4)*0.1 + (2/4)*0.1 = 0.1
    assert np.isclose(expected_calibration_error(y, p, n_bins=10), 0.1)


def test_ece_empty_input_is_nan():
    assert np.isnan(expected_calibration_error(np.array([]), np.array([]), n_bins=10))


def test_reliability_curve_bins_means_and_counts():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.1, 0.9, 0.9])
    mean_p, frac_pos, counts = reliability_curve(y, p, n_bins=10)
    assert counts[1] == 2 and counts[9] == 2 and counts.sum() == 4
    assert np.isclose(mean_p[1], 0.1) and np.isclose(frac_pos[1], 0.0)
    assert np.isclose(mean_p[9], 0.9) and np.isclose(frac_pos[9], 1.0)
    assert np.isnan(mean_p[0])  # leerer Bin -> nan


def test_reliability_curve_last_bin_is_right_inclusive():
    # proba == 1.0 muss in den letzten Bin fallen, nicht durchrutschen.
    mean_p, frac_pos, counts = reliability_curve(
        np.array([1]), np.array([1.0]), n_bins=10
    )
    assert counts[9] == 1
    assert np.isclose(mean_p[9], 1.0)
