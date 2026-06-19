import csv
import json

from src.server import training_runs as tr


def test_list_runs_computes_mean_acc_from_cv(tmp_path):
    # Why: config.json wird beim Start ohne mean_acc geschrieben; das Ergebnis
    # lebt in cv.csv (per-fold accuracy). list_runs muss es daraus mitteln,
    # sonst zeigt die Historie "–".
    d = tr.run_dir("2026-06-18_10-00_rf_legacy", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "legacy"})
    with open(d / "cv.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["held_out", "accuracy", "roc_auc"])
        w.writerow(["P1", "0.90", "0.95"])
        w.writerow(["P2", "0.80", "0.85"])
    r = next(x for x in tr.list_runs(root=tmp_path)
             if x["run_id"].endswith("rf_legacy"))
    assert abs(r["mean_acc"] - 0.85) < 1e-9
    assert r["n_folds"] == 2
    assert abs(r["mean_auc"] - 0.90) < 1e-9


def test_list_runs_without_cv_has_no_mean_acc(tmp_path):
    d = tr.run_dir("2026-06-18_11-00_rf_legacy", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "legacy"})  # Stub: nur config
    r = tr.list_runs(root=tmp_path)[0]
    assert "mean_acc" not in r  # kein cv.csv -> kein Ergebnis


def test_delete_run_removes_dir(tmp_path):
    d = tr.run_dir("2026-06-18_09-00_rf_legacy", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "legacy"})
    assert d.exists()
    assert tr.delete_run("2026-06-18_09-00_rf_legacy", root=tmp_path) is True
    assert not d.exists()


def test_delete_run_unknown_returns_false(tmp_path):
    assert tr.delete_run("does-not-exist", root=tmp_path) is False


def test_delete_run_rejects_escape(tmp_path):
    # Why: run_id darf nicht aus RUNS_ROOT ausbrechen und Fremdes löschen.
    root = tmp_path / "runs"; root.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    assert tr.delete_run("../outside", root=root) is False
    assert outside.exists()


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


def test_write_timing_persists_folds_and_total(tmp_path):
    d = tr.run_dir("2026-06-19_10-00_rf_legacy", root=tmp_path)
    tr.write_timing(d, [{"person": "P1", "sec": 3.0},
                        {"person": "P2", "sec": 5.0}], total_sec=10.0)
    data = json.loads((d / "timing.json").read_text())
    assert data["total_sec"] == 10.0
    assert [f["sec"] for f in data["folds"]] == [3.0, 5.0]


def test_list_runs_attaches_total_sec_from_timing(tmp_path):
    d = tr.run_dir("2026-06-19_10-00_rf_legacy", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "legacy"})
    tr.write_timing(d, [{"person": "P1", "sec": 4.0}], total_sec=12.5)
    r = tr.list_runs(root=tmp_path)[0]
    assert r["total_sec"] == 12.5


def test_estimate_returns_median_per_fold_across_matching_runs(tmp_path):
    # Zwei rf/legacy-Läufe → alle Fold-Dauern gepoolt, Median als pro-Fold-Schätzer.
    d1 = tr.run_dir("2026-06-19_10-00_rf_legacy", root=tmp_path)
    tr.write_config(d1, {"model": "rf", "pool": "legacy"})
    tr.write_timing(d1, [{"person": "P1", "sec": 4.0},
                         {"person": "P2", "sec": 6.0}], total_sec=12.0)
    d2 = tr.run_dir("2026-06-19_11-00_rf_legacy", root=tmp_path)
    tr.write_config(d2, {"model": "rf", "pool": "legacy"})
    tr.write_timing(d2, [{"person": "P3", "sec": 8.0}], total_sec=9.0)
    est = tr.estimate("rf", "legacy", root=tmp_path)
    assert est["n_runs"] == 2
    assert est["per_fold_sec"] == 6.0  # median([4, 6, 8])


def test_estimate_filters_by_model_and_pool(tmp_path):
    d = tr.run_dir("2026-06-19_10-00_cnn_legacy", root=tmp_path)
    tr.write_config(d, {"model": "cnn", "pool": "legacy"})
    tr.write_timing(d, [{"person": "P1", "sec": 90.0}], total_sec=100.0)
    est = tr.estimate("rf", "legacy", root=tmp_path)  # anderes Modell → kein Treffer
    assert est == {"per_fold_sec": None, "n_runs": 0}


def test_estimate_empty_when_no_history(tmp_path):
    assert tr.estimate("rf", "legacy", root=tmp_path) == {"per_fold_sec": None, "n_runs": 0}
