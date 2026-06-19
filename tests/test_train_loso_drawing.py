"""Drawing-Window-Exclusion in train_loso.

Background: Die `drawing`-Task (Zeichnen/Skizzieren) wurde 2026-06-18 aus
dem v2-Protokoll entfernt — Nicht-Handschrift-Stiftbewegung ist nicht das
Erkennungsziel. Bereits aufgenommene Sessions (S042/S043) tragen die Blöcke
aber weiterhin in ihren Marker-CSVs, und ihre Fenster würden sonst als
writing-Klasse ins Training gehen. `_exclude_drawing_windows` filtert sie
marker-getrieben über `t_center_ms` heraus.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.training.train_loso import _exclude_drawing_windows


def _windows(sid: str = "S900", n: int = 10) -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": [sid] * n,
        "ax_mean": np.arange(n, dtype=float),
        "label": np.ones(n, dtype=int),
        "t_center_ms": np.arange(n, dtype=float) * 500,  # 0, 500, ..., 4500
    })


def _timeline(task_id: str, start_ms: float, end_ms: float) -> pd.DataFrame:
    return pd.DataFrame({
        "task_index": [1],
        "task_id": [task_id],
        "task_name": ["Block"],
        "task_category": ["writing"],
        "start_ms": [start_ms],
        "end_ms": [end_ms],
    })


def test_drops_windows_inside_drawing_block():
    df = _windows()
    out = _exclude_drawing_windows(
        df, timeline_loader=lambda sid: _timeline("drawing", 1000.0, 3000.0)
    )
    # [1000, 3000): drops 1000/1500/2000/2500; 3000 stays (half-open).
    assert list(out["t_center_ms"]) == [0, 500, 3000, 3500, 4000, 4500]
    assert len(out) == 6


def test_keeps_non_drawing_task_blocks():
    df = _windows()
    out = _exclude_drawing_windows(
        df, timeline_loader=lambda sid: _timeline("math", 1000.0, 3000.0)
    )
    assert len(out) == len(df)


def test_no_markers_keeps_all_windows():
    df = _windows()
    empty = pd.DataFrame(
        columns=["task_index", "task_id", "task_name",
                 "task_category", "start_ms", "end_ms"]
    )
    out = _exclude_drawing_windows(df, timeline_loader=lambda sid: empty)
    assert len(out) == len(df)


def test_only_named_sessions_filtered_others_untouched():
    df = pd.concat([_windows("S900"), _windows("S901")], ignore_index=True)

    def loader(sid: str) -> pd.DataFrame:
        if sid == "S900":
            return _timeline("drawing", 1000.0, 3000.0)
        return _timeline("math", 1000.0, 3000.0)

    out = _exclude_drawing_windows(df, timeline_loader=loader)
    assert (out["session_id"] == "S900").sum() == 6   # 4 drawing windows gone
    assert (out["session_id"] == "S901").sum() == 10  # untouched
