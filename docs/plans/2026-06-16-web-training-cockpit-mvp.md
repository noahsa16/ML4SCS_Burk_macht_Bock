# Web-Training-Cockpit (Demo-MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Einen „Training"-Tab im Dashboard, von dem aus ein RF-LOSO-Lauf gestartet, live verfolgt (Fold-für-Fold, Live-Confusion, Hardware-Last) und nach dem Lauf analysiert wird — inkl. Graceful Stop und Sandbox-Inference, ohne die kanonische Headline zu überschreiben.

**Architecture:** Die LOSO-Runner emittieren strukturierte JSON-Events auf stdout (Ansatz B). Eine `TrainingRun`-State-Machine startet den Runner als Subprozess (Muster wie `pen_proc.py`), parst die Events, misst per `psutil` die Last und broadcastet alles über den bestehenden WebSocket. Jeder Lauf schreibt in ein eigenes `models/runs/{run_id}/`-Verzeichnis (nicht-destruktiv); die kanonischen Artefakte ändern sich nur per expliziter Promotion. Das Frontend ist ein vanilla-JS-Page-Modul mit dem etablierten `mount/onStatus/onShow/onHide`-Contract.

**Tech Stack:** Python 3.13, FastAPI, scikit-learn, joblib, pandas, numpy, **psutil** (neu); vanilla ES-Modul-JS + handgeschriebenes CSS (oklch-Tokens, IBM Plex), pytest.

---

## Scope (MVP — bewusst eng)

**Drin:** RF-LOSO starten/stoppen/promoten, Live-Cockpit (3 Zustände idle/läuft/fertig), Per-Person-Grid, Konvergenz-Kurve, **Live-Confusion-Matrix**, Log-Ticker, **Hardware-Sparkline**, **Graceful Stop**, nicht-destruktive Run-Historie, **Sandbox-Inference**, Done-State-Analyse (Confusion, ROC, Feature-Gruppen, Burst-Kurve), Per-Person-Drill-in.

**Raus (post-MVP, eigene Pläne):** Deep/harnet/klassische Nicht-RF-Runner im Menü (nur die Registry-Struktur wird vorbereitet), neue Modelle (TCN/BiLSTM/Focal), SHAP-Waterfall, Session-Replay-Geist, Auto-Narrativ, Quaternion-Capture, Modell-Vergleich-Drawer mit Wilcoxon, „Fehler nach Task"-Card. Diese werden im Code durch klare Erweiterungspunkte (Registry, Event-Schema, Drawer) nicht verbaut.

**Referenz-Design:** Der eingefrorene immersive Look (Dark + Light, oklch-Tokens, Branding-Slash) — Mockups `light-immersive.html` / `full-lifecycle.html` aus der Brainstorming-Session; Spec `docs/specs/2026-06-16-web-training-cockpit-design.md`.

## File Structure

**Neu (Backend):**
- `src/training/events.py` — Event-Schema-Konstanten + `json_line_emitter`. Eine Verantwortung: Runner→Server-Eventprotokoll.
- `src/training/registry.py` — `ModelSpec` + `MODELS`-Liste (MVP: nur RF) + Lookups. Single source of truth für Menü/Validität/Tooltips.
- `src/server/training_runs.py` — Run-Verzeichnis-Verwaltung (run_id, write config, list, promote). Reine Dateilogik, FastAPI-frei, unit-testbar.
- `src/server/training.py` — `TrainingRun`-State-Machine + Subprozess-Lifecycle + stdout-Parser + psutil-Sampling.
- `src/server/routes/training.py` — FastAPI-Router (`/training/*`).
- `tests/test_training_events.py`, `tests/test_training_registry.py`, `tests/test_training_runs.py`, `tests/test_training_state.py`, `tests/test_training_endpoints.py`.

**Neu (Frontend):**
- `static/views/training.html` — Markup-Partial (drei Zustands-Container).
- `static/js/pages/training.js` — Page-Modul (`mount/onStatus/onShow/onHide`) + Rendering.
- `static/css/training.css` — Immersiver Look, oklch-Tokens, Branding-Slash.

**Modifiziert:**
- `src/training/train_loso.py` — `on_event`/`run_dir`-Parameter + Graceful Stop + `--emit-json`/`--run-dir`-CLI.
- `src/server/inference.py` — `load_sandbox(path)` (temporärer Modell-Load ohne Whitelist).
- `src/server/broadcast.py` — Training-Payload + hw in den 1-Hz-Tick.
- `src/server/routes/__init__.py` — Training-Router aggregieren.
- `dashboard.html` — „Training"-Tab + leerer View-Slot.
- `static/dashboard.js` — Page-Registry um `training` erweitern (+ ggf. `Object.assign(window, …)`).
- `static/js/core/router.js` — Tab-Indicator kennt `training`.
- `requirements.txt` — `psutil`.
- `tests/test_dashboard_static.py` — neue Asset-Pfade.
- `CLAUDE.md` — kurzer Abschnitt „Training-Cockpit".

---

## Task 1: Event-Schema + Emitter

**Files:**
- Create: `src/training/events.py`
- Test: `tests/test_training_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_training_events.py
import json
import io
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_training_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.training.events'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/training/events.py
"""Strukturiertes Runner→Server-Eventprotokoll (Ansatz B).

Die LOSO-Runner rufen optional ``on_event(dict)``. Im Web-Pfad ist das
``json_line_emitter`` (eine JSON-Zeile pro Event auf stdout); ohne Callback
bleibt das bisherige Print-Verhalten unverändert.
"""
from __future__ import annotations

import json
import sys
from typing import Callable, TextIO

RUN_START = "run_start"
FOLD_START = "fold_start"
FOLD_END = "fold_end"
RUN_END = "run_end"
ERROR = "error"

EventCallback = Callable[[dict], None]


def json_line_emitter(stream: TextIO | None = None) -> EventCallback:
    """Gibt einen Callback zurück, der jedes Event als JSON-Zeile schreibt + flusht."""
    out = stream if stream is not None else sys.stdout

    def _emit(event: dict) -> None:
        out.write(json.dumps(event) + "\n")
        out.flush()

    return _emit
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_training_events.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/training/events.py tests/test_training_events.py
git commit -m "feat(training): JSON-Line Event-Emitter für Web-Launcher (Ansatz B)"
```

---

## Task 2: Modell-Registry (MVP: RF)

**Files:**
- Create: `src/training/registry.py`
- Test: `tests/test_training_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_training_registry.py
import pytest
from src.training import registry


def test_rf_spec_present_and_well_formed():
    spec = registry.get("rf")
    assert spec.id == "rf"
    assert spec.family == "classical"
    assert spec.speed == "fast"
    assert "legacy" in spec.valid_pools and "auto" in spec.valid_pools
    assert spec.supports_feature_importance is True
    assert spec.causal is True  # RF ist live-tauglich (Sandbox)
    assert spec.description  # nicht leer (Tooltip)


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        registry.get("does-not-exist")


def test_list_models_returns_serialisable_dicts():
    rows = registry.list_models()
    assert any(r["id"] == "rf" for r in rows)
    for r in rows:
        assert {"id", "label", "family", "speed", "valid_pools",
                "supports_feature_importance", "causal", "description"} <= set(r)


def test_validate_pool_rejects_invalid_combo():
    assert registry.validate("rf", "legacy") is True
    assert registry.validate("rf", "nonsense") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_training_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.training.registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/training/registry.py
"""Single source of truth für das Modell-Menü, Pool-Validität und Tooltips.

MVP: nur RandomForest ist verdrahtet. Weitere Modelle (Deep/harnet/klassisch)
docken hier mit demselben Schema an, ohne Launcher/Frontend zu ändern.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    family: str            # "classical" | "deep" | "foundation"
    speed: str             # "fast" (live-demo) | "slow" (background)
    valid_pools: frozenset[str]
    supports_feature_importance: bool
    supports_zscore: bool
    causal: bool           # False => nicht live-tauglich (z. B. BiLSTM)
    runner: str            # python -m <runner>
    description: str


MODELS: dict[str, ModelSpec] = {
    "rf": ModelSpec(
        id="rf",
        label="RandomForest",
        family="classical",
        speed="fast",
        valid_pools=frozenset({"auto", "legacy", "modern"}),
        supports_feature_importance=True,
        supports_zscore=True,
        causal=True,
        runner="src.training.train_loso",
        description=(
            "Klassisch, 88/92 Features. Schnell (live-demo-tauglich). "
            "Per-Session-Z-Score an. Feature-Gruppen-Importance verfügbar."
        ),
    ),
}


def get(model_id: str) -> ModelSpec:
    if model_id not in MODELS:
        raise KeyError(f"unknown model {model_id!r}; have {sorted(MODELS)}")
    return MODELS[model_id]


def list_models() -> list[dict]:
    out = []
    for spec in MODELS.values():
        d = asdict(spec)
        d["valid_pools"] = sorted(spec.valid_pools)
        out.append(d)
    return out


def validate(model_id: str, pool: str) -> bool:
    return model_id in MODELS and pool in MODELS[model_id].valid_pools
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_training_registry.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/training/registry.py tests/test_training_registry.py
git commit -m "feat(training): Modell-Registry (MVP: RandomForest)"
```

---

## Task 3: Run-Store (Verzeichnisse + Promotion)

**Files:**
- Create: `src/server/training_runs.py`
- Test: `tests/test_training_runs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_training_runs.py
import json
from pathlib import Path
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_training_runs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.server.training_runs'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/server/training_runs.py
"""Nicht-destruktive Run-Verzeichnisse + explizite Headline-Promotion.

Jeder Lauf lebt in models/runs/{run_id}/ (cv.csv, oof.csv, model.joblib,
config.json, events.jsonl). Die kanonischen Artefakte (rf_all.joblib,
loso_cv.csv, loso_oof.csv) ändern sich ausschließlich über promote().
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
RUNS_ROOT = ROOT / "models" / "runs"
CANONICAL_DIR = ROOT / "models"

# Welche Run-Datei auf welchen kanonischen Namen promotet wird.
_PROMOTE_MAP = {
    "cv.csv": "loso_cv.csv",
    "oof.csv": "loso_oof.csv",
    "model.joblib": "rf_all.joblib",
}


def new_run_id(model: str, pool: str, now: str | None = None) -> str:
    stamp = now or datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"{stamp}_{model}_{pool}"


def run_dir(run_id: str, root: Path = RUNS_ROOT) -> Path:
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_config(d: Path, config: dict) -> None:
    (d / "config.json").write_text(json.dumps(config, indent=2))


def list_runs(root: Path = RUNS_ROOT) -> list[dict]:
    if not root.exists():
        return []
    rows = []
    for d in root.iterdir():
        cfg = d / "config.json"
        if not cfg.is_dir() and cfg.exists():
            data = json.loads(cfg.read_text())
            data["run_id"] = d.name
            rows.append(data)
    rows.sort(key=lambda r: r["run_id"], reverse=True)
    return rows


def promote(run_id: str, root: Path = RUNS_ROOT,
            canonical_dir: Path = CANONICAL_DIR) -> None:
    src = root / run_id
    if not src.exists():
        raise FileNotFoundError(f"run {run_id} not found")
    canonical_dir.mkdir(parents=True, exist_ok=True)
    for run_file, canon_name in _PROMOTE_MAP.items():
        p = src / run_file
        if p.exists():
            shutil.copy2(p, canonical_dir / canon_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_training_runs.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/server/training_runs.py tests/test_training_runs.py
git commit -m "feat(training): nicht-destruktiver Run-Store + Headline-Promotion"
```

---

## Task 4: `train_loso` instrumentieren (Events + run_dir + Graceful Stop)

**Files:**
- Modify: `src/training/train_loso.py` (Signatur `train_loso`, Fold-Loop ~474-514, `__main__`)
- Test: `tests/test_train_loso_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_train_loso_events.py
import numpy as np
import pandas as pd
import pytest
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
                # zwei trennbare Features
                "f0": rng.normal(label, 0.3), "f1": rng.normal(-label, 0.3),
            })
    return pd.DataFrame(rows)


def test_on_event_receives_run_and_fold_events(monkeypatch):
    df = _toy_windows([("S1", "P1"), ("S2", "P2"), ("S3", "P3")])
    monkeypatch.setattr(T, "_select_sessions",
                        lambda **k: df[["session_id", "person_id"]].drop_duplicates())
    monkeypatch.setattr(T, "_load_windows",
                        lambda sid, profile=None: df[df.session_id == sid].copy())
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
    monkeypatch.setattr(T, "_select_sessions",
                        lambda **k: df[["session_id", "person_id"]].drop_duplicates())
    monkeypatch.setattr(T, "_load_windows",
                        lambda sid, profile=None: df[df.session_id == sid].copy())
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_train_loso_events.py -v`
Expected: FAIL with `TypeError: train_loso() got an unexpected keyword argument 'on_event'`

- [ ] **Step 3: Implement — Signatur + Events + Graceful Stop**

In `src/training/train_loso.py`:

(a) Import oben ergänzen (nach `from src.features.windows import load_session_windows`):

```python
from src.training import events as _events
```

(b) Signatur von `train_loso` um zwei Parameter erweitern (an das Ende der Keyword-Args, vor dem `)` in Zeile ~406):

```python
    pool: str = "auto",
    drop_gravity: bool = False,
    on_event=None,
    run_dir: Path | None = None,
) -> dict:
    emit = on_event if on_event is not None else (lambda e: None)
```

(c) Direkt **vor** der Fold-Schleife (vor `fold_results: list[dict] = []`, ~Zeile 474):

```python
    emit({"type": _events.RUN_START, "model": "rf", "by": by, "pool": pool,
          "n_folds": len(groups), "features": len(feature_cols),
          "zscore": zscore_per_session})
    interrupted = False
```

(d) Die Fold-Schleife so umbauen, dass sie pro Fold `fold_start`/`fold_end` emittiert und `KeyboardInterrupt` abfängt. Ersetze die Schleife `for held_out in groups:` … bis `fold_results.append(res)` durch:

```python
    for fold_idx, held_out in enumerate(groups, start=1):
        emit({"type": _events.FOLD_START, "idx": fold_idx,
              "person": str(held_out), "n": len(groups)})
        test_mask = all_windows[group_col] == held_out
        train_df = all_windows[~test_mask]
        test_df = all_windows[test_mask]
        held_out_sessions = sessions.loc[
            sessions[group_col] == held_out, "session_id"].tolist()
        print(f"\n--- Fold: held-out {by}={held_out} (sessions={held_out_sessions}) ---")
        try:
            res = _fit_eval_fold(
                train_df, test_df, feature_cols, n_estimators, random_state)
        except KeyboardInterrupt:
            # Graceful Stop: bereits fertige Folds behalten, Schleife sauber verlassen.
            print("\n[stop] KeyboardInterrupt — finalisiere fertige Folds…")
            interrupted = True
            break
        if res is None:
            print("  skipped — test fold has only one class")
            continue
        res["held_out"] = held_out
        res["held_out_sessions"] = held_out_sessions
        print(res["report"])
        print(f"Accuracy: {res['accuracy']:.3f}   F1(writing): {res['f1_writing']:.3f}   "
              f"ROC-AUC: {res['roc_auc']:.3f}")
        cm = res["confusion_matrix"]
        emit({"type": _events.FOLD_END, "idx": fold_idx, "person": str(held_out),
              "n": len(groups), "acc": res["accuracy"], "auc": res["roc_auc"],
              "f1": res["f1_writing"],
              "burst": {k: v["accuracy"] for k, v in res["bursts"].items()},
              "confusion": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]),
                            "fn": int(cm[1, 0]), "tp": int(cm[1, 1])}})
        fold_results.append(res)
```

(e) `run_dir`-Artefakte + `run_end`. Direkt **vor** `return {"folds": fold_results, "summary": summary}` (Zeile ~611), nach dem `save_*`-Block:

```python
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        per_fold_table.to_csv(run_dir / "cv.csv", index=False)
        pd.concat([r["oof"] for r in fold_results], ignore_index=True).to_csv(
            run_dir / "oof.csv", index=False)
        _train_final_model(all_windows, feature_cols, sessions,
                           n_estimators, random_state, run_dir / "model.joblib")
    emit({"type": _events.RUN_END, "partial": interrupted,
          "n_done": len(fold_results),
          "mean_acc": summary["mean_accuracy"], "std_acc": summary["std_accuracy"],
          "auc": summary["mean_roc_auc"], "f1": summary["mean_f1_writing"],
          "burst": {k: v["mean_accuracy"] for k, v in burst_summary.items()},
          "out_dir": str(run_dir) if run_dir else ""})
```

(f) Im frühen Guard (Zeile ~516 `if not fold_results:`) ebenfalls ein `run_end` mit `partial=interrupted` emittieren, damit ein sofort gestoppter Lauf nicht stumm bleibt:

```python
    if not fold_results:
        print("\n[warn] All folds skipped / interrupted. Nothing to summarise.")
        emit({"type": _events.RUN_END, "partial": interrupted, "n_done": 0,
              "mean_acc": 0.0, "std_acc": 0.0, "auc": 0.0, "f1": 0.0,
              "burst": {}, "out_dir": ""})
        return {"folds": [], "summary": {}}
```

(g) CLI: in `_parse_args` zwei Flags + im `__main__` durchreichen. Nach `p.add_argument("--save-oof", …)` (~Zeile 686):

```python
    p.add_argument("--emit-json", action="store_true",
                   help="Strukturierte JSON-Events auf stdout (Web-Launcher).")
    p.add_argument("--run-dir", type=Path, default=None,
                   help="Artefakte (cv/oof/model) in dieses Verzeichnis schreiben.")
    p.add_argument("--model", default="rf", help="Registry-Modell-ID (MVP: rf).")
```

Im `__main__`-`train_loso(...)`-Aufruf (~Zeile 733) ergänzen:

```python
        on_event=_events.json_line_emitter() if args.emit_json else None,
        run_dir=args.run_dir,
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_train_loso_events.py tests/test_train_loso_pool.py -v`
Expected: PASS (neue 2 + bestehende Pool-Tests unverändert grün)

- [ ] **Step 5: Verify CLI unchanged without --emit-json**

Run: `python -m src.training.train_loso --pool legacy 2>&1 | head -5`
Expected: normale menschenlesbare Ausgabe wie bisher (keine JSON-Zeilen)

- [ ] **Step 6: Commit**

```bash
git add src/training/train_loso.py tests/test_train_loso_events.py
git commit -m "feat(training): train_loso emittiert Events + run_dir + Graceful Stop"
```

---

## Task 5: `TrainingRun`-State-Machine + Subprozess + psutil

**Files:**
- Create: `src/server/training.py`
- Modify: `requirements.txt` (psutil)
- Test: `tests/test_training_state.py`

- [ ] **Step 1: Add psutil dependency**

In `requirements.txt` eine Zeile `psutil` ergänzen, dann:

Run: `pip install psutil`
Expected: erfolgreich installiert

- [ ] **Step 2: Write the failing test**

```python
# tests/test_training_state.py
import pytest
from src.server import training as tr


def test_initial_state_is_idle():
    run = tr.TrainingRun()
    assert run.snapshot()["phase"] == "idle"


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_training_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.server.training'`

- [ ] **Step 4: Write the implementation**

```python
# src/server/training.py
"""Live-Trainings-Lauf: State-Machine + Subprozess + psutil-Sampling.

Genau EIN Lauf gleichzeitig. Der Runner läuft als asyncio-Subprozess mit
--emit-json (Muster wie pen_proc.py); der stdout-Reader parst JSON-Events und
aktualisiert den State, der über den bestehenden WS-Tick gebroadcastet wird.
"""
from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path

import psutil

from .config import ROOT
from . import training_runs


class TrainingRun:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = "idle"            # idle | running | done | error
        self.model: str | None = None
        self.pool: str | None = None
        self.run_id: str | None = None
        self.fold = 0
        self.n = 0
        self.folds: list[dict] = []
        self.confusion = {"tn": 0, "fp": 0, "fn": 0, "tp": 0}
        self.summary: dict = {}
        self.log: list[str] = []
        self.error: str | None = None
        self.hw = {"cpu_pct": 0.0, "ram_gb": 0.0}
        self.partial = False
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None

    def is_busy(self) -> bool:
        return self.phase == "running"

    # ---- event handling (pure, unit-testable) ----
    def _on_started(self, model: str, pool: str, run_id: str) -> None:
        self.reset()
        self.phase = "running"
        self.model, self.pool, self.run_id = model, pool, run_id

    def _handle_event(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "run_start":
            self.n = int(ev.get("n_folds", 0))
        elif t == "fold_start":
            self.fold = int(ev.get("idx", self.fold))
        elif t == "fold_end":
            self.fold = int(ev.get("idx", self.fold))
            self.n = int(ev.get("n", self.n))
            self.folds.append({k: ev.get(k) for k in
                               ("idx", "person", "acc", "auc", "f1")})
            c = ev.get("confusion") or {}
            for k in self.confusion:
                self.confusion[k] += int(c.get(k, 0))
            self.log.append(
                f"Fold {ev.get('idx')} {ev.get('person')} · "
                f"acc={ev.get('acc'):.3f} auc={ev.get('auc'):.3f}")
        elif t == "run_end":
            self.partial = bool(ev.get("partial", False))
            self.summary = {k: ev.get(k) for k in
                            ("mean_acc", "std_acc", "auc", "f1", "burst",
                             "out_dir", "n_done")}
            self.phase = "done"
        elif t == "error":
            self.error = str(ev.get("message", "unknown"))
            self.phase = "error"

    def snapshot(self) -> dict:
        return {
            "phase": self.phase, "model": self.model, "pool": self.pool,
            "run_id": self.run_id, "fold": self.fold, "n": self.n,
            "folds": self.folds, "confusion": self.confusion,
            "summary": self.summary, "partial": self.partial,
            "error": self.error, "hw": self.hw,
            "log": self.log[-8:],
        }

    # ---- subprocess lifecycle ----
    async def start(self, model: str, pool: str, by: str = "person") -> dict:
        if self.is_busy():
            return {"error": "busy"}
        run_id = training_runs.new_run_id(model, pool)
        rdir = training_runs.run_dir(run_id)
        training_runs.write_config(rdir, {"model": model, "pool": pool, "by": by})
        self._on_started(model, pool, run_id)
        cmd = [sys.executable, "-u", "-m", "src.training.train_loso",
               "--emit-json", "--model", model, "--pool", pool, "--by", by,
               "--run-dir", str(rdir)]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        self._reader = asyncio.create_task(self._read(self._proc))
        return {"ok": True, "run_id": run_id}

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        ps = psutil.Process(proc.pid)
        while True:
            try:
                line = await proc.stdout.readline()
            except ValueError:
                await proc.stdout.read(65536)
                continue
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text.startswith("{"):
                try:
                    self._handle_event(json.loads(text))
                except json.JSONDecodeError:
                    pass
            try:
                self.hw = {"cpu_pct": ps.cpu_percent(interval=None),
                           "ram_gb": ps.memory_info().rss / 1e9}
            except psutil.NoSuchProcess:
                pass
        rc = await proc.wait()
        if rc != 0 and self.phase == "running":
            self.error = f"runner exited with code {rc}"
            self.phase = "error"

    async def stop(self) -> dict:
        """Graceful: SIGINT → Runner finalisiert fertige Folds (partial run_end)."""
        if self._proc and self._proc.returncode is None:
            self._proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=20)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        return {"ok": True}


run = TrainingRun()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_training_state.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/server/training.py tests/test_training_state.py requirements.txt
git commit -m "feat(server): TrainingRun State-Machine + Subprozess + psutil-HW"
```

---

## Task 6: Sandbox-Load in der LiveInference-Singleton

**Files:**
- Modify: `src/server/inference.py` (neue Methode `load_sandbox`)
- Test: `tests/test_inference.py` (eine neue Test-Funktion ergänzen)

- [ ] **Step 1: Write the failing test (an bestehende Datei anhängen)**

```python
# tests/test_inference.py  (neue Funktion)
def test_load_sandbox_swaps_model_without_whitelist(tmp_path):
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    import numpy as np
    from src.server.inference import LiveInference

    clf = RandomForestClassifier(n_estimators=3).fit(
        np.random.rand(20, 88), np.random.randint(0, 2, 20))
    p = tmp_path / "model.joblib"
    joblib.dump({"model": clf, "feature_cols": [f"f{i}" for i in range(88)],
                 "sample_rate_hz": 50}, p)
    inf = LiveInference()
    ok = inf.load_sandbox(p)
    assert ok is True
    assert inf.current_model_id() == "sandbox"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inference.py::test_load_sandbox_swaps_model_without_whitelist -v`
Expected: FAIL with `AttributeError: 'LiveInference' object has no attribute 'load_sandbox'`

- [ ] **Step 3: Implement — `load_sandbox` (Muster wie der bestehende Modell-Swap)**

In `src/server/inference.py` eine Methode auf der `LiveInference`-Klasse ergänzen, die den vorhandenen Lade-/Buffer-Clear-Pfad wiederverwendet (dieselbe Mechanik wie `POST /inference/model`, nur ohne Whitelist-Prüfung und mit fester ID `"sandbox"`). Folge dem bestehenden `_load_model`/`set_model`-Muster der Datei:

```python
    def load_sandbox(self, joblib_path) -> bool:
        """Lädt ein beliebiges Run-Joblib temporär (ohne Whitelist).

        Für den Demo-Live-Test eines frisch trainierten Modells, ohne die
        Headline zu überschreiben. Setzt die Modell-ID auf 'sandbox' und
        leert den Rolling-Buffer (sauberer Neustart), exakt wie der reguläre
        Modell-Swap.
        """
        from pathlib import Path
        path = Path(joblib_path)
        if not path.exists():
            return False
        bundle = joblib.load(path)
        self._model = bundle["model"]
        self._feature_cols = bundle["feature_cols"]
        self._model_id = "sandbox"
        self._buffer.clear()
        return True
```

**Hinweis für den Engineer:** Die exakten Attributnamen (`_model`, `_feature_cols`, `_model_id`, `_buffer`) an die in `inference.py` bereits verwendeten anpassen — diese Methode spiegelt nur den vorhandenen Swap. `current_model_id()` ggf. als kleinen Getter ergänzen, falls noch nicht vorhanden.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_inference.py -v`
Expected: PASS (alle inkl. neuer Test)

- [ ] **Step 5: Commit**

```bash
git add src/server/inference.py tests/test_inference.py
git commit -m "feat(inference): load_sandbox für temporären Run-Modell-Test"
```

---

## Task 7: FastAPI-Routes `/training/*`

**Files:**
- Create: `src/server/routes/training.py`
- Modify: `src/server/routes/__init__.py` (Router aggregieren — dem bestehenden Muster der anderen Router folgen)
- Test: `tests/test_training_endpoints.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_training_endpoints.py
from fastapi.testclient import TestClient
from server import app
from src.server import training as T

client = TestClient(app)


def test_models_endpoint_lists_rf():
    r = client.get("/training/models")
    assert r.status_code == 200
    assert any(m["id"] == "rf" for m in r.json())


def test_start_rejects_invalid_pool():
    r = client.post("/training/start", json={"model": "rf", "pool": "nonsense"})
    assert r.status_code == 400


def test_start_409_when_busy(monkeypatch):
    monkeypatch.setattr(T.run, "is_busy", lambda: True)
    r = client.post("/training/start", json={"model": "rf", "pool": "legacy"})
    assert r.status_code == 409


def test_runs_and_promote_smoke(tmp_path, monkeypatch):
    from src.server import training_runs as tr
    monkeypatch.setattr(tr, "RUNS_ROOT", tmp_path)
    d = tr.run_dir("2026-06-16_10-00_rf_auto", root=tmp_path)
    tr.write_config(d, {"model": "rf", "pool": "auto", "mean_acc": 0.87})
    (d / "cv.csv").write_text("held_out,accuracy\nP1,0.9\n")
    r = client.get("/training/runs")
    assert r.status_code == 200 and r.json()[0]["run_id"].endswith("_rf_auto")


def test_promote_unknown_run_404():
    r = client.post("/training/runs/does-not-exist/promote")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_training_endpoints.py -v`
Expected: FAIL (404 auf `/training/models`, Router noch nicht registriert)

- [ ] **Step 3: Implement the router**

```python
# src/server/routes/training.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.training import registry
from .. import training as training_mod
from .. import training_runs
from ..inference import live  # bestehende LiveInference-Singleton

router = APIRouter(prefix="/training", tags=["training"])


class StartBody(BaseModel):
    model: str = "rf"
    pool: str = "legacy"
    by: str = "person"


@router.get("/models")
def models():
    return registry.list_models()


@router.post("/start")
async def start(body: StartBody):
    if not registry.validate(body.model, body.pool):
        raise HTTPException(400, f"invalid model/pool: {body.model}/{body.pool}")
    if training_mod.run.is_busy():
        raise HTTPException(409, "a training run is already in progress")
    return await training_mod.run.start(body.model, body.pool, body.by)


@router.post("/stop")
async def stop():
    return await training_mod.run.stop()


@router.get("/current")
def current():
    return training_mod.run.snapshot()


@router.get("/runs")
def runs():
    return training_runs.list_runs()


@router.post("/runs/{run_id}/promote")
def promote(run_id: str):
    try:
        training_runs.promote(run_id)
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} not found")
    return {"ok": True}


@router.post("/runs/{run_id}/sandbox")
def sandbox(run_id: str):
    path = training_runs.RUNS_ROOT / run_id / "model.joblib"
    if not path.exists():
        raise HTTPException(404, f"no model.joblib for run {run_id}")
    ok = live.load_sandbox(path)
    return {"ok": ok, "model_id": "sandbox"}
```

In `src/server/routes/__init__.py` den neuen Router einbinden — dem bestehenden Muster folgen (Import + `router.include_router(...)`):

```python
from .training import router as training_router
# … bei den anderen include_router-Aufrufen:
router.include_router(training_router)
```

**Hinweis:** Den exакten Aggregations-Stil (`include_router` vs. `APIRouter`-Sammlung) an `routes/__init__.py` anpassen. `live` ist die in `inference.py` exportierte Singleton (Name ggf. anpassen).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_training_endpoints.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/server/routes/training.py src/server/routes/__init__.py tests/test_training_endpoints.py
git commit -m "feat(server): /training/* Endpoints (start/stop/runs/promote/sandbox)"
```

---

## Task 8: Training-Payload + HW in den WS-Tick

**Files:**
- Modify: `src/server/broadcast.py` (im `_status_loop`/`_status_payload`-Pfad)
- Test: `tests/test_training_endpoints.py` (ein WS-Smoke ergänzen)

- [ ] **Step 1: Write the failing test (anhängen)**

```python
# tests/test_training_endpoints.py  (neue Funktion)
def test_status_payload_includes_training_block():
    from src.server.status import _status_payload  # bestehender Builder
    payload = _status_payload()
    assert "training" in payload
    assert "phase" in payload["training"]
```

**Hinweis:** Falls `_status_payload` in `status.py` statt `broadcast.py` lebt, dort einhaken — der WS-Tick ruft ihn ohnehin auf.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_training_endpoints.py::test_status_payload_includes_training_block -v`
Expected: FAIL (`KeyError: 'training'`)

- [ ] **Step 3: Implement — Training-Snapshot in die Payload**

In `src/server/status.py` (bzw. wo `_status_payload()` definiert ist) den Training-Snapshot ergänzen. Beim Dict-Aufbau der Payload:

```python
from .training import run as _training_run
# … beim Zusammenbauen des payload-Dicts:
payload["training"] = _training_run.snapshot()
```

`snapshot()` enthält bereits `hw`, `confusion`, `folds`, `phase` — kein separater psutil-Tick im Loop nötig (der Reader sampelt pro stdout-Zeile).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_training_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server/status.py tests/test_training_endpoints.py
git commit -m "feat(server): Training-Snapshot (inkl. hw/confusion) im WS-Tick"
```

---

## Task 9: „Training"-Tab + leerer View-Slot + Routing

**Files:**
- Modify: `dashboard.html` (Topbar-Tab + `<div data-view="training">`)
- Modify: `static/dashboard.js` (Page-Registry)
- Modify: `static/js/core/router.js` (Tab-Indicator kennt `training`)

- [ ] **Step 1: Tab + Slot in `dashboard.html`**

Im Tab-Strip (nach dem Sessions-Tab) ergänzen — dem bestehenden Markup der anderen Tabs folgen:

```html
<a href="#training" data-tab="training">Training</a>
```

Bei den Page-Slots ergänzen:

```html
<div data-view="training"></div>
```

- [ ] **Step 2: Page-Modul registrieren in `static/dashboard.js`**

Im Page-Registry-Objekt (wo `recording`, `focus`, `sessions` … gemappt sind) `training` ergänzen, analog zu den bestehenden Einträgen (lazy import des Moduls + Partial-Pfad `static/views/training.html`). Dem exakten Muster der bestehenden Registry folgen.

- [ ] **Step 3: Router kennt den Tab**

In `static/js/core/router.js` `training` zur Liste gültiger Hash-Routes/Tab-Indicator-Map hinzufügen (analog `sessions`).

- [ ] **Step 4: Manuelle Verifikation**

Run: `uvicorn server:app --port 8000` und im Browser `http://localhost:8000/#training` öffnen.
Expected: Tab „Training" ist aktiv, leerer Slot wird angezeigt (kein 404 in der Konsole).

- [ ] **Step 5: Commit**

```bash
git add dashboard.html static/dashboard.js static/js/core/router.js
git commit -m "feat(dashboard): Training-Tab + Route + leerer View-Slot"
```

---

## Task 10: View-Partial + CSS (Gerüst der drei Zustände)

**Files:**
- Create: `static/views/training.html`
- Create: `static/css/training.css`
- Modify: `tests/test_dashboard_static.py` (Pfade ergänzen)

- [ ] **Step 1: Failing static-asset test**

In `tests/test_dashboard_static.py` die drei neuen Pfade zur Parametrize-Liste hinzufügen:

```python
    "/static/views/training.html",
    "/static/js/pages/training.js",
    "/static/css/training.css",
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_static.py -v`
Expected: FAIL (404 für die drei neuen Pfade)

- [ ] **Step 3: Write the partial `static/views/training.html`**

Drei Zustands-Container; `training.js` blendet je nach `phase` um. Stylesheet-Link auf `training.css` ergänzen.

```html
<link rel="stylesheet" href="/static/css/training.css">
<div class="trn" id="trn-root">
  <!-- IDLE -->
  <section class="trn-state" data-state="idle">
    <div class="trn-card trn-config">
      <div class="trn-row">
        <label>Modell <span class="trn-q" title="">?</span>
          <select id="trn-model"></select></label>
        <label>Pool <select id="trn-pool">
          <option value="legacy">legacy (N=15)</option>
          <option value="auto">auto</option>
          <option value="modern">modern</option></select></label>
        <label>LOSO-Achse <select id="trn-by">
          <option value="person">by person</option>
          <option value="session">by session</option></select></label>
      </div>
      <button id="trn-start" class="trn-cta">Training starten</button>
    </div>
    <div class="trn-card"><h3>Run-Historie</h3><table id="trn-runs"></table></div>
  </section>

  <!-- RUNNING + DONE teilen das Cockpit -->
  <section class="trn-state" data-state="running done" hidden>
    <div class="trn-titlerow">
      <h2 id="trn-title">RandomForest</h2>
      <span class="trn-pill" id="trn-status"></span>
      <button id="trn-stop" class="trn-ghost">Stop</button>
      <button id="trn-again" class="trn-ghost" hidden>Nochmal</button>
      <button id="trn-promote" class="trn-cta" hidden>Als Headline speichern</button>
      <button id="trn-sandbox" class="trn-ghost" hidden>Live in der Sandbox testen</button>
    </div>
    <div class="trn-card trn-hero">
      <div><b id="trn-acc">–</b><small>accuracy</small></div>
      <div><b id="trn-auc">–</b><small>ROC-AUC</small></div>
      <div><b id="trn-f1">–</b><small>F1</small></div>
      <div class="trn-foldcount"><b id="trn-folds">0 / 0</b><small>Folds</small></div>
      <div class="trn-hw" id="trn-hw"></div>
    </div>
    <div class="trn-card"><div class="trn-pg" id="trn-grid"></div></div>
    <div class="trn-cols">
      <div class="trn-card"><h3>LOSO-Konvergenz</h3><svg id="trn-conv" viewBox="0 0 480 160"></svg></div>
      <div class="trn-card"><h3>Live-Confusion</h3><div id="trn-confusion"></div></div>
    </div>
    <div class="trn-tick" id="trn-log"></div>
    <div class="trn-cols trn-analysis" hidden>
      <div class="trn-card"><h3>ROC</h3><svg id="trn-roc" viewBox="0 0 160 120"></svg></div>
      <div class="trn-card"><h3>Feature-Gruppen</h3><div id="trn-feat"></div></div>
      <div class="trn-card"><h3>Burst-Skalen</h3><svg id="trn-burst" viewBox="0 0 160 120"></svg></div>
    </div>
  </section>

  <aside class="trn-drawer" id="trn-drawer" hidden></aside>
</div>
```

- [ ] **Step 4: Write `static/css/training.css`**

Immersiver Look über die bestehenden `base.css`-Tokens (Light + Dark kommen automatisch). Branding-Slash als Hintergrund. (Vollständige Stilvorlage: die freigegebenen Mockups `light-immersive.html` / `full-lifecycle.html`.)

```css
.trn { position: relative; padding: var(--space-5); }
.trn::before { /* Branding-Slash */
  content: "/"; position: fixed; right: -4vw; top: -10vh;
  font-family: var(--mono); font-style: italic; font-weight: 600;
  font-size: 100vh; line-height: 1; color: var(--accent); opacity: .05;
  pointer-events: none; z-index: 0;
}
.trn-state { position: relative; z-index: 1; }
.trn-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: var(--space-4);
  margin-bottom: var(--space-4); box-shadow: 0 8px 30px oklch(0 0 0 / .12);
}
.trn-hero { display: flex; gap: var(--space-6); align-items: flex-end; }
.trn-hero b { font-size: var(--text-xl); font-weight: 700; }
.trn-hero #trn-acc { color: var(--green); }
.trn-hero small { display: block; color: var(--text3); font-size: var(--text-xs); }
.trn-foldcount #trn-folds { color: var(--accent); }
.trn-hw { margin-left: auto; font-family: var(--mono); font-size: var(--text-xs); color: var(--text3); }
.trn-pg { display: grid; grid-template-columns: repeat(15, 1fr); gap: var(--space-1); }
.trn-tile { border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: var(--space-2); text-align: center; background: var(--surface2); }
.trn-tile .who { font-size: var(--text-xs); color: var(--text3); }
.trn-tile .v { font-weight: 700; }
.trn-tile.good { border-color: color-mix(in oklch, var(--green) 45%, var(--border)); }
.trn-tile.warn { border-color: color-mix(in oklch, var(--yellow) 50%, var(--border)); }
.trn-tile.live { border-color: var(--accent); box-shadow: 0 0 16px color-mix(in oklch, var(--accent) 35%, transparent); }
.trn-cols { display: grid; grid-template-columns: 1.8fr 1fr; gap: var(--space-4); }
.trn-cta { background: var(--accent); color: var(--text-on-dark); border: none;
  border-radius: var(--radius-sm); padding: var(--space-3) var(--space-5); font-weight: 600; cursor: pointer; }
.trn-ghost { background: var(--surface2); color: var(--text); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: var(--space-2) var(--space-4); cursor: pointer; }
.trn-pill { display: inline-flex; align-items: center; gap: var(--space-2);
  border: 1px solid var(--border); border-radius: var(--radius-pill); padding: 4px 12px; font-size: var(--text-sm); }
.trn-tick { font-family: var(--mono); font-size: var(--text-xs); color: var(--text2);
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3); white-space: nowrap; overflow: hidden; }
.trn-drawer { position: fixed; right: 0; top: 0; bottom: 0; width: 420px; z-index: 50;
  background: var(--surface); border-left: 1px solid var(--border); padding: var(--space-5);
  overflow: auto; box-shadow: -20px 0 60px oklch(0 0 0 / .4); }
.trn-confusion-grid { display: grid; grid-template-columns: auto 1fr 1fr; gap: 4px; }
.trn-confusion-cell { padding: var(--space-3); text-align: center; border-radius: var(--radius-sm); }
.trn-confusion-cell.diag { background: color-mix(in oklch, var(--green) 20%, transparent); }
.trn-confusion-cell.off  { background: color-mix(in oklch, var(--red) 18%, transparent); }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_dashboard_static.py -v`
Expected: PASS (alle Asset-Pfade 200) — `training.js` ist noch leer/Stub; eine leere Datei reicht für 200, wird in Task 11 gefüllt. Lege jetzt eine minimale `static/js/pages/training.js` mit leerem Contract an, damit der Test grün wird:

```javascript
export function mount() {}
export function onStatus() {}
export function onShow() {}
export function onHide() {}
```

- [ ] **Step 6: Commit**

```bash
git add static/views/training.html static/css/training.css static/js/pages/training.js tests/test_dashboard_static.py
git commit -m "feat(dashboard): Training-View-Gerüst + CSS + Page-Stub"
```

---

## Task 11: Page-Modul — Idle/Start + Run-Historie

**Files:**
- Modify: `static/js/pages/training.js`

- [ ] **Step 1: `mount` — Config laden, Start verdrahten, Historie rendern**

```javascript
// static/js/pages/training.js
import { api } from "/static/js/core/api.js";   // bestehender fetch-Helper

let root = null;

export function mount(container) {
  root = container;
  _loadModels();
  _loadRuns();
  root.querySelector("#trn-start").addEventListener("click", _start);
  root.querySelector("#trn-stop").addEventListener("click",
    () => api.post("/training/stop"));
  root.querySelector("#trn-again").addEventListener("click",
    () => _setState("idle"));
  root.querySelector("#trn-promote").addEventListener("click", _promote);
  root.querySelector("#trn-sandbox").addEventListener("click", _sandbox);
}

async function _loadModels() {
  const models = await api.get("/training/models");
  const sel = root.querySelector("#trn-model");
  sel.innerHTML = "";
  for (const m of models) {
    const o = document.createElement("option");
    o.value = m.id; o.textContent = `${m.label} (${m.speed})`;
    o.title = m.description;
    sel.appendChild(o);
  }
}

async function _loadRuns() {
  const runs = await api.get("/training/runs");
  const t = root.querySelector("#trn-runs");
  t.innerHTML = "<tr><th>Run</th><th>Modell</th><th>Pool</th><th>acc</th><th></th></tr>";
  for (const r of runs) {
    const tr = document.createElement("tr");
    const acc = (r.mean_acc != null) ? r.mean_acc.toFixed(3) : "–";
    tr.innerHTML = `<td>${r.run_id}</td><td>${r.model}</td><td>${r.pool}</td><td>${acc}</td>`;
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "trn-ghost"; btn.textContent = "als Headline setzen";
    btn.addEventListener("click", () => api.post(`/training/runs/${r.run_id}/promote`));
    td.appendChild(btn); tr.appendChild(td); t.appendChild(tr);
  }
}

async function _start() {
  const body = {
    model: root.querySelector("#trn-model").value,
    pool: root.querySelector("#trn-pool").value,
    by: root.querySelector("#trn-by").value,
  };
  const res = await api.post("/training/start", body);
  if (res && res.run_id) { _currentRunId = res.run_id; _setState("running"); }
}

let _currentRunId = null;

async function _promote() {
  if (_currentRunId) await api.post(`/training/runs/${_currentRunId}/promote`);
}
async function _sandbox() {
  if (_currentRunId) await api.post(`/training/runs/${_currentRunId}/sandbox`);
}

function _setState(phase) {
  for (const s of root.querySelectorAll(".trn-state")) {
    const owns = (s.dataset.state || "").split(" ").includes(phase);
    s.hidden = !owns;
  }
}

export function onShow() { _loadRuns(); }
export function onHide() {}
```

**Hinweis:** Den exakten Import-/Aufruf-Stil von `api.js` (z. B. `api.get`/`api.post` vs. benannte Funktionen) an die bestehende Datei anpassen.

- [ ] **Step 2: Manuelle Verifikation**

Server starten, `#training` öffnen → Modell-Dropdown zeigt „RandomForest (fast)", Run-Historie lädt, „Training starten" wechselt in den Cockpit-Zustand.

- [ ] **Step 3: Commit**

```bash
git add static/js/pages/training.js
git commit -m "feat(dashboard): Training idle-State, Start, Run-Historie"
```

---

## Task 12: Page-Modul — Live-Cockpit (onStatus)

**Files:**
- Modify: `static/js/pages/training.js`

- [ ] **Step 1: `onStatus` — Hero/Grid/Konvergenz/Confusion/HW/Log live**

```javascript
// in static/js/pages/training.js ergänzen
export function onStatus(payload) {
  const t = payload && payload.training;
  if (!t || t.phase === "idle") return;
  _setState(t.phase === "done" ? "done" : "running");

  root.querySelector("#trn-title").textContent =
    `${t.model} · ${t.pool}`;
  root.querySelector("#trn-status").textContent =
    t.phase === "done" ? (t.partial ? `partial ${t.summary.n_done}/${t.n}` : "fertig")
                       : `läuft · Fold ${t.fold}/${t.n}`;
  root.querySelector("#trn-folds").textContent = `${t.fold} / ${t.n}`;

  const s = t.summary || {};
  const live = t.folds.length
    ? t.folds.reduce((a, f) => a + f.acc, 0) / t.folds.length : null;
  _setNum("#trn-acc", t.phase === "done" ? s.mean_acc : live);
  _setNum("#trn-auc", t.phase === "done" ? s.auc :
    (t.folds.length ? t.folds.reduce((a, f) => a + f.auc, 0) / t.folds.length : null));
  _setNum("#trn-f1", t.phase === "done" ? s.f1 : null);

  _renderGrid(t);
  _renderConfusion(t.confusion);
  _renderConvergence(t.folds);
  root.querySelector("#trn-hw").textContent =
    `CPU ${Math.round(t.hw.cpu_pct)}% · RAM ${t.hw.ram_gb.toFixed(1)} GB`;
  root.querySelector("#trn-log").textContent =
    "/ " + (t.log || []).slice(-1)[0] || "";

  const done = t.phase === "done";
  root.querySelector("#trn-stop").hidden = done;
  root.querySelector("#trn-again").hidden = !done;
  root.querySelector("#trn-promote").hidden = !done;
  root.querySelector("#trn-sandbox").hidden = !done;
  root.querySelector(".trn-analysis").hidden = !done;
}

function _setNum(sel, v) {
  root.querySelector(sel).textContent = (v == null) ? "–" : v.toFixed(3);
}

function _renderGrid(t) {
  const g = root.querySelector("#trn-grid");
  g.innerHTML = "";
  for (const f of t.folds) {
    const cls = f.acc >= 0.87 ? "good" : (f.acc >= 0.83 ? "warn" : "warn");
    const d = document.createElement("div");
    d.className = `trn-tile ${cls}`;
    d.innerHTML = `<div class="who">${f.person}</div><div class="v">${f.acc.toFixed(3)}</div>`;
    d.addEventListener("click", () => _openDrawer(f));
    g.appendChild(d);
  }
}

function _renderConfusion(c) {
  const el = root.querySelector("#trn-confusion");
  el.innerHTML = `<div class="trn-confusion-grid">
    <div></div><div>pred 0</div><div>pred 1</div>
    <div>true 0</div><div class="trn-confusion-cell diag">${c.tn}</div><div class="trn-confusion-cell off">${c.fp}</div>
    <div>true 1</div><div class="trn-confusion-cell off">${c.fn}</div><div class="trn-confusion-cell diag">${c.tp}</div>
  </div>`;
}

function _renderConvergence(folds) {
  const svg = root.querySelector("#trn-conv");
  if (!folds.length) { svg.innerHTML = ""; return; }
  const w = 480, h = 160, pad = 30;
  const pts = folds.map((f, i) => {
    const x = pad + (folds.length === 1 ? 0 : i * (w - 2 * pad) / (folds.length - 1));
    const y = h - pad - (f.auc - 0.5) / 0.5 * (h - 2 * pad);
    return `${x},${y}`;
  }).join(" ");
  svg.innerHTML =
    `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>` +
    folds.map((f, i) => {
      const x = pad + (folds.length === 1 ? 0 : i * (w - 2 * pad) / (folds.length - 1));
      const y = h - pad - (f.auc - 0.5) / 0.5 * (h - 2 * pad);
      const col = f.acc >= 0.87 ? "var(--green)" : "var(--yellow)";
      return `<circle cx="${x}" cy="${y}" r="3.5" fill="${col}"/>`;
    }).join("");
}

function _openDrawer(fold) {
  const d = root.querySelector("#trn-drawer");
  d.hidden = false;
  d.innerHTML = `<button class="trn-ghost" id="trn-drawer-x">schließen</button>
    <h2>${fold.person}</h2>
    <p>accuracy ${fold.acc.toFixed(3)} · AUC ${fold.auc.toFixed(3)} · F1 ${(fold.f1||0).toFixed(3)}</p>
    <p class="trn-muted">Per-Task-Aufschlüsselung aus Markern: post-MVP.</p>`;
  d.querySelector("#trn-drawer-x").addEventListener("click", () => { d.hidden = true; });
}
```

**Hinweis:** `onStatus` wird vom bestehenden `setActivePageDispatcher`/`_activePageDispatch`-Pfad nur für die aktive Seite aufgerufen — kein zusätzliches WS-Setup nötig.

- [ ] **Step 2: Manuelle End-to-End-Verifikation**

Server starten, `#training` öffnen, „Training starten" (Pool legacy). Erwartung: Folds poppen einzeln rein, Hero-Zahlen + Konvergenz + Confusion zählen hoch, HW-Zeile aktualisiert, nach dem letzten Fold erscheint die Analyse-Sektion + Promote/Sandbox-Buttons.

- [ ] **Step 3: Graceful-Stop-Verifikation**

Während eines Laufs „Stop" drücken. Erwartung: Lauf endet nach dem laufenden Fold, Status zeigt `partial n/N`, die fertigen Folds bleiben sichtbar, Analyse-Sektion erscheint.

- [ ] **Step 4: Commit**

```bash
git add static/js/pages/training.js
git commit -m "feat(dashboard): Live-Cockpit (Hero, Grid, Konvergenz, Confusion, HW, Drill-in)"
```

---

## Task 13: Done-State-Analyse (ROC, Feature-Gruppen, Burst) + Doku

**Files:**
- Modify: `static/js/pages/training.js` (ROC/Feature/Burst aus dem Run laden)
- Modify: `src/server/routes/training.py` (`GET /training/runs/{id}` liefert cv.csv + feature-importances)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Endpoint liefert Run-Detail (cv-Zeilen + Feature-Importance)**

In `src/server/routes/training.py`:

```python
import pandas as pd, joblib

@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    d = training_runs.RUNS_ROOT / run_id
    if not (d / "cv.csv").exists():
        raise HTTPException(404, "run not found")
    cv = pd.read_csv(d / "cv.csv").to_dict(orient="records")
    feat = []
    mp = d / "model.joblib"
    if mp.exists():
        b = joblib.load(mp)
        clf, cols = b["model"], b["feature_cols"]
        imp = getattr(clf, "feature_importances_", None)
        if imp is not None:
            feat = sorted(({"name": c, "imp": float(i)}
                           for c, i in zip(cols, imp)),
                          key=lambda r: -r["imp"])[:12]
    return {"cv": cv, "feature_importance": feat}
```

- [ ] **Step 2: Done-State holt das Detail + rendert ROC/Feature/Burst**

In `training.js` `onStatus` beim Übergang auf `done` einmalig `GET /training/runs/{id}` holen und die drei SVG/Listen füllen (Burst aus den `acc_5s/acc_10s/acc_30s`-Spalten der cv-Zeilen, Feature-Gruppen aus `feature_importance` auf die 6 Gruppen-Präfixe aggregiert). Guard gegen Mehrfach-Fetch über ein `_detailLoaded`-Flag.

```javascript
let _detailLoaded = false;
async function _loadDetail(runId) {
  if (_detailLoaded || !runId) return;
  _detailLoaded = true;
  const d = await api.get(`/training/runs/${runId}`);
  _renderFeatureGroups(d.feature_importance);
  _renderBurst(d.cv);
}
```

`_renderFeatureGroups` mappt jeden Feature-Namen über sein Präfix auf eine der sechs Gruppen (time_stats/spectral/zcr/jerk/magnitude/correlation), summiert die Importances und zeichnet horizontale Balken. `_renderBurst` mittelt `acc_5s/acc_10s/acc_30s` über die cv-Zeilen und zeichnet die 1→30s-Kurve. (`_detailLoaded` beim Start eines neuen Laufs zurücksetzen.)

- [ ] **Step 3: Manuelle Verifikation**

Nach einem vollständigen Lauf: ROC-/Feature-Gruppen-/Burst-Karten gefüllt; „Als Headline speichern" schreibt `models/loso_cv.csv` + `rf_all.joblib` (per `git status` prüfen, dass nur diese sich ändern).

- [ ] **Step 4: CLAUDE.md kurz dokumentieren**

Im Architektur-Abschnitt einen Satz + die neuen Endpoints/Dateien notieren (Training-Cockpit: `routes/training.py`, `training.py`, `training_runs.py`, `events.py`, `registry.py`; `models/runs/{id}/`; nicht-destruktiv, Promotion-only).

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -q`
Expected: alle grün (bestehende 346 + neue Tests)

- [ ] **Step 6: Commit**

```bash
git add static/js/pages/training.js src/server/routes/training.py CLAUDE.md
git commit -m "feat(dashboard): Done-State-Analyse (ROC/Feature-Gruppen/Burst) + Doku"
```

---

## Self-Review

**Spec-Coverage (Demo-MVP-Teil):**
- Launcher/Job-Registry → Task 2. Ansatz B (Events) → Task 1+4. State-Machine/Subprozess → Task 5. Endpoints → Task 7. WS → Task 8.
- Drei Zustände → Task 10+11+12. Per-Person-Grid + Drill-in → Task 12. Konvergenz/Hero/Log → Task 12. Done-Analyse (Confusion/ROC/Feature/Burst) → Task 12+13.
- Nicht-destruktive Runs + Promotion → Task 3+7. Demo-Tier: Graceful Stop → Task 4+5+12; Live-Confusion → Task 4+12; HW-Sparkline → Task 5+8+12; Sandbox-Inference → Task 6+7+11.
- Branding/Light+Dark → Task 10 (oklch-Tokens + Slash). Tooltips (Basis: `title` aus Registry-`description`) → Task 11.
- **Bewusst post-MVP (kein Task):** Deep/harnet/klassische Runner, neue Modelle, SHAP, Replay, Auto-Narrativ, Quaternion-Capture, Task-Fehler-Card, Wilcoxon-Vergleich-Drawer, „Fehler nach Task". In der Registry/Event-Struktur als Erweiterungspunkt vorbereitet.

**Platzhalter-Scan:** Keine „TODO/TBD". Drei `Hinweis`-Blöcke verweisen bewusst auf bestehende Projekt-Muster (api.js-Stil, routes/__init__-Aggregation, inference-Attributnamen), die der Engineer 1:1 spiegelt — kein erfundenes API.

**Typ-Konsistenz:** Event-Felder identisch über Task 1/4/5/12 (`fold_end`: idx/person/n/acc/auc/f1/burst/confusion{tn,fp,fn,tp}; `run_end`: partial/n_done/mean_acc/std_acc/auc/f1/burst/out_dir). `snapshot()`-Keys (phase/model/pool/fold/n/folds/confusion/summary/hw/log) deckungsgleich mit dem Frontend-Zugriff in Task 12. Run-Store-Namen (`new_run_id`/`run_dir`/`write_config`/`list_runs`/`promote`) konsistent über Task 3/5/7.

---

## Execution Handoff

Plan complete and saved. Offene manuelle Schritte (Geräte/Server) sind als „Manuelle Verifikation" markiert, weil das Projekt für Frontend + Live-Pfad keine automatisierten Tests hat (nur den Static-200-Smoke).
