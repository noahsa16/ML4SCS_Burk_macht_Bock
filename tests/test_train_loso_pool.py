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


def test_no_pool_suffix_promotes_to_canonical_path():
    # Bewusster Override des Guards: der Headline-Lauf (legacy N=14)
    # darf die kanonischen Artefakte schreiben — explizit, nie silent.
    from pathlib import Path

    from src.training.train_loso import _pool_suffixed_path

    out = _pool_suffixed_path(Path("models/rf_all.joblib"), "legacy", pool_suffix=False)

    assert out.name == "rf_all.joblib"


def test_no_pool_suffix_keeps_nogravity_guard():
    # Der Ablation-Arm darf NIE kanonisch werden, auch nicht mit
    # --no-pool-suffix.
    from pathlib import Path

    from src.training.train_loso import _pool_suffixed_path

    out = _pool_suffixed_path(
        Path("models/rf_all.joblib"), "legacy", drop_gravity=True, pool_suffix=False
    )

    assert out.name == "rf_all_nogravity.joblib"


def test_profile_for_pool_mapping():
    from src.training.train_loso import _profile_for_pool

    assert _profile_for_pool("legacy") == "50hz"
    assert _profile_for_pool("modern") == "100hz_grav"
    assert _profile_for_pool("auto") is None


def test_load_windows_explicit_profile_reads_view(tmp_path, monkeypatch):
    # pool=legacy lädt die 50hz-View einer Modern-Session — der
    # N=14-Mechanismus: Views joinen den Legacy-Pool automatisch.
    from src import profiles
    from src.training import train_loso as T

    monkeypatch.setattr(profiles, "DATA_PROC", tmp_path)
    monkeypatch.setattr(profiles, "WINDOWS_DIR", tmp_path / "windows")
    target = tmp_path / "windows" / "50hz" / "S900_windows.csv"
    target.parent.mkdir(parents=True)
    pd.DataFrame({"ax_mean": [1.0], "label": [0], "t_center_ms": [500.0]}).to_csv(
        target, index=False
    )

    df = T._load_windows("S900", profile="50hz")

    assert df["session_id"].iloc[0] == "S900"
    assert "ax_mean" in df.columns


def test_load_windows_explicit_profile_missing_raises(tmp_path, monkeypatch):
    # Explizit angefordertes Profil ohne Datei darf NICHT stillschweigend
    # die native Variante on-the-fly bauen (wäre falsches Profil).
    from src import profiles
    from src.training import train_loso as T

    monkeypatch.setattr(profiles, "DATA_PROC", tmp_path)
    monkeypatch.setattr(profiles, "WINDOWS_DIR", tmp_path / "windows")

    import pytest

    with pytest.raises(FileNotFoundError, match="50hz"):
        T._load_windows("S901", profile="50hz")


def test_invalid_pool_raises():
    df = _legacy_session("S001")

    try:
        _filter_pool(df, "bogus")
    except ValueError as e:
        assert "bogus" in str(e)
    else:
        raise AssertionError("ValueError expected")
