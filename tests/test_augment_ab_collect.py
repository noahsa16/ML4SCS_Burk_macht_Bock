"""Tests fuer den parallelen Augment-A/B-Collector (scripts/ml/augment_ab_collect.py)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).parents[1] / "scripts" / "ml" / "augment_ab_collect.py"
_spec = importlib.util.spec_from_file_location("augment_ab_collect", _SCRIPT)
collect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect)


def _cv(held, acc, auc):
    return pd.DataFrame({"held_out": held, "accuracy": acc, "roc_auc": auc})


def _write_run(root: Path, name: str, df: pd.DataFrame):
    d = root / f"cv-{name}"
    d.mkdir(parents=True)
    df.to_csv(d / "deep_loso_modern.csv", index=False)


def test_load_runs_splits_by_suffix(tmp_path):
    _write_run(tmp_path, "s42-noaug", _cv(["P1", "P2"], [0.80, 0.90], [0.85, 0.95]))
    _write_run(tmp_path, "s42-aug", _cv(["P1", "P2"], [0.91, 0.92], [0.96, 0.97]))
    base, aug = collect.load_runs(str(tmp_path))
    assert len(base) == 1 and len(aug) == 1
    assert set(aug[0]["accuracy"]) == {0.91, 0.92}


def test_seed_average_means_over_seeds():
    s1 = _cv(["P1", "P2"], [0.80, 0.90], [0.85, 0.95])
    s2 = _cv(["P1", "P2"], [0.90, 0.70], [0.95, 0.85])
    avg = collect._seed_average([s1, s2])
    assert list(avg["held_out"]) == ["P1", "P2"]
    assert avg.loc[avg.held_out == "P1", "accuracy"].iloc[0] == pytest.approx(0.85)
    assert avg.loc[avg.held_out == "P2", "accuracy"].iloc[0] == pytest.approx(0.80)


def test_paired_signs_aug_minus_base():
    aug = _cv(["P1", "P2", "P3"], [0.91, 0.92, 0.93], [0.96, 0.97, 0.98])
    base = _cv(["P1", "P2", "P3"], [0.90, 0.90, 0.90], [0.95, 0.95, 0.95])
    res = collect._paired(aug, base, "accuracy")
    assert res["n"] == 3 and res["mean_diff"] > 0 and res["metric"] == "accuracy"


def test_build_report_has_verdict_and_per_fold():
    base_runs = [_cv(["P1", "P2"], [0.80, 0.90], [0.85, 0.95]),
                 _cv(["P1", "P2"], [0.82, 0.88], [0.86, 0.94])]
    aug_runs = [_cv(["P1", "P2"], [0.85, 0.93], [0.90, 0.97]),
                _cv(["P1", "P2"], [0.87, 0.91], [0.91, 0.96])]
    report = collect.build_report(base_runs, aug_runs)
    assert "Claim-Gate" in report
    assert "Gepaarter Wilcoxon" in report
    assert "| P1 |" in report and "| P2 |" in report
    assert "Seed-sigma" in report
