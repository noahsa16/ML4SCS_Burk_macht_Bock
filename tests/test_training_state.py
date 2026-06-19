import asyncio
import sys
import textwrap

from src.server import training as tr

# Synthetischer Runner: run_start, dann eine Schleife. "catch" ehrt SIGINT und
# emittiert run_end (graceful); "ignore" ignoriert SIGINT und läuft weiter
# (mimt einen Runner, dessen Interrupt nicht landet — torch/joblib in C).
_CHILD = textwrap.dedent('''
    import sys, time, json, signal
    mode = sys.argv[1]
    def emit(e): sys.stdout.write(json.dumps(e)+"\\n"); sys.stdout.flush()
    emit({"type":"run_start","n_folds":3})
    stop = {"v": False}
    if mode == "catch":
        signal.signal(signal.SIGINT, lambda s,f: stop.__setitem__("v", True))
    elif mode == "ignore":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    i = 0
    while not stop["v"] and i < 400:   # ~20 s, deutlich > Test-grace
        time.sleep(0.05); i += 1
    emit({"type":"run_end","partial":True,"n_done":1,"mean_acc":0.5,
          "std_acc":0.0,"auc":0.5,"f1":0.5,"burst":{},"out_dir":""})
''')


def _stop_trial(monkeypatch, tmp_path, mode, grace=0.4):
    """Fährt start()→stop() mit einem synthetischen Child und gibt den Snapshot
    nach dem Stop zurück (Runner-/Subprozess-frei dank gepatchtem _build_cmd)."""
    monkeypatch.setattr(
        tr, "_build_cmd",
        lambda *a, **k: [sys.executable, "-u", "-c", _CHILD, mode])

    def fake_run_dir(rid):
        d = tmp_path / rid
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(tr.training_runs, "new_run_id", lambda m, p: "testrun")
    monkeypatch.setattr(tr.training_runs, "run_dir", fake_run_dir)
    monkeypatch.setattr(tr.training_runs, "write_config", lambda d, c: None)

    async def go():
        run = tr.TrainingRun()
        run._stop_grace_sec = grace
        await run.start("rf", "legacy")
        for _ in range(60):  # auf run_start warten
            if run.snapshot()["n"] == 3:
                break
            await asyncio.sleep(0.02)
        t0 = asyncio.get_event_loop().time()
        await run.stop()
        elapsed = asyncio.get_event_loop().time() - t0
        if run._reader is not None:
            await run._reader  # _read finalisiert die Terminal-Phase
        return run.snapshot(), elapsed

    return asyncio.run(go())


def test_stop_graceful_runner_settles_partial_done(monkeypatch, tmp_path):
    snap, _ = _stop_trial(monkeypatch, tmp_path, "catch")
    assert snap["phase"] == "done"
    assert snap["partial"] is True


def test_stop_unresponsive_runner_killed_clean_done(monkeypatch, tmp_path):
    # Runner ignoriert SIGINT → Eskalation auf Kill nach grace; ein NUTZER-Stop
    # landet sauber in done(partial), NICHT in error (Regression für den
    # "stoppt nicht wirklich bis Refresh"-Bug). elapsed << 20 s belegt, dass
    # nicht auf die natürliche Beendigung gewartet wird.
    snap, elapsed = _stop_trial(monkeypatch, tmp_path, "ignore", grace=0.3)
    assert snap["phase"] == "done"
    assert snap["partial"] is True
    assert snap["error"] is None
    assert elapsed < 3.0, f"stop dauerte {elapsed:.1f}s — keine Kill-Eskalation?"


def test_snapshot_exposes_stopping_flag():
    run = tr.TrainingRun()
    assert run.snapshot()["stopping"] is False


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


def test_build_cmd_window_and_gap():
    cmd = tr._build_cmd("rf", "legacy", "person", True, "/tmp/r",
                        window_sec=5.0, max_gap_ms=1000.0)
    assert cmd[cmd.index("--window-sec") + 1] == "5.0"
    assert cmd[cmd.index("--max-gap-ms") + 1] == "1000.0"


def test_build_cmd_window_gap_none_omits_flags():
    cmd = tr._build_cmd("rf", "legacy", "person", True, "/tmp/r")
    assert "--window-sec" not in cmd and "--max-gap-ms" not in cmd


def test_build_cmd_deep_uses_deep_runner():
    # Deep-Modelle verzweigen auf src.training.deep mit reduziertem Argsatz.
    cmd = tr._build_cmd("cnn", "legacy", "person", False, "/tmp/r")
    assert "src.training.deep" in cmd
    assert cmd[cmd.index("--model") + 1] == "cnn"
    assert "--emit-json" in cmd and "--run-dir" in cmd
    # by/burst/window gelten für rohe Sequenzen nicht → nicht durchgereicht.
    assert "--by" not in cmd
    assert "--burst-scales" not in cmd
    assert "--window-sec" not in cmd
    assert "--no-zscore" not in cmd  # Deep nutzt --zscore opt-in


def test_build_cmd_deep_zscore_optin_and_gap():
    on = tr._build_cmd("cnn", "legacy", "person", True, "/tmp/r", max_gap_ms=2500.0)
    assert "--zscore" in on
    assert on[on.index("--max-gap-ms") + 1] == "2500.0"
    off = tr._build_cmd("cnn", "legacy", "person", False, "/tmp/r")
    assert "--zscore" not in off


def test_error_event_sets_error_phase():
    run = tr.TrainingRun()
    run._on_started("rf", "legacy", "rid")
    run._handle_event({"type": "run_start", "n_folds": 1})
    run._handle_event({"type": "error", "message": "boom"})
    snap = run.snapshot()
    assert snap["phase"] == "error" and snap["error"] == "boom"


def test_fold_and_total_timing_accumulate_with_injected_clock():
    # Why: pro-Fold + Gesamt-Dauer werden über eine injizierbare Uhr gemessen,
    # damit _handle_event deterministisch unit-testbar bleibt (keine echte Zeit).
    run = tr.TrainingRun()
    now = [1000.0]
    run._clock = lambda: now[0]
    run._on_started("rf", "legacy", "rid")          # run_t0 = 1000
    run._handle_event({"type": "run_start", "n_folds": 2})
    run._handle_event({"type": "fold_start", "idx": 1, "person": "P1", "n": 2})
    now[0] = 1003.0
    run._handle_event({"type": "fold_end", "idx": 1, "person": "P1", "n": 2,
                       "acc": 0.9, "auc": 0.9, "f1": 0.9, "confusion": {}})   # 3 s
    run._handle_event({"type": "fold_start", "idx": 2, "person": "P2", "n": 2})
    now[0] = 1009.0
    run._handle_event({"type": "fold_end", "idx": 2, "person": "P2", "n": 2,
                       "acc": 0.9, "auc": 0.9, "f1": 0.9, "confusion": {}})   # 6 s
    now[0] = 1010.0
    run._handle_event({"type": "run_end", "partial": False, "n_done": 2,
                       "mean_acc": 0.9, "std_acc": 0.0, "auc": 0.9, "f1": 0.9,
                       "burst": {}, "out_dir": ""})
    assert [round(f["sec"]) for f in run.fold_secs] == [3, 6]
    assert [f["person"] for f in run.fold_secs] == ["P1", "P2"]
    assert round(run.total_sec) == 10


def test_snapshot_exposes_elapsed_running_then_total_when_done():
    run = tr.TrainingRun()
    now = [100.0]
    run._clock = lambda: now[0]
    run._on_started("rf", "legacy", "rid")          # run_t0 = 100
    run._handle_event({"type": "run_start", "n_folds": 1})
    now[0] = 107.0
    assert round(run.snapshot()["elapsed_sec"]) == 7          # läuft → live elapsed
    now[0] = 120.0
    run._handle_event({"type": "run_end", "partial": False, "n_done": 1,
                       "mean_acc": 0.9, "std_acc": 0.0, "auc": 0.9, "f1": 0.9,
                       "burst": {}, "out_dir": ""})
    assert round(run.snapshot()["elapsed_sec"]) == 20         # done → eingefrorene Gesamtzeit


def test_persist_timing_writes_file(tmp_path):
    run = tr.TrainingRun()
    run._run_dir = tmp_path
    run.fold_secs = [{"person": "P1", "sec": 3.0}]
    run.total_sec = 5.0
    run._persist_timing()
    import json
    data = json.loads((tmp_path / "timing.json").read_text())
    assert data["total_sec"] == 5.0 and data["folds"][0]["person"] == "P1"


def test_persist_timing_noop_without_fold_data(tmp_path):
    # Lauf ohne fertige Folds (sofort gestoppt) schreibt keine irreführende
    # Null-Dauer in den Schätz-Pool.
    run = tr.TrainingRun()
    run._run_dir = tmp_path
    run._persist_timing()
    assert not (tmp_path / "timing.json").exists()


def test_epoch_events_track_loss_history_reset_per_fold():
    # Deep-Modelle: echte Per-Epochen-Loss/Val-AUC werden gesammelt; jeder Fold
    # trainiert frisch → loss_hist startet pro Fold neu.
    run = tr.TrainingRun()
    run._on_started("cnn", "legacy", "rid")
    run._handle_event({"type": "run_start", "n_folds": 2})
    run._handle_event({"type": "fold_start", "idx": 1, "person": "P1", "n": 2})
    run._handle_event({"type": "epoch", "fold": 1, "epoch": 0, "loss": 0.5, "val_auc": 0.7})
    run._handle_event({"type": "epoch", "fold": 1, "epoch": 1, "loss": 0.3, "val_auc": 0.85})
    snap = run.snapshot()
    assert snap["epoch"] == 1
    assert round(snap["epoch_loss"], 3) == 0.3
    assert [h["loss"] for h in snap["loss_hist"]] == [0.5, 0.3]
    assert snap["loss_hist"][1]["val_auc"] == 0.85
    # neuer Fold → loss_hist + epoch zurückgesetzt
    run._handle_event({"type": "fold_start", "idx": 2, "person": "P2", "n": 2})
    snap2 = run.snapshot()
    assert snap2["loss_hist"] == [] and snap2["epoch"] is None
