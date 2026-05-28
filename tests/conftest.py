"""Common test setup: redirect data paths to a tmp dir per test."""

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.server.config import (  # noqa: E402
    AIRPODS_FIELDNAMES, SESSIONS_FIELDNAMES, WATCH_FIELDNAMES,
)
from src.pen_schema import PEN_FIELDNAMES  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _synthetic_inference_model(tmp_path_factory):
    # Why: models/ is gitignored, so CI checkouts start empty and the
    # live-inference tests have nothing to load. We synthesize a minimal
    # joblib whose feature_cols come from the real _window_features so the
    # bundle stays in lock-step with the feature extractor. MODELS +
    # _DEFAULT_MODEL_PATHS are redirected to a tmp dir for the whole session,
    # so local devs' real joblibs are bypassed too (hermetic test env).
    import joblib
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier

    from src.server import inference as inf_module
    from src.server.routes import inference as inf_route
    from src.features.windows import _window_features

    rng = np.random.default_rng(0)
    feature_cols = list(
        _window_features(rng.standard_normal((100, 6)) * 0.3, fs_hz=100.0).keys()
    )
    X = rng.standard_normal((20, len(feature_cols)))
    y = np.array([0, 1] * 10)
    clf = RandomForestClassifier(n_estimators=2, random_state=42).fit(X, y)

    tmp_models = tmp_path_factory.mktemp("inference_models")
    target = tmp_models / "rf_noah.joblib"
    joblib.dump({
        "model": clf,
        "feature_cols": feature_cols,
        "person_id": "synthetic",
        "sample_rate_hz": 100,
        "trained_on": "conftest synthetic",
        "n_windows": 20,
        "zscore_mu": None,
        "zscore_sigma": None,
    }, target)

    orig_models = inf_module.MODELS
    orig_paths = inf_module._DEFAULT_MODEL_PATHS
    orig_route_models = inf_route.MODELS  # route imported MODELS by name → separate binding
    inf_module.MODELS = tmp_models
    inf_module._DEFAULT_MODEL_PATHS = (target,)
    inf_route.MODELS = tmp_models
    # Module-level singleton may have been imported with the old MODELS;
    # clear it so the next predict() reloads from the patched path.
    inf_module.live._bundle = None
    inf_module.live._loaded_from = None
    inf_module.live._buffer.clear()
    inf_module.live._proba_history.clear()

    yield

    inf_module.MODELS = orig_models
    inf_module._DEFAULT_MODEL_PATHS = orig_paths
    inf_route.MODELS = orig_route_models


@pytest.fixture
def data_dirs(tmp_path, monkeypatch):
    """Point all DATA_RAW_* / SESSIONS_CSV constants at a tmp dir.

    Returns a small bag with the resolved paths so tests can write fixtures.
    """
    pen_dir = tmp_path / "raw" / "pen"
    watch_dir = tmp_path / "raw" / "watch"
    airpods_dir = tmp_path / "raw" / "airpods"
    markers_dir = tmp_path / "raw" / "markers"
    pen_dir.mkdir(parents=True)
    watch_dir.mkdir(parents=True)
    airpods_dir.mkdir(parents=True)
    markers_dir.mkdir(parents=True)
    sessions_csv = tmp_path / "sessions.csv"
    with open(sessions_csv, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writeheader()

    # Patch every module that imported the constants directly.
    import src.server.config as config
    import src.server.csv_io as csv_io
    import src.server.quality as quality
    import src.server.routes.airpods as routes_airpods
    import src.server.routes.sessions as routes_sessions
    import src.server.routes.watch as routes_watch
    import src.server.sync as sync_mod
    import src.server.timelines as timelines

    for mod in (
        config, csv_io, quality, sync_mod, timelines,
        routes_airpods, routes_sessions, routes_watch,
    ):
        if hasattr(mod, "DATA_RAW_PEN"):
            monkeypatch.setattr(mod, "DATA_RAW_PEN", pen_dir, raising=False)
        if hasattr(mod, "DATA_RAW_WATCH"):
            monkeypatch.setattr(mod, "DATA_RAW_WATCH", watch_dir, raising=False)
        if hasattr(mod, "DATA_RAW_AIRPODS"):
            monkeypatch.setattr(mod, "DATA_RAW_AIRPODS", airpods_dir, raising=False)
        if hasattr(mod, "DATA_RAW_MARKERS"):
            monkeypatch.setattr(mod, "DATA_RAW_MARKERS", markers_dir, raising=False)
        if hasattr(mod, "MARKERS_DIR"):
            monkeypatch.setattr(mod, "MARKERS_DIR", markers_dir, raising=False)
        if hasattr(mod, "SESSIONS_CSV"):
            monkeypatch.setattr(mod, "SESSIONS_CSV", sessions_csv, raising=False)

    # csv_io caches watch CSV writers per path; reset so tests don't see stale handles.
    csv_io._watch_writers.clear() if hasattr(csv_io, "_watch_writers") else None
    csv_io._airpods_writers.clear() if hasattr(csv_io, "_airpods_writers") else None
    csv_io._pen_count_cache.clear() if hasattr(csv_io, "_pen_count_cache") else None
    csv_io._airpods_count_cache.clear() if hasattr(csv_io, "_airpods_count_cache") else None

    # Quality caches results by session id; clear so tests don't see stale facts.
    quality._facts_cache.clear()

    return type("DataDirs", (), {
        "pen": pen_dir,
        "watch": watch_dir,
        "airpods": airpods_dir,
        "markers": markers_dir,
        "sessions": sessions_csv,
    })


def write_pen_csv(path: Path, rows: list[dict]):
    """Write a pen CSV with the canonical schema. Missing keys default to ''."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PEN_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in PEN_FIELDNAMES})


def write_watch_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WATCH_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in WATCH_FIELDNAMES})


def write_airpods_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AIRPODS_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in AIRPODS_FIELDNAMES})


def append_session_row(sessions_csv: Path, row: dict):
    with open(sessions_csv, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=SESSIONS_FIELDNAMES).writerow(
            {k: row.get(k, "") for k in SESSIONS_FIELDNAMES}
        )
