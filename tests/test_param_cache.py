"""Parametrisierter Window-Feature-Cache.

Feature-Fenster (window/stride) und Label-Gap sind Feature-Build-Parameter.
Nicht-Default-Kombis müssen kollisionsfrei und getrennt vom kanonischen
windows/{profile}/-Cache abgelegt werden (User-Anforderung: "nicht
gegenseitig überschreiben, sauber gespeichert").
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features import param_cache as pc


def test_is_default_params():
    assert pc.is_default_params(1.0, 0.5, 2500.0) is True
    assert pc.is_default_params(5.0, 2.5, 2500.0) is False
    assert pc.is_default_params(1.0, 0.5, 1000.0) is False


def test_param_paths_distinct_per_combo_and_off_canonical():
    p1 = pc.param_windows_path("S001", "legacy", 1.0, 0.5, 2500.0)
    p2 = pc.param_windows_path("S001", "legacy", 5.0, 2.5, 2500.0)
    p3 = pc.param_windows_path("S001", "legacy", 1.0, 0.5, 1000.0)
    # Jede Kombi ihr eigener Pfad -> kein gegenseitiges Überschreiben.
    assert len({str(p1), str(p2), str(p3)}) == 3
    for p in (p1, p2, p3):
        assert "windows_param" in str(p)          # nicht der kanonische windows/-Cache
        assert p.name == "S001_windows.csv"


def test_ensure_reuses_existing_without_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "PARAM_DIR", tmp_path / "windows_param")
    monkeypatch.setattr(pc, "DATA_PROC", tmp_path)  # kein merged -> Build würde scheitern
    out = pc.param_windows_dir("legacy", 5.0, 2.5, 2500.0) / "S900_windows.csv"
    out.parent.mkdir(parents=True)
    out.write_text("sentinel\n")
    got = pc.ensure_param_windows("S900", "legacy", 5.0, 2.5, 2500.0)
    assert got.read_text() == "sentinel\n"          # wiederverwendet, nicht neu gebaut


def test_ensure_builds_from_merged(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "PARAM_DIR", tmp_path / "windows_param")
    monkeypatch.setattr(pc, "DATA_PROC", tmp_path)
    n = 500
    ts = np.arange(n) * 20.0  # ms, 50 Hz
    merged = pd.DataFrame({
        "ts": ts, "local_ts_ms": ts,
        "ax": np.sin(ts / 100), "ay": np.cos(ts / 120), "az": np.sin(ts / 90),
        "rx": np.cos(ts / 80), "ry": np.sin(ts / 70), "rz": np.cos(ts / 60),
        "label_writing": (np.arange(n) // 50) % 2,  # alternierende Blöcke
    })
    merged.to_csv(tmp_path / "S900_merged.csv", index=False)
    out = pc.ensure_param_windows("S900", "legacy", 5.0, 2.5, 2500.0)
    assert out.exists()
    df = pd.read_csv(out)
    assert "label" in df.columns and "session_id" in df.columns
    assert (df["session_id"] == "S900").all()
    assert len(df) > 0
