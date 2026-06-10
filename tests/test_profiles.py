"""watch_profile-Taxonomie: Ordner-Mapping, native Auflösung, Detection.

Background: Window-CSVs leben profil-sortiert unter
data/processed/windows/{50hz,100hz,100hz_grav}/. Eine Modern-Session
existiert legitim in zwei Profilen (nativ 100hz_grav + Legacy-View
50hz) — die Auflösung muss kollisionsfrei und vorhersagbar sein.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import profiles


@pytest.fixture
def proc(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "DATA_PROC", tmp_path)
    monkeypatch.setattr(profiles, "WINDOWS_DIR", tmp_path / "windows")
    return tmp_path


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("label\n0\n")
    return path


def test_windows_path_maps_profile_to_folder(proc):
    p = profiles.windows_path("S038", "100hz_grav")
    assert p == proc / "windows" / "100hz_grav" / "S038_windows.csv"


def test_windows_path_rejects_unknown_profile(proc):
    with pytest.raises(ValueError, match="bogus"):
        profiles.windows_path("S038", "bogus")


def test_find_windows_explicit_profile(proc):
    _touch(proc / "windows" / "50hz" / "S038_windows.csv")
    _touch(proc / "windows" / "100hz_grav" / "S038_windows.csv")

    found = profiles.find_windows("S038", "50hz")

    assert found == proc / "windows" / "50hz" / "S038_windows.csv"


def test_find_windows_native_prefers_highest_fidelity(proc):
    # S038 existiert nativ (100hz_grav) UND als Legacy-View (50hz) —
    # native Auflösung muss die View ignorieren.
    _touch(proc / "windows" / "50hz" / "S038_windows.csv")
    native = _touch(proc / "windows" / "100hz_grav" / "S038_windows.csv")

    assert profiles.find_windows("S038") == native


def test_find_windows_native_falls_back_to_flat_legacy_path(proc):
    flat = _touch(proc / "S007_windows.csv")

    with pytest.warns(UserWarning, match="flach"):
        found = profiles.find_windows("S007")

    assert found == flat


def test_find_windows_explicit_profile_does_not_fall_back_to_flat(proc):
    _touch(proc / "S007_windows.csv")

    assert profiles.find_windows("S007", "50hz") is None


def test_find_windows_missing_returns_none(proc):
    assert profiles.find_windows("S999") is None


def _merged_df(fs_hz: float, with_gravity: bool, n: int = 200) -> pd.DataFrame:
    df = pd.DataFrame({
        "ts": np.arange(n) / fs_hz,
        "ax": np.zeros(n), "ay": np.zeros(n), "az": np.zeros(n),
        "rx": np.zeros(n), "ry": np.zeros(n), "rz": np.zeros(n),
    })
    if with_gravity:
        df["gx"] = 0.0
        df["gy"] = 0.0
        df["gz"] = -1.0
    return df


def test_detect_profile_50hz_no_gravity():
    assert profiles.detect_profile(_merged_df(50.0, False)) == "50hz"


def test_detect_profile_100hz_with_gravity():
    assert profiles.detect_profile(_merged_df(100.0, True)) == "100hz_grav"


def test_detect_profile_gravity_columns_all_nan_is_not_grav():
    df = _merged_df(100.0, True)
    df[["gx", "gy", "gz"]] = np.nan

    assert profiles.detect_profile(df) == "100hz"


def test_profile_for_maps_rate_and_gravity():
    assert profiles.profile_for(49.7, False) == "50hz"
    assert profiles.profile_for(99.2, False) == "100hz"
    assert profiles.profile_for(100.4, True) == "100hz_grav"


def test_profile_for_rejects_ambiguous_rate():
    with pytest.raises(ValueError, match="75"):
        profiles.profile_for(75.0, False)


def test_detect_profile_rejects_ambiguous_rate():
    with pytest.raises(ValueError, match="75"):
        profiles.detect_profile(_merged_df(75.0, False))


def test_detect_profile_handles_legacy_ms_units_and_reversed_batches():
    # Reale Legacy-merged-CSVs: ts in MILLISEKUNDEN und innerhalb jedes
    # 10er-Batches rückwärts sortiert (frühe Watch-App-Batch-Reihenfolge;
    # median(diff) wäre −20 ms). Detection muss trotzdem 50hz liefern.
    n_batches, batch, dt_ms = 30, 10, 20.0
    ts = np.concatenate([
        (np.arange(batch)[::-1] + i * batch) * dt_ms for i in range(n_batches)
    ])
    df = pd.DataFrame({"ts": ts, "ax": np.zeros(len(ts))})

    assert profiles.detect_profile(df) == "50hz"


def test_migrate_moves_flat_windows_by_merged_profile(proc):
    # Profil einer flachen windows.csv ist nur über die merged-Schwester
    # bestimmbar (Windows-Features tragen keine Sample-Rate).
    _merged_df(50.0, False).to_csv(proc / "S007_merged.csv", index=False)
    _touch(proc / "S007_windows.csv")
    _merged_df(100.0, True).to_csv(proc / "S038_merged.csv", index=False)
    _touch(proc / "S038_windows.csv")

    moved = profiles.migrate_flat_windows()

    assert (proc / "windows" / "50hz" / "S007_windows.csv").exists()
    assert (proc / "windows" / "100hz_grav" / "S038_windows.csv").exists()
    assert not (proc / "S007_windows.csv").exists()
    assert not (proc / "S038_windows.csv").exists()
    assert len(moved) == 2


def test_migrate_skips_windows_without_merged_sibling(proc):
    flat = _touch(proc / "S099_windows.csv")

    with pytest.warns(UserWarning, match="S099"):
        moved = profiles.migrate_flat_windows()

    assert flat.exists()
    assert moved == []
