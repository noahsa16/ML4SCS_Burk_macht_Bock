"""Tests fuer die Daten-Vollstaendigkeits-Logik (scripts/ops/ensure_views.py).

Getestet wird die reine ``plan``/``targets_for``-Logik (welches Subject welche
Profile braucht); die Subprozess-Build-Kette ist manueller Smoke.
"""
import importlib.util
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).parents[1] / "scripts" / "ops" / "ensure_views.py"
_spec = importlib.util.spec_from_file_location("ensure_views", _SCRIPT)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def _sessions(rows):
    return pd.DataFrame(rows, columns=["session_id", "person_id", "study_mode", "watch_profile"])


def test_targets_for_per_profile():
    assert ev.targets_for("50hz") == ["50hz"]
    assert ev.targets_for("100hz_grav") == ["100hz_grav", "50hz"]
    assert ev.targets_for("100hz") == ["50hz"]
    assert ev.targets_for("unknown") == []


def test_plan_modern_needs_both_profiles():
    s = _sessions([("S1", "P1", "study", "100hz_grav")])
    # gemergt, aber nur das native 100hz_grav-Window existiert -> 50hz fehlt
    miss = ev.plan(s, lambda sid: True, lambda sid, p: p == "100hz_grav")
    assert miss == {"S1": ["50hz"]}


def test_plan_skips_test_sessions():
    s = _sessions([("S1", "P1", "test", "100hz_grav")])
    assert ev.plan(s, lambda sid: True, lambda sid, p: False) == {}


def test_plan_skips_unmerged_pen_less_sessions():
    # free-Aufnahme ohne native merged (kein Pen) -> nicht trainable -> skip
    s = _sessions([("S2", "P2", "free", "100hz_grav")])
    assert ev.plan(s, lambda sid: False, lambda sid, p: False) == {}


def test_plan_modern_missing_both():
    s = _sessions([("S3", "P3", "study", "100hz_grav")])
    miss = ev.plan(s, lambda sid: True, lambda sid, p: False)
    assert miss == {"S3": ["100hz_grav", "50hz"]}


def test_plan_complete_returns_empty():
    s = _sessions([("S4", "P4", "study", "50hz")])
    assert ev.plan(s, lambda sid: True, lambda sid, p: True) == {}


def test_plan_legacy_needs_only_50hz():
    s = _sessions([("S5", "P5", "study", "50hz")])
    assert ev.plan(s, lambda sid: True, lambda sid, p: False) == {"S5": ["50hz"]}
