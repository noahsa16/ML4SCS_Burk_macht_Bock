"""Tests fuer die reine Kernlogik von marker_fpr (parse/assign/fpr).

``scripts`` ist kein Paket -> Modul per importlib laden. Kein OOF/Marker-IO hier.
"""
import importlib.util
from pathlib import Path

import pandas as pd

_S = Path(__file__).parents[1] / "scripts" / "ml" / "marker_fpr.py"
_spec = importlib.util.spec_from_file_location("marker_fpr", _S)
mf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mf)


def _markers():
    # zwei Idle-Bloecke: pause [0,1000), keyboard_typing [1000,2000)
    return pd.DataFrame([
        {"timestamp_ms": 0, "event": "task_start", "task_id": "pause",
         "task_index": 1, "task_category": "idle"},
        {"timestamp_ms": 1000, "event": "task_end", "task_id": "pause",
         "task_index": 1, "task_category": "idle"},
        {"timestamp_ms": 1000, "event": "task_start", "task_id": "keyboard_typing",
         "task_index": 2, "task_category": "idle"},
        {"timestamp_ms": 2000, "event": "task_end", "task_id": "keyboard_typing",
         "task_index": 2, "task_category": "idle"},
    ])


def test_parse_task_blocks_pairs_by_index():
    b = mf.parse_task_blocks(_markers())
    assert len(b) == 2
    kb = b[b.task_id == "keyboard_typing"].iloc[0]
    assert kb.start_ms == 1000.0 and kb.end_ms == 2000.0
    assert set(b.task_category) == {"idle"}


def test_assign_task_maps_windows_to_blocks():
    blocks = mf.parse_task_blocks(_markers())
    oof = pd.DataFrame({"session_id": ["S1"] * 4,
                        "t_center_ms": [200.0, 800.0, 1200.0, 5000.0],  # letztes ausserhalb
                        "proba_cal": [0.1, 0.2, 0.9, 0.9]})
    a = mf.assign_task(oof, blocks)
    assert len(a) == 3                                   # 5000ms verworfen
    assert a[a.t_center_ms == 200.0]["task_id"].iloc[0] == "pause"
    assert a[a.t_center_ms == 1200.0]["task_id"].iloc[0] == "keyboard_typing"


def test_fpr_by_task_counts_false_positives():
    blocks = mf.parse_task_blocks(_markers())
    # pause: 2 Fenster, keins >=0.5 -> FPR 0 ; keyboard: 2 Fenster, beide >=0.5 -> FPR 1
    oof = pd.DataFrame({"session_id": ["S1"] * 4,
                        "t_center_ms": [200.0, 800.0, 1200.0, 1500.0],
                        "proba_cal": [0.1, 0.3, 0.9, 0.7]})
    fpr = mf.fpr_by_task(mf.assign_task(oof, blocks))
    kb = fpr[fpr.task_id == "keyboard_typing"].iloc[0]
    pa = fpr[fpr.task_id == "pause"].iloc[0]
    assert kb.fpr == 1.0 and kb.n == 2 and kb.n_fp == 2
    assert pa.fpr == 0.0 and pa.n == 2
    # absteigend sortiert -> keyboard zuerst
    assert fpr.iloc[0]["task_id"] == "keyboard_typing"


def test_fpr_ignores_writing_blocks():
    markers = pd.DataFrame([
        {"timestamp_ms": 0, "event": "task_start", "task_id": "free_writing",
         "task_index": 1, "task_category": "writing"},
        {"timestamp_ms": 1000, "event": "task_end", "task_id": "free_writing",
         "task_index": 1, "task_category": "writing"},
    ])
    blocks = mf.parse_task_blocks(markers)
    oof = pd.DataFrame({"session_id": ["S1"], "t_center_ms": [500.0], "proba_cal": [0.9]})
    fpr = mf.fpr_by_task(mf.assign_task(oof, blocks))
    assert fpr.empty                                     # nur writing -> keine idle-FPR
