# Engagement — Schreibzeit-Anteil pro Aufgabe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pro Schreib-Aufgabe und Proband den tatsächlichen Schreibzeit-Anteil auswerten — ein Engagement-Proxy als Auswertungs-Schicht über den bestehenden LOSO-Vorhersagen.

**Architecture:** Reines Post-Processing, kein Modell-Training. Ein neues Modul `src/evaluation/engagement.py` liest `models/loso_oof.csv` + die `markers`-CSVs, ordnet jedes 1-s-Fenster über `t_center_ms` einem Task-Block zu und aggregiert pro `(Session, Task)`. Die Per-Block-Prozent-Formel wird als Helfer `block_percentages()` aus `regression.py` geteilt, nicht doppelt implementiert.

**Tech Stack:** Python, pandas, numpy, matplotlib, pytest.

**Spec:** `docs/specs/2026-05-21-engagement-design.md`
**Branch:** `feature/engagement` (existiert bereits, Spec ist dort committet)

---

## File Structure

- **Modify** `src/evaluation/regression.py` — `block_percentages()`-Helfer extrahieren; `aggregate()` ruft ihn statt der Inline-Formel. Verhalten unverändert.
- **Create** `src/evaluation/engagement.py` — das neue Auswertungs-Modul.
- **Modify** `tests/test_regression_eval.py` — ein Test für `block_percentages()` ergänzen; bestehende Tests bleiben unverändert.
- **Create** `tests/test_engagement_eval.py` — Smoke-Tests für das neue Modul.
- **Create** `reports/engagement.md` — Fortschritts-/Vorgehens-Log.
- **Modify** `CLAUDE.md` — Modul + CLI-Befehl dokumentieren.

---

## Task 1: `block_percentages()`-Helfer aus regression.py extrahieren

Die Umrechnung „Block von OOF-Fenstern → Prozentzahlen" wird ein benannter Helfer, damit `engagement.py` ihn importieren kann statt ihn neu zu schreiben. `regression.aggregate()` ruft danach den Helfer; sein Output ist byte-identisch zu vorher.

**Files:**
- Modify: `src/evaluation/regression.py`
- Test: `tests/test_regression_eval.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_regression_eval.py` ans Dateiende anhängen:

```python
def test_block_percentages_binary_proba_and_closed_label():
    # 6 Fenster: 4 mit proba 0.8 (>=0.5), 2 mit 0.2; labels 5×1, 1×0
    group = pd.DataFrame({
        "proba_cal": [0.8, 0.8, 0.8, 0.8, 0.2, 0.2],
        "label": [1, 1, 1, 1, 1, 0],
    })
    p = reg.block_percentages(group)

    assert p["n_windows"] == 6
    # binärer Schätzer: 4 von 6 Fenstern über 0.5
    assert p["pred_pct"] == pytest.approx(4 / 6 * 100.0)
    # Proba-Mittel: (4*0.8 + 2*0.2) / 6
    assert p["pred_pct_proba"] == pytest.approx((4 * 0.8 + 2 * 0.2) / 6 * 100.0)
    # closed label: 5 von 6
    assert p["true_pct"] == pytest.approx(5 / 6 * 100.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_regression_eval.py::test_block_percentages_binary_proba_and_closed_label -v`
Expected: FAIL — `AttributeError: module 'src.evaluation.regression' has no attribute 'block_percentages'`

- [ ] **Step 3: Add the helper to regression.py**

In `src/evaluation/regression.py`, direkt **vor** `def aggregate(` einfügen:

```python
def block_percentages(group: pd.DataFrame) -> dict[str, float]:
    """Per-Block-Prozente aus den OOF-Fenstern eines Blocks.

    Geteilt von ``regression.py`` (Zeitblöcke) und ``engagement.py``
    (Task-Blöcke), damit die Definition des binären Schätzers an einer
    Stelle lebt. ``pred_pct`` = binärer Schätzer
    ``mean(proba_cal >= 0.5)``; ``pred_pct_proba`` = Proba-Mittel
    (Vergleich); ``true_pct`` = Mittel der geschlossenen Labels.
    Alle Werte in Prozent.
    """
    return {
        "n_windows": int(len(group)),
        "pred_pct": float((group["proba_cal"] >= 0.5).mean()) * 100.0,
        "pred_pct_proba": float(group["proba_cal"].mean()) * 100.0,
        "true_pct": float(group["label"].mean()) * 100.0,
    }
```

- [ ] **Step 4: Refactor `aggregate()` to use the helper**

In `src/evaluation/regression.py`, in `aggregate()` den `rows.append({...})`-Block ersetzen.

Vorher:

```python
            rows.append({
                "session_id": sid,
                "person_id": bg["person_id"].iat[0],
                "block_start_ms": block_start,
                "n_windows": int(len(bg)),
                "pred_pct": float((bg["proba_cal"] >= 0.5).mean()) * 100.0,
                "pred_pct_proba": float(bg["proba_cal"].mean()) * 100.0,
                "truth_closed_pct": float(bg["label"].mean()) * 100.0,
                "truth_pen_pct": _pen_pct(merged, block_start, block_end, anchor),
            })
```

Nachher:

```python
            pcts = block_percentages(bg)
            rows.append({
                "session_id": sid,
                "person_id": bg["person_id"].iat[0],
                "block_start_ms": block_start,
                "n_windows": pcts["n_windows"],
                "pred_pct": pcts["pred_pct"],
                "pred_pct_proba": pcts["pred_pct_proba"],
                "truth_closed_pct": pcts["true_pct"],
                "truth_pen_pct": _pen_pct(merged, block_start, block_end, anchor),
            })
```

- [ ] **Step 5: Run the full regression test file**

Run: `python -m pytest tests/test_regression_eval.py -v`
Expected: PASS — alle bisherigen Tests grün plus der neue. Beweis, dass die Extraktion das Verhalten nicht ändert.

- [ ] **Step 6: Commit**

```bash
git add src/evaluation/regression.py tests/test_regression_eval.py
git commit -m "refactor(evaluation): extract block_percentages() helper

Per-Block-Prozent-Formel wird benannter Helfer, damit engagement.py
sie teilen kann statt sie neu zu implementieren. aggregate() ruft den
Helfer; Output unverändert (bestehende Tests grün).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Modul-Gerüst + `task_timeline()`

`engagement.py` wird angelegt mit Pfad-Konstanten und der ersten Funktion: aus einer Marker-CSV die Task-Blöcke einer Session rekonstruieren.

**Files:**
- Create: `src/evaluation/engagement.py`
- Create: `tests/test_engagement_eval.py`

- [ ] **Step 1: Write the failing test**

`tests/test_engagement_eval.py` neu anlegen:

```python
"""Smoke tests für die Engagement-Auswertung (Schreibzeit-Anteil/Task).

Trainings-frei: OOF-CSV und markers.csv werden als synthetische
Fixtures gemockt.
"""

import numpy as np
import pandas as pd
import pytest

from src.evaluation import engagement as eng


def _write_markers(path, rows):
    """Synthetische markers.csv. rows: Liste von Tupeln
    (timestamp_ms, event, task_id, task_name, task_index, task_category).
    """
    pd.DataFrame(
        rows,
        columns=["timestamp_ms", "event", "task_id", "task_name",
                 "task_index", "task_category"],
    ).assign(protocol_id="v1").to_csv(path, index=False)


def _oof(session, person, t_center_ms, label, proba_cal):
    """Synthetische OOF-Zeilen für eine Session."""
    return pd.DataFrame({
        "session_id": session,
        "person_id": person,
        "t_center_ms": np.asarray(t_center_ms, dtype=float),
        "label": np.asarray(label, dtype=int),
        "proba_raw": np.asarray(proba_cal, dtype=float),
        "proba_cal": np.asarray(proba_cal, dtype=float),
    })


def test_task_timeline_pairs_start_and_end(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)
    _write_markers(tmp_path / "S001_markers.csv", [
        (1000, "study_start", "", "", "", ""),
        (1100, "task_start", "abschreiben", "Text", 1, "writing"),
        (5100, "task_end",   "abschreiben", "Text", 1, "writing"),
        (5200, "task_start", "pause", "Pause", 2, "idle"),
        (7200, "task_end",   "pause", "Pause", 2, "idle"),
        (7300, "study_end",  "", "", "", ""),
    ])

    tl = eng.task_timeline("S001")

    assert list(tl["task_index"]) == [1, 2]
    assert list(tl["task_id"]) == ["abschreiben", "pause"]
    assert list(tl["task_category"]) == ["writing", "idle"]
    assert tl.loc[0, "start_ms"] == 1100.0
    assert tl.loc[0, "end_ms"] == 5100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engagement_eval.py::test_task_timeline_pairs_start_and_end -v`
Expected: FAIL — `ImportError` / `ModuleNotFoundError` für `src.evaluation.engagement`.

- [ ] **Step 3: Create `engagement.py` with constants and `task_timeline()`**

`src/evaluation/engagement.py` neu anlegen:

```python
"""Engagement — Schreibzeit-Anteil pro Aufgabe (Stufe 2, Prio 2).

Reines Post-Processing über ``models/loso_oof.csv`` + den
Study-Mode-``markers``-CSVs — kein Modell-Training. Ordnet jedes
1-s-Vorhersage-Fenster über ``t_center_ms`` einem Task-Block zu und
aggregiert pro (Session, Aufgabe) den Schreibzeit-Anteil.

Der gemessene Wert ist ein **Engagement-Proxy**, ausdrücklich kein
Aufmerksamkeits-Detektor: Schreibzeit ≠ Aufmerksamkeit.

CLI
---
::

    python -m src.evaluation.engagement                       # Defaults
    python -m src.evaluation.engagement --oof PATH
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.regression import block_percentages, load_oof

ROOT = Path(__file__).parents[2]
MARKERS_DIR = ROOT / "data" / "raw" / "markers"
MODEL_DIR = ROOT / "models"
FIG_DIR = ROOT / "reports" / "figures"

# Spaltenreihenfolge der Schreib-Tasks im Heatmap-Grid (Protokoll v1).
WRITING_TASKS = ["abschreiben", "free_writing", "math"]

TIMELINE_COLS = ["task_index", "task_id", "task_name", "task_category",
                 "start_ms", "end_ms"]


def task_timeline(session_id: str) -> pd.DataFrame:
    """Task-Blöcke einer Session aus ihrer Marker-CSV.

    Paart jedes ``task_start`` mit dem ``task_end`` gleichen
    ``task_index``. Rückgabe: eine Zeile pro Block (Spalten
    ``TIMELINE_COLS``), nach ``start_ms`` sortiert. Ein ``task_start``
    ohne passendes ``task_end`` (abgebrochene Session) wird verworfen.
    Fehlt die Marker-CSV, kommt ein leerer DataFrame zurück.
    """
    path = MARKERS_DIR / f"{session_id}_markers.csv"
    if not path.exists():
        return pd.DataFrame(columns=TIMELINE_COLS)

    m = pd.read_csv(path)
    ends = (m[m["event"] == "task_end"]
            .drop_duplicates("task_index", keep="first")
            .set_index("task_index")["timestamp_ms"])
    rows: list[dict] = []
    for _, s in m[m["event"] == "task_start"].iterrows():
        idx = s["task_index"]
        if idx not in ends.index:
            continue  # Why: task_start ohne task_end = abgebrochener Block.
        rows.append({
            "task_index": int(idx),
            "task_id": s["task_id"],
            "task_name": s["task_name"],
            "task_category": s["task_category"],
            "start_ms": float(s["timestamp_ms"]),
            "end_ms": float(ends.loc[idx]),
        })
    return pd.DataFrame(rows, columns=TIMELINE_COLS).sort_values(
        "start_ms").reset_index(drop=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oof", default=str(MODEL_DIR / "loso_oof.csv"),
                   help="Pfad zur OOF-CSV (default: models/loso_oof.csv).")
    p.add_argument("--out", default=str(MODEL_DIR / "engagement_metrics.csv"),
                   help="Ziel-CSV für die Engagement-Metriken.")
    return p.parse_args()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engagement_eval.py::test_task_timeline_pairs_start_and_end -v`
Expected: PASS

- [ ] **Step 5: Add tests for the two edge cases**

In `tests/test_engagement_eval.py` anhängen:

```python
def test_task_timeline_drops_unpaired_start(tmp_path, monkeypatch):
    # abgebrochene Session: task_start ohne task_end
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)
    _write_markers(tmp_path / "S002_markers.csv", [
        (1000, "study_start", "", "", "", ""),
        (1100, "task_start", "math", "Mathe", 1, "writing"),
        (3000, "abort", "", "", "", ""),
    ])

    tl = eng.task_timeline("S002")

    assert tl.empty
    assert list(tl.columns) == eng.TIMELINE_COLS


def test_task_timeline_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)

    tl = eng.task_timeline("S999")

    assert tl.empty
    assert list(tl.columns) == eng.TIMELINE_COLS
```

- [ ] **Step 6: Run the engagement test file**

Run: `python -m pytest tests/test_engagement_eval.py -v`
Expected: PASS — 3 Tests grün.

- [ ] **Step 7: Commit**

```bash
git add src/evaluation/engagement.py tests/test_engagement_eval.py
git commit -m "feat(evaluation): engagement module skeleton + task_timeline

task_timeline() rekonstruiert die Task-Blöcke einer Session aus ihrer
markers.csv (task_start/task_end paaren). Unpaarige Starts und
fehlende Dateien sicher behandelt.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `assign_tasks()` — Fenster den Task-Blöcken zuordnen

Jedes OOF-Fenster bekommt über sein `t_center_ms` die Task-Spalten des Blocks, in dessen `[start_ms, end_ms)`-Intervall es liegt. Fenster in Übergängen → `NaN`.

**Files:**
- Modify: `src/evaluation/engagement.py`
- Test: `tests/test_engagement_eval.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_engagement_eval.py` anhängen:

```python
def _timeline_two_blocks():
    """Zwei Blöcke: writing [1000,2000), idle [2000,3000)."""
    return pd.DataFrame({
        "task_index": [1, 2],
        "task_id": ["abschreiben", "pause"],
        "task_name": ["Text", "Pause"],
        "task_category": ["writing", "idle"],
        "start_ms": [1000.0, 2000.0],
        "end_ms": [2000.0, 3000.0],
    })


def test_assign_tasks_maps_windows_into_blocks():
    # Fenster bei 1500 (Block 1), 2500 (Block 2), 3500 (Übergang/außerhalb)
    oof = _oof("S001", "P01", [1500.0, 2500.0, 3500.0], [1, 0, 1],
               [0.9, 0.1, 0.5])

    out = eng.assign_tasks(oof, _timeline_two_blocks())

    assert out["task_index"].tolist()[:2] == [1.0, 2.0]
    assert pd.isna(out["task_index"].iloc[2])  # Fenster außerhalb → NaN
    assert out["task_category"].tolist()[:2] == ["writing", "idle"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engagement_eval.py::test_assign_tasks_maps_windows_into_blocks -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'assign_tasks'`

- [ ] **Step 3: Implement `assign_tasks()`**

In `src/evaluation/engagement.py`, nach `task_timeline()` einfügen:

```python
def assign_tasks(oof_session: pd.DataFrame,
                 timeline: pd.DataFrame) -> pd.DataFrame:
    """Ordnet jedem OOF-Fenster einer Session seinen Task-Block zu.

    Fügt die Spalten task_index/task_id/task_name/task_category hinzu.
    Fenster, deren ``t_center_ms`` in keinem ``[start_ms, end_ms)``
    liegt (Vor-Task-Countdown, Übergänge), bekommen ``NaN``.
    """
    out = oof_session.copy()
    for col in ("task_index", "task_id", "task_name", "task_category"):
        out[col] = np.nan
    t = out["t_center_ms"]
    for _, blk in timeline.iterrows():
        mask = (t >= blk["start_ms"]) & (t < blk["end_ms"])
        out.loc[mask, "task_index"] = blk["task_index"]
        out.loc[mask, "task_id"] = blk["task_id"]
        out.loc[mask, "task_name"] = blk["task_name"]
        out.loc[mask, "task_category"] = blk["task_category"]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engagement_eval.py::test_assign_tasks_maps_windows_into_blocks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/engagement.py tests/test_engagement_eval.py
git commit -m "feat(evaluation): assign_tasks() maps windows to task blocks

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `engagement_per_task()` — Aggregation pro (Session, Task)

Pro Task-Block eine Zeile: `true_pct`/`pred_pct` über den geteilten `block_percentages()`-Helfer, plus `error_pp`. Sessions ohne Marker werden übersprungen.

**Files:**
- Modify: `src/evaluation/engagement.py`
- Test: `tests/test_engagement_eval.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_engagement_eval.py` anhängen:

```python
def test_engagement_per_task_aggregates_per_block():
    # Block 1 (writing): 4 Fenster, alle label 1, proba 0.9 → 100/100
    # Block 2 (idle):    4 Fenster, alle label 0, proba 0.1 → 0/0
    oof = _oof("S001", "P01",
               [1200.0, 1400.0, 1600.0, 1800.0,
                2200.0, 2400.0, 2600.0, 2800.0],
               [1, 1, 1, 1, 0, 0, 0, 0],
               [0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1])

    out = eng.engagement_per_task(
        oof, timeline_loader=lambda s: _timeline_two_blocks())

    assert len(out) == 2
    assert list(out.columns) == [
        "session_id", "person_id", "task_index", "task_id", "task_name",
        "task_category", "n_windows", "true_pct", "pred_pct", "error_pp"]
    w = out[out["task_category"] == "writing"].iloc[0]
    assert w["true_pct"] == pytest.approx(100.0)
    assert w["pred_pct"] == pytest.approx(100.0)
    assert w["error_pp"] == pytest.approx(0.0)
    assert w["n_windows"] == 4
    idle = out[out["task_category"] == "idle"].iloc[0]
    assert idle["true_pct"] == pytest.approx(0.0)


def test_engagement_per_task_skips_session_without_markers():
    oof = _oof("S001", "P01", [1500.0, 2500.0], [1, 0], [0.9, 0.1])

    out = eng.engagement_per_task(
        oof, timeline_loader=lambda s: pd.DataFrame(columns=eng.TIMELINE_COLS))

    assert out.empty
    assert list(out.columns) == [
        "session_id", "person_id", "task_index", "task_id", "task_name",
        "task_category", "n_windows", "true_pct", "pred_pct", "error_pp"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engagement_eval.py::test_engagement_per_task_aggregates_per_block -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'engagement_per_task'`

- [ ] **Step 3: Implement `engagement_per_task()`**

In `src/evaluation/engagement.py`, nach `assign_tasks()` einfügen:

```python
ENGAGEMENT_COLS = ["session_id", "person_id", "task_index", "task_id",
                   "task_name", "task_category", "n_windows", "true_pct",
                   "pred_pct", "error_pp"]


def engagement_per_task(oof_df: pd.DataFrame,
                        timeline_loader=task_timeline) -> pd.DataFrame:
    """Eine Zeile pro (Session, Task-Block): Schreibzeit-Anteil.

    ``true_pct``/``pred_pct`` über den mit ``regression.py`` geteilten
    ``block_percentages()``. Sessions ohne Marker-CSV (leere Timeline)
    werden mit einer Warnung übersprungen. Fenster ohne Task-Zuordnung
    (Übergänge) zählen pro Session als Diagnose-Ausgabe.
    """
    rows: list[dict] = []
    for sid, g in oof_df.groupby("session_id", sort=False):
        timeline = timeline_loader(sid)
        if timeline.empty:
            print(f"  ⚠ {sid}: keine Marker-CSV — übersprungen")
            continue
        assigned = assign_tasks(g, timeline)
        n_unassigned = int(assigned["task_index"].isna().sum())
        if n_unassigned:
            print(f"  {sid}: {n_unassigned}/{len(assigned)} Fenster "
                  f"ohne Task (Übergänge)")
        tagged = assigned.dropna(subset=["task_index"])
        for tidx, bg in tagged.groupby("task_index", sort=True):
            first = bg.iloc[0]
            pcts = block_percentages(bg)
            rows.append({
                "session_id": sid,
                "person_id": bg["person_id"].iat[0],
                "task_index": int(tidx),
                "task_id": first["task_id"],
                "task_name": first["task_name"],
                "task_category": first["task_category"],
                "n_windows": pcts["n_windows"],
                "true_pct": pcts["true_pct"],
                "pred_pct": pcts["pred_pct"],
                "error_pp": pcts["pred_pct"] - pcts["true_pct"],
            })
    return pd.DataFrame(rows, columns=ENGAGEMENT_COLS)
```

- [ ] **Step 4: Run the engagement test file**

Run: `python -m pytest tests/test_engagement_eval.py -v`
Expected: PASS — alle Tests grün.

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/engagement.py tests/test_engagement_eval.py
git commit -m "feat(evaluation): engagement_per_task() aggregation

Aggregiert pro (Session, Task-Block) den Schreibzeit-Anteil über den
geteilten block_percentages()-Helfer. Sessions ohne Marker werden
übersprungen, nicht zuordenbare Fenster geloggt.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: `plot_engagement_heatmap()` — Proband × Task Heatmap

Ein Grid (Zeilen = Probanden, Spalten = Schreib-Tasks), Zellfarbe = `true_pct`, Beschriftung `echt/geschätzt`. Daneben ein Pausen-Streifen als Kontrolle.

**Files:**
- Modify: `src/evaluation/engagement.py`
- Test: `tests/test_engagement_eval.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_engagement_eval.py` anhängen:

```python
def test_plot_engagement_heatmap_writes_file(tmp_path):
    eng_df = pd.DataFrame({
        "session_id": ["S001", "S001", "S002", "S002"],
        "person_id": ["P01", "P01", "P02", "P02"],
        "task_index": [1, 2, 1, 2],
        "task_id": ["abschreiben", "pause", "abschreiben", "pause"],
        "task_name": ["Text", "Pause", "Text", "Pause"],
        "task_category": ["writing", "idle", "writing", "idle"],
        "n_windows": [100, 80, 100, 80],
        "true_pct": [72.0, 4.0, 65.0, 6.0],
        "pred_pct": [70.0, 5.0, 71.0, 8.0],
        "error_pp": [-2.0, 1.0, 6.0, 2.0],
    })
    out = tmp_path / "engagement_heatmap.png"

    eng.plot_engagement_heatmap(eng_df, out)

    assert out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engagement_eval.py::test_plot_engagement_heatmap_writes_file -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'plot_engagement_heatmap'`

- [ ] **Step 3: Implement `plot_engagement_heatmap()`**

In `src/evaluation/engagement.py`, nach `engagement_per_task()` einfügen:

```python
def plot_engagement_heatmap(eng_df: pd.DataFrame, out_path: Path) -> None:
    """Proband × Schreib-Task Heatmap plus Pausen-Kontrollstreifen.

    Zellfarbe = ``true_pct``; Zell-Text zeigt ``echt/geschätzt``. Der
    Pausen-Streifen rechts sollte durchgehend niedrige Werte zeigen.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    persons = sorted(eng_df["person_id"].unique())
    writing = eng_df[eng_df["task_category"] == "writing"]
    tasks = [t for t in WRITING_TASKS if t in set(writing["task_id"])]

    true_grid = np.full((len(persons), len(tasks)), np.nan)
    pred_grid = np.full((len(persons), len(tasks)), np.nan)
    for i, p in enumerate(persons):
        for j, t in enumerate(tasks):
            cell = writing[(writing["person_id"] == p)
                           & (writing["task_id"] == t)]
            if not cell.empty:
                true_grid[i, j] = cell["true_pct"].mean()
                pred_grid[i, j] = cell["pred_pct"].mean()

    # Pausen-Kontrolle: mittlerer true_pct der idle-Blöcke je Proband.
    idle = eng_df[eng_df["task_category"] == "idle"]
    pause_col = np.array([
        idle.loc[idle["person_id"] == p, "true_pct"].mean()
        for p in persons
    ]).reshape(-1, 1)

    fig, (ax, axp) = plt.subplots(
        1, 2, figsize=(2.2 * len(tasks) + 3.0, 0.55 * len(persons) + 1.6),
        gridspec_kw={"width_ratios": [max(len(tasks), 1), 1]})

    im = ax.imshow(true_grid, cmap="viridis", vmin=0, vmax=100,
                   aspect="auto")
    ax.set_xticks(range(len(tasks)))
    ax.set_xticklabels(tasks, rotation=20, ha="right")
    ax.set_yticks(range(len(persons)))
    ax.set_yticklabels(persons)
    ax.set_title("Schreibzeit-Anteil je Aufgabe  (echt / geschätzt)")
    for i in range(len(persons)):
        for j in range(len(tasks)):
            if not np.isnan(true_grid[i, j]):
                ax.text(j, i,
                        f"{true_grid[i, j]:.0f}/{pred_grid[i, j]:.0f}",
                        ha="center", va="center", fontsize=8,
                        color="white" if true_grid[i, j] < 55 else "black")

    axp.imshow(pause_col, cmap="viridis", vmin=0, vmax=100, aspect="auto")
    axp.set_xticks([0])
    axp.set_xticklabels(["Pause"], rotation=20, ha="right")
    axp.set_yticks([])
    axp.set_title("Kontrolle")
    for i in range(len(persons)):
        if not np.isnan(pause_col[i, 0]):
            axp.text(0, i, f"{pause_col[i, 0]:.0f}", ha="center",
                     va="center", fontsize=8,
                     color="white" if pause_col[i, 0] < 55 else "black")

    fig.colorbar(im, ax=[ax, axp], fraction=0.04,
                 label="echter Schreibzeit-Anteil (%)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engagement_eval.py::test_plot_engagement_heatmap_writes_file -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/engagement.py tests/test_engagement_eval.py
git commit -m "feat(evaluation): engagement heatmap plot

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: `evaluate()`-Orchestrator + CLI

`evaluate()` fügt alles zusammen: OOF laden, aggregieren, CSV schreiben, zwei Abschnitte drucken (Schreib-Tasks + Pausen-Kontrolle), Heatmap rendern.

**Files:**
- Modify: `src/evaluation/engagement.py`
- Test: `tests/test_engagement_eval.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_engagement_eval.py` anhängen:

```python
def test_evaluate_writes_engagement_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(eng, "MARKERS_DIR", tmp_path)
    monkeypatch.setattr(eng, "FIG_DIR", tmp_path / "figures")
    _write_markers(tmp_path / "S001_markers.csv", [
        (1000, "study_start", "", "", "", ""),
        (1100, "task_start", "abschreiben", "Text", 1, "writing"),
        (2000, "task_end",   "abschreiben", "Text", 1, "writing"),
        (2100, "task_start", "pause", "Pause", 2, "idle"),
        (3000, "task_end",   "pause", "Pause", 2, "idle"),
        (3100, "study_end",  "", "", "", ""),
    ])
    # 4 Fenster im writing-Block, 4 im idle-Block
    oof = _oof("S001", "P01",
               [1200.0, 1400.0, 1600.0, 1800.0,
                2200.0, 2400.0, 2600.0, 2800.0],
               [1, 1, 1, 0, 0, 0, 0, 0],
               [0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1])
    oof_path = tmp_path / "loso_oof.csv"
    oof.to_csv(oof_path, index=False)
    out_csv = tmp_path / "engagement_metrics.csv"

    result = eng.evaluate(oof_path=oof_path, out_csv=out_csv)

    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert list(df.columns) == eng.ENGAGEMENT_COLS
    assert len(df) == 2
    assert set(df["task_category"]) == {"writing", "idle"}
    assert (tmp_path / "figures" / "engagement_heatmap.png").exists()
    assert "engagement" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engagement_eval.py::test_evaluate_writes_engagement_csv -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'evaluate'`

- [ ] **Step 3: Implement `evaluate()` and wire the CLI**

In `src/evaluation/engagement.py`, nach `plot_engagement_heatmap()` einfügen:

```python
def evaluate(oof_path: Path = MODEL_DIR / "loso_oof.csv",
             out_csv: Path = MODEL_DIR / "engagement_metrics.csv") -> dict:
    """Orchestriert die Engagement-Auswertung: CSV + Heatmap."""
    oof = load_oof(oof_path)
    eng_df = engagement_per_task(oof)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    eng_df.to_csv(out_csv, index=False)

    writing = eng_df[eng_df["task_category"] == "writing"]
    idle = eng_df[eng_df["task_category"] == "idle"]
    print("=== Schreib-Tasks (Engagement: echter Schreibzeit-Anteil) ===")
    print(writing.to_string(index=False))
    print()
    print("=== Pausen (Kontrolle — true_pct sollte niedrig sein) ===")
    print(idle.to_string(index=False))

    heatmap = FIG_DIR / "engagement_heatmap.png"
    plot_engagement_heatmap(eng_df, heatmap)
    print(f"→ {out_csv}")
    print(f"→ {heatmap}")
    return {"engagement": eng_df}
```

Am Dateiende, **nach** `_parse_args()`, anhängen:

```python
if __name__ == "__main__":
    args = _parse_args()
    evaluate(oof_path=Path(args.oof), out_csv=Path(args.out))
```

- [ ] **Step 4: Run the full engagement test file**

Run: `python -m pytest tests/test_engagement_eval.py -v`
Expected: PASS — alle Tests grün.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS — alle bisherigen Tests plus die neuen.

- [ ] **Step 6: Commit**

```bash
git add src/evaluation/engagement.py tests/test_engagement_eval.py
git commit -m "feat(evaluation): engagement evaluate() orchestrator + CLI

python -m src.evaluation.engagement erzeugt engagement_metrics.csv
plus die Proband×Task-Heatmap; Schreib-Tasks und Pausen-Kontrolle
getrennt ausgegeben.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Dokumentation — `reports/engagement.md` + CLAUDE.md

**Files:**
- Create: `reports/engagement.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create `reports/engagement.md`**

`reports/engagement.md` neu anlegen:

```markdown
# Engagement — Schreibzeit-Anteil pro Aufgabe

Fortschritts- und Vorgehens-Log für Prio 2 der Zwischenpräsi-Roadmap:
pro Schreib-Aufgabe und Proband den tatsächlichen Schreibzeit-Anteil
auswerten — ein Engagement-Proxy als Auswertungs-Schicht über den
LOSO-Vorhersagen.

- Spec: `docs/specs/2026-05-21-engagement-design.md`
- Plan: `docs/plans/2026-05-21-engagement-plan.md`
- Branch: `feature/engagement`

## Ziel

Das LOSO-Modell klassifiziert pro 1-s-Fenster binär writing/idle. Die
Engagement-Auswertung ordnet diese Sekunden über die Study-Mode-Marker
den einzelnen Aufgaben zu und aggregiert pro (Proband, Aufgabe) den
Schreibzeit-Anteil. Das Modell selbst wird nicht verändert.

Motivation: P07s 0.58 Math-Accuracy ist kein Modellfehler — die Person
hat in dieser Aufgabe kaum geschrieben. Der Schreibzeit-Anteil macht
das zur Messgröße statt zur Fehlerquelle.

## Wichtige Einschränkung

Schreibzeit ≠ Aufmerksamkeit. Der Wert ist ein **Engagement-Proxy** für
Aufgabenbearbeitung, kein Aufmerksamkeits-Detektor. Eine Person kann
konzentriert denken, ohne zu schreiben.

## Architektur

`src/evaluation/engagement.py` — reines Post-Processing über
`models/loso_oof.csv` + den `data/raw/markers/`-CSVs. Die
Per-Block-Prozent-Formel wird über `block_percentages()` mit
`regression.py` geteilt.

## Ergebnisse

(wird beim ersten echten Lauf gefüllt)
```

- [ ] **Step 2: Update CLAUDE.md — CLI-Befehl**

In `CLAUDE.md`, im Code-Block der ML-Pipeline-Befehle, die Zeile mit
`src.evaluation.regression` ergänzen — danach einfügen:

```
python -m src.evaluation.engagement               # Schreibzeit-Anteil pro Aufgabe + Heatmap
```

- [ ] **Step 3: Update CLAUDE.md — Modul-Beschreibung**

In `CLAUDE.md`, direkt **nach** dem `src/evaluation/regression.py`-Absatz, einen neuen Listenpunkt einfügen:

```
- `src/evaluation/engagement.py` — Engagement-Auswertung (Stufe 2,
  Prio 2). Reines Post-Processing über `models/loso_oof.csv` + den
  Study-Mode-`markers`-CSVs. Ordnet jedes 1-s-Fenster über `t_center_ms`
  einem Task-Block zu (`task_start`/`task_end` aus den Markern) und
  aggregiert pro `(Session, Task)` den Schreibzeit-Anteil: `true_pct`
  (geschlossene Labels) und `pred_pct` (binärer Schätzer, geteilt mit
  `regression.py` via `block_percentages()`). Output:
  `models/engagement_metrics.csv` (1 Zeile pro Task-Block, Schreib-Tasks
  + Pausen als Kontrolle) plus `reports/figures/engagement_heatmap.png`
  (Proband × Task). Der Wert ist ein **Engagement-Proxy**, kein
  Aufmerksamkeits-Detektor — Schreibzeit ≠ Aufmerksamkeit.
```

- [ ] **Step 4: Verify the docs render and tests still pass**

Run: `python -m pytest tests/ -q`
Expected: PASS — keine Änderung gegenüber Task 6 (reine Doku).

- [ ] **Step 5: Commit**

```bash
git add reports/engagement.md CLAUDE.md
git commit -m "docs(engagement): progress log + CLAUDE.md module entry

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Abschluss

Nach Task 7:

- [ ] **Realer Lauf** (sofern `models/loso_oof.csv` vorhanden):
  `python -m src.training.train_loso --save-oof` falls die OOF-CSV
  fehlt, dann `python -m src.evaluation.engagement`. Prüfen, dass die
  Pausen-Zeilen sichtbar niedrigeren `true_pct` zeigen als die
  Schreib-Tasks und der P07-Math-Block als niedrige Zelle erscheint.
  Ergebnisse in `reports/engagement.md` unter „Ergebnisse" eintragen.
- [ ] **Branch abschließen** über die `superpowers:finishing-a-development-branch`-Skill (PR gegen `main`).
```
