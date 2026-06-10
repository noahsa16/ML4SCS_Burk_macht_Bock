"""Pool-Filter-Tests für train_loso.

Background: Modern-Pool-Sessions haben tilt_x_mean/tilt_change/etc.
Legacy-Pool-Sessions haben nicht. Beim pd.concat über gemischte Pools
würde pandas NaN in den gravity-Spalten erzeugen → RandomForest.fit
crasht auf NaN. _filter_pool() ist die Abwehrlinie.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.gravity import GRAVITY_FEATURE_NAMES
from src.training.train_loso import _filter_pool


def _legacy_session(sid: str, n: int = 20) -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": [sid] * n,
        "ax_mean": np.zeros(n),
        "label": np.zeros(n, dtype=int),
        "t_center_ms": np.arange(n, dtype=float) * 500,
    })


def _modern_session(sid: str, n: int = 20) -> pd.DataFrame:
    df = _legacy_session(sid, n)
    for name in GRAVITY_FEATURE_NAMES:
        df[name] = 1.0
    return df


def _concat_pools(*dfs: pd.DataFrame) -> pd.DataFrame:
    # Simulates train_loso.py's concat — pandas pads with NaN where columns
    # don't match.
    return pd.concat(dfs, ignore_index=True)


def test_auto_with_all_legacy_keeps_everything():
    df = _concat_pools(_legacy_session("S001"), _legacy_session("S002"))

    out = _filter_pool(df, "auto")

    assert set(out["session_id"]) == {"S001", "S002"}
    for name in GRAVITY_FEATURE_NAMES:
        assert name not in out.columns


def test_auto_with_all_modern_keeps_gravity():
    df = _concat_pools(_modern_session("S001"), _modern_session("S002"))

    out = _filter_pool(df, "auto")

    assert set(out["session_id"]) == {"S001", "S002"}
    for name in GRAVITY_FEATURE_NAMES:
        assert name in out.columns
    # And no NaNs introduced
    assert out[GRAVITY_FEATURE_NAMES].notna().all().all()


def test_auto_with_mixed_drops_gravity_keeps_all_sessions():
    df = _concat_pools(
        _legacy_session("S001"),
        _modern_session("S002"),
    )

    out = _filter_pool(df, "auto")

    assert set(out["session_id"]) == {"S001", "S002"}
    for name in GRAVITY_FEATURE_NAMES:
        assert name not in out.columns


def test_legacy_filters_to_legacy_only_and_drops_gravity():
    df = _concat_pools(
        _legacy_session("S001"),
        _modern_session("S002"),
        _modern_session("S003"),
    )

    out = _filter_pool(df, "legacy")

    assert set(out["session_id"]) == {"S001"}
    for name in GRAVITY_FEATURE_NAMES:
        assert name not in out.columns


def test_modern_filters_to_modern_only_and_keeps_gravity():
    df = _concat_pools(
        _legacy_session("S001"),
        _modern_session("S002"),
        _modern_session("S003"),
    )

    out = _filter_pool(df, "modern")

    assert set(out["session_id"]) == {"S002", "S003"}
    for name in GRAVITY_FEATURE_NAMES:
        assert name in out.columns
    assert out[GRAVITY_FEATURE_NAMES].notna().all().all()


def test_modern_with_drop_gravity_keeps_sessions_drops_columns():
    # Ablation arm: same modern sessions/folds, gravity features removed.
    df = _concat_pools(
        _legacy_session("S001"),
        _modern_session("S002"),
        _modern_session("S003"),
    )

    out = _filter_pool(df, "modern", drop_gravity=True)

    assert set(out["session_id"]) == {"S002", "S003"}
    for name in GRAVITY_FEATURE_NAMES:
        assert name not in out.columns


def test_drop_gravity_suffixes_save_paths():
    from pathlib import Path

    from src.training.train_loso import _pool_suffixed_path

    out = _pool_suffixed_path(Path("models/rf_all.joblib"), "modern", drop_gravity=True)

    assert out.name == "rf_all_modern_nogravity.joblib"


def test_invalid_pool_raises():
    df = _legacy_session("S001")

    try:
        _filter_pool(df, "bogus")
    except ValueError as e:
        assert "bogus" in str(e)
    else:
        raise AssertionError("ValueError expected")
