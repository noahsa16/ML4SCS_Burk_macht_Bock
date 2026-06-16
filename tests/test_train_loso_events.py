import numpy as np
import pandas as pd

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
    # Windows tragen kein person_id (das kommt per merge aus sessions) —
    # sonst kollidiert der person_id-Merge in train_loso.
    monkeypatch.setattr(
        T, "_load_windows",
        lambda sid, profile=None:
            df[df.session_id == sid].drop(columns=["person_id"]).copy())


def test_on_event_receives_run_and_fold_events(monkeypatch):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    _patch(monkeypatch, df)
    seen = []
    T.train_loso(by="person", include_all=True, zscore_per_session=False,
                 pool="auto", on_event=seen.append)
    types = [e["type"] for e in seen]
    assert types[0] == E.RUN_START
    assert E.FOLD_END in types and types[-1] == E.RUN_END
    fe = next(e for e in seen if e["type"] == E.FOLD_END)
    assert {"idx", "person", "acc", "auc", "f1", "confusion"} <= set(fe)
    assert {"tn", "fp", "fn", "tp"} <= set(fe["confusion"])
    re = next(e for e in seen if e["type"] == E.RUN_END)
    assert re["partial"] is False and re["n_done"] == 3


def test_keyboardinterrupt_emits_partial_run_end(monkeypatch):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    _patch(monkeypatch, df)
    calls = {"n": 0}
    real = T._fit_eval_fold

    def _boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real(*a, **k)

    monkeypatch.setattr(T, "_fit_eval_fold", _boom)
    seen = []
    T.train_loso(by="person", include_all=True, zscore_per_session=False,
                 pool="auto", on_event=seen.append)
    re = next(e for e in seen if e["type"] == E.RUN_END)
    assert re["partial"] is True and re["n_done"] == 1


def test_run_dir_writes_artifacts(monkeypatch, tmp_path):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    _patch(monkeypatch, df)
    T.train_loso(by="person", include_all=True, zscore_per_session=False,
                 pool="auto", run_dir=tmp_path)
    assert (tmp_path / "cv.csv").exists()
    assert (tmp_path / "oof.csv").exists()
    assert (tmp_path / "model.joblib").exists()
