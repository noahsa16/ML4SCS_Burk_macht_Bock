"""Falsifikations-Diagnostik für den Varianz-Alignment-Bias-Verdacht.

Reviewer-Verdacht #3: das Varianz-minimierende Alignment mappe Schreib-Labels
auf RUHIGE Handgelenk-Phasen → Schreiben hätte niedrige Varianz/Jerk. Diese
Diagnostik vergleicht die Klassen kinematisch; ist Schreiben die *dynamischere*
Klasse (ratio > 1 bei Jerk-Features), ist der Verdacht widerlegt.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.evaluation.label_diagnostics import class_kinematics_summary


def test_summary_computes_per_class_means_and_ratio():
    df = pd.DataFrame({"label": [1, 1, 0, 0],
                       "jerk": [2.0, 2.0, 1.0, 1.0],
                       "flat": [5.0, 5.0, 5.0, 5.0]})
    s = class_kinematics_summary(df, ["jerk", "flat"]).set_index("feature")
    assert s.loc["jerk", "writing_mean"] == pytest.approx(2.0)
    assert s.loc["jerk", "idle_mean"] == pytest.approx(1.0)
    assert s.loc["jerk", "ratio"] == pytest.approx(2.0)
    assert s.loc["flat", "ratio"] == pytest.approx(1.0)


def test_missing_feature_columns_are_ignored():
    df = pd.DataFrame({"label": [1, 0], "a": [1.0, 2.0]})
    s = class_kinematics_summary(df, ["a", "does_not_exist"])
    assert set(s["feature"]) == {"a"}


def test_requires_both_classes():
    df = pd.DataFrame({"label": [1, 1], "a": [1.0, 2.0]})
    with pytest.raises(ValueError):
        class_kinematics_summary(df, ["a"])
