"""Tests fuer den Augmentation-A/B-Treiber (scripts/ml/augment_ab.py)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "ml" / "augment_ab.py"
_spec = importlib.util.spec_from_file_location("augment_ab", _SCRIPT)
augment_ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(augment_ab)


def _folds(held_out, acc, auc):
    return pd.DataFrame({"held_out": held_out, "accuracy": acc, "roc_auc": auc})


def test_seed_average_means_over_seeds():
    s1 = _folds(["P1", "P2"], [0.80, 0.90], [0.85, 0.95])
    s2 = _folds(["P1", "P2"], [0.90, 0.70], [0.95, 0.85])
    avg = augment_ab._seed_average([s1, s2])
    assert list(avg["held_out"]) == ["P1", "P2"]
    assert avg.loc[avg.held_out == "P1", "accuracy"].iloc[0] == pytest.approx(0.85)
    assert avg.loc[avg.held_out == "P2", "accuracy"].iloc[0] == pytest.approx(0.80)


def test_paired_aligns_on_held_out_and_signs_aug_minus_base():
    aug = _folds(["P1", "P2", "P3"], [0.91, 0.92, 0.93], [0.96, 0.97, 0.98])
    base = _folds(["P1", "P2", "P3"], [0.90, 0.90, 0.90], [0.95, 0.95, 0.95])
    res = augment_ab._paired(aug, base, "accuracy")
    assert res["n"] == 3
    assert res["mean_diff"] > 0          # aug besser
    assert res["metric"] == "accuracy"


def test_paired_uses_only_common_folds():
    aug = _folds(["P1", "P2", "PX"], [0.91, 0.92, 0.50], [0.9, 0.9, 0.9])
    base = _folds(["P1", "P2", "PY"], [0.90, 0.90, 0.99], [0.9, 0.9, 0.9])
    res = augment_ab._paired(aug, base, "accuracy")
    assert res["n"] == 2                 # nur P1+P2 gemeinsam
