import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from src.server.inference import LiveInference


def _dump_dummy_model(path):
    clf = RandomForestClassifier(n_estimators=3).fit(
        np.random.rand(20, 88), np.random.randint(0, 2, 20))
    joblib.dump({"model": clf, "feature_cols": [f"f{i}" for i in range(88)],
                 "sample_rate_hz": 50}, path)


def test_load_sandbox_swaps_model_and_labels_sandbox(tmp_path):
    p = tmp_path / "model.joblib"
    _dump_dummy_model(p)
    inf = LiveInference()
    assert inf.load_sandbox(p) is True
    assert inf.model_id == "sandbox"


def test_load_sandbox_missing_file_returns_false(tmp_path):
    inf = LiveInference()
    assert inf.load_sandbox(tmp_path / "nope.joblib") is False


def test_normal_load_after_sandbox_clears_label(tmp_path):
    p = tmp_path / "rf_demo.joblib"
    _dump_dummy_model(p)
    inf = LiveInference()
    inf.load_sandbox(tmp_path / "model.joblib") if False else None
    inf.load_sandbox(p)
    assert inf.model_id == "sandbox"
    # Ein regulärer load_model setzt das Sandbox-Label zurück.
    inf.load_model(p)
    assert inf.model_id == "rf_demo"
