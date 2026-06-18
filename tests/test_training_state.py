from src.server import training as tr


def test_initial_state_is_idle():
    run = tr.TrainingRun()
    assert run.snapshot()["phase"] == "idle"
    assert run.is_busy() is False


def test_handle_events_builds_running_then_done():
    run = tr.TrainingRun()
    run._on_started("rf", "legacy", "2026-06-16_10-00_rf_legacy")
    run._handle_event({"type": "run_start", "model": "rf", "n_folds": 3})
    run._handle_event({"type": "fold_end", "idx": 1, "person": "P1", "n": 3,
                       "acc": 0.9, "auc": 0.95, "f1": 0.9,
                       "confusion": {"tn": 5, "fp": 1, "fn": 1, "tp": 5}})
    snap = run.snapshot()
    assert snap["phase"] == "running"
    assert snap["fold"] == 1 and snap["n"] == 3
    assert snap["folds"][0]["person"] == "P1"
    assert snap["confusion"] == {"tn": 5, "fp": 1, "fn": 1, "tp": 5}
    run._handle_event({"type": "run_end", "partial": False, "n_done": 1,
                       "mean_acc": 0.9, "std_acc": 0.0, "auc": 0.95, "f1": 0.9,
                       "burst": {}, "out_dir": "models/runs/x"})
    assert run.snapshot()["phase"] == "done"


def test_confusion_accumulates_across_folds():
    run = tr.TrainingRun()
    run._on_started("rf", "legacy", "rid")
    run._handle_event({"type": "run_start", "n_folds": 2})
    for i in (1, 2):
        run._handle_event({"type": "fold_end", "idx": i, "person": f"P{i}", "n": 2,
                           "acc": 0.9, "auc": 0.9, "f1": 0.9,
                           "confusion": {"tn": 2, "fp": 1, "fn": 0, "tp": 3}})
    assert run.snapshot()["confusion"] == {"tn": 4, "fp": 2, "fn": 0, "tp": 6}


def test_is_busy_guard():
    run = tr.TrainingRun()
    assert run.is_busy() is False
    run._on_started("rf", "legacy", "rid")
    run._handle_event({"type": "run_start", "n_folds": 2})
    assert run.is_busy() is True


def test_build_cmd_zscore_flag():
    on = tr._build_cmd("rf", "legacy", "person", True, "/tmp/r")
    assert "--emit-json" in on and "--run-dir" in on and "--no-zscore" not in on
    off = tr._build_cmd("rf", "legacy", "person", False, "/tmp/r")
    assert "--no-zscore" in off


def test_build_cmd_burst_scales():
    cmd = tr._build_cmd("rf", "legacy", "person", True, "/tmp/r",
                        burst_scales="5,30")
    i = cmd.index("--burst-scales")
    assert cmd[i + 1] == "5,30"


def test_build_cmd_burst_scales_default_omits_flag():
    cmd = tr._build_cmd("rf", "legacy", "person", True, "/tmp/r")
    assert "--burst-scales" not in cmd


def test_build_cmd_burst_scales_empty_is_passed_through():
    # Why: "" is meaningful (report only the 1 s base) and must reach the CLI,
    # distinct from None (use the backend default 5,10,30).
    cmd = tr._build_cmd("rf", "legacy", "person", True, "/tmp/r",
                        burst_scales="")
    i = cmd.index("--burst-scales")
    assert cmd[i + 1] == ""


def test_error_event_sets_error_phase():
    run = tr.TrainingRun()
    run._on_started("rf", "legacy", "rid")
    run._handle_event({"type": "run_start", "n_folds": 1})
    run._handle_event({"type": "error", "message": "boom"})
    snap = run.snapshot()
    assert snap["phase"] == "error" and snap["error"] == "boom"
