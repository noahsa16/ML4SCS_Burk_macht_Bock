"""Classifier-Factory + `model`-Durchreichung in train_loso.

Bis zum Cockpit-Runner-Ausbau trainierte train_loso immer RF; das
`--model`-CLI-Flag wurde geparst, aber nicht an train_loso() übergeben.
Diese Tests fixieren: (a) die Factory baut pro Registry-ID den richtigen
Estimator, (b) der gewählte Model fließt bis in RUN_START + das gespeicherte
model.joblib durch.
"""
import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)

from src.training import train_loso as T
from src.training import events as E


def _toy_windows(sessions, per=60, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for sid, pid in sessions:
        for i in range(per):
            label = i % 2
            rows.append({
                "session_id": sid, "person_id": pid,
                "t_center_ms": i * 500,
                "label": label,
                "f0": rng.normal(label, 0.3), "f1": rng.normal(-label, 0.3),
            })
    return pd.DataFrame(rows)


def _patch(monkeypatch, df):
    monkeypatch.setattr(
        T, "_select_sessions",
        lambda **k: df[["session_id", "person_id"]].drop_duplicates())
    monkeypatch.setattr(
        T, "_load_windows",
        lambda sid, profile=None:
            df[df.session_id == sid].drop(columns=["person_id"]).copy())


def test_make_classifier_maps_ids_to_estimator_types():
    assert isinstance(T._make_classifier("rf", 200, 42), RandomForestClassifier)
    assert isinstance(T._make_classifier("extratrees", 200, 42), ExtraTreesClassifier)
    assert isinstance(T._make_classifier("histgb", 200, 42),
                      HistGradientBoostingClassifier)
    # Lineare/Kernel/MLP-Modelle bekommen einen Scaler vorgeschaltet (Pipeline).
    for mid in ("logreg", "svm_rbf", "mlp"):
        est = T._make_classifier(mid, 200, 42)
        assert hasattr(est, "fit") and hasattr(est, "predict_proba")


def test_make_classifier_unknown_id_raises():
    with pytest.raises((KeyError, ValueError)):
        T._make_classifier("does-not-exist", 200, 42)


def test_make_classifier_returns_fresh_instances():
    a = T._make_classifier("rf", 200, 42)
    b = T._make_classifier("rf", 200, 42)
    assert a is not b


def test_run_start_carries_selected_model(monkeypatch):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    _patch(monkeypatch, df)
    seen = []
    T.train_loso(by="person", include_all=True, zscore_per_session=False,
                 pool="auto", model="extratrees", on_event=seen.append)
    rs = next(e for e in seen if e["type"] == E.RUN_START)
    assert rs["model"] == "extratrees"


def test_run_dir_model_joblib_uses_selected_model(monkeypatch, tmp_path):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    _patch(monkeypatch, df)
    T.train_loso(by="person", include_all=True, zscore_per_session=False,
                 pool="auto", model="extratrees", run_dir=tmp_path)
    bundle = joblib.load(tmp_path / "model.joblib")
    assert isinstance(bundle["model"], ExtraTreesClassifier)


def test_default_model_is_rf(monkeypatch, tmp_path):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    _patch(monkeypatch, df)
    seen = []
    T.train_loso(by="person", include_all=True, zscore_per_session=False,
                 pool="auto", run_dir=tmp_path, on_event=seen.append)
    rs = next(e for e in seen if e["type"] == E.RUN_START)
    assert rs["model"] == "rf"
    bundle = joblib.load(tmp_path / "model.joblib")
    assert isinstance(bundle["model"], RandomForestClassifier)
