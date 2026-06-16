import io
import json

from src.training import events


def test_json_line_emitter_writes_one_json_line_per_event():
    buf = io.StringIO()
    emit = events.json_line_emitter(stream=buf)
    emit({"type": events.RUN_START, "model": "rf", "n_folds": 3})
    emit({"type": events.FOLD_END, "idx": 1, "person": "P07", "acc": 0.9})
    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "run_start" and first["n_folds"] == 3
    assert json.loads(lines[1])["person"] == "P07"


def test_event_type_constants_are_stable_strings():
    assert events.RUN_START == "run_start"
    assert events.FOLD_START == "fold_start"
    assert events.FOLD_END == "fold_end"
    assert events.RUN_END == "run_end"
    assert events.ERROR == "error"
