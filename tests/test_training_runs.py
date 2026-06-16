import json

from src.server import training_runs as tr


def test_new_run_dir_is_unique_and_has_config(tmp_path):
    rid = tr.new_run_id("rf", "legacy", now="2026-06-16_19-43")
    assert rid == "2026-06-16_19-43_rf_legacy"
    d = tr.run_dir(rid, root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "legacy"})
    assert (d / "config.json").exists()
    assert json.loads((d / "config.json").read_text())["model"] == "rf"


def test_list_runs_reads_back_configs_newest_first(tmp_path):
    for rid in ["2026-06-16_10-00_rf_legacy", "2026-06-16_12-00_rf_auto"]:
        d = tr.run_dir(rid, root=tmp_path)
        tr.write_config(d, {"model": "rf", "pool": rid.split("_")[-1],
                            "mean_acc": 0.87})
    runs = tr.list_runs(root=tmp_path)
    assert [r["run_id"] for r in runs] == [
        "2026-06-16_12-00_rf_auto", "2026-06-16_10-00_rf_legacy"]
    assert runs[0]["mean_acc"] == 0.87


def test_promote_copies_artifacts_to_canonical(tmp_path):
    src_dir = tr.run_dir("2026-06-16_12-00_rf_auto", root=tmp_path)
    (src_dir / "cv.csv").write_text("held_out,accuracy\nP01,0.9\n")
    (src_dir / "oof.csv").write_text("session_id,label\nS1,1\n")
    (src_dir / "model.joblib").write_bytes(b"x")
    canon = tmp_path / "canon"
    tr.promote("2026-06-16_12-00_rf_auto", root=tmp_path, canonical_dir=canon)
    assert (canon / "loso_cv.csv").read_text().startswith("held_out")
    assert (canon / "loso_oof.csv").exists()
    assert (canon / "rf_all.joblib").read_bytes() == b"x"


def test_promote_unknown_run_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        tr.promote("nope", root=tmp_path, canonical_dir=tmp_path / "c")
