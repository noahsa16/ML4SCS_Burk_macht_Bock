"""Tests fuer den testbaren Kern von ensemble_committee (committee_table).

``scripts`` ist kein Paket -> Modul per importlib ueber den Pfad laden.
Kein IO/Report — nur die reine Kombinatorik-Logik.
"""
import importlib.util
from pathlib import Path

import pandas as pd

_S = Path(__file__).parents[1] / "scripts" / "ml" / "ensemble_committee.py"
_spec = importlib.util.spec_from_file_location("ensemble_committee", _S)
com = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(com)


def _aligned():
    """3 Personen x 4 Fenster (y=[0,1,0,1]), 3 distinkte Arme, per-Person leicht
    versetzt (keine degenerierten all-gleich-Folds fuer den gepaarten Test)."""
    base = {"a": [0.2, 0.7, 0.3, 0.8], "b": [0.15, 0.85, 0.45, 0.6],
            "c": [0.35, 0.55, 0.25, 0.72]}
    off = {"P1": 0.0, "P2": 0.06, "P3": -0.04}
    d = {"person_id": [], "y": [], "a_proba": [], "b_proba": [], "c_proba": []}
    for person in ["P1", "P2", "P3"]:
        for i, y in enumerate([0, 1, 0, 1]):
            d["person_id"].append(person)
            d["y"].append(y)
            for m in ("a", "b", "c"):
                d[f"{m}_proba"].append(min(0.99, max(0.01, base[m][i] + off[person])))
    return pd.DataFrame(d)


def test_committee_table_all_combos_and_columns():
    # 3 Mitglieder -> C(3,2)+C(3,3) = 4 Kombinationen
    tbl = com.committee_table(_aligned(), ["a", "b", "c"])
    assert set(tbl["members"]) == {"a+b", "a+c", "b+c", "a+b+c"}
    assert {"members", "n", "acc", "auc", "r_resid", "best_solo",
            "delta_acc", "p_acc", "significant"} <= set(tbl.columns)
    # nach acc absteigend sortiert
    assert list(tbl["acc"]) == sorted(tbl["acc"], reverse=True)


def test_committee_table_two_members_single_combo():
    tbl = com.committee_table(_aligned(), ["a", "b"])
    assert list(tbl["members"]) == ["a+b"]
    assert tbl["n"].iloc[0] == 2
    assert -1.0 <= tbl["r_resid"].iloc[0] <= 1.0
    # best_solo ist eines der beiden Mitglieder
    assert tbl["best_solo"].iloc[0] in {"a", "b"}
