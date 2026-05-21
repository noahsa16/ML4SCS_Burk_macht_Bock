# Regression — Schreib-Prozent pro Zeitfenster: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine kontinuierliche Schätzung „wie viel Prozent eines Zeitfensters wurde geschrieben" als Auswertungs-Schicht über den bestehenden LOSO-Vorhersagen, mit MAE/RMSE/Bias gegen zwei Ground-Truth-Definitionen und Calibration-Plots.

**Architecture:** Zwei über ein CSV-Artefakt entkoppelte Stufen. Stufe 1: `train_loso.py` schreibt mit `--save-oof` die out-of-fold-Vorhersagen (roh + isotonisch kalibriert) pro Fenster nach `models/loso_oof.csv`. Stufe 2: `src/evaluation/regression.py` ist reines Post-Processing auf dieser CSV — kein Modell-Training, voll unit-testbar. Die Implementierungs-Reihenfolge baut Stufe 2 zuerst (definiert das CSV-Schema), dann Stufe 1.

**Tech Stack:** Python, pandas, numpy, scikit-learn (`CalibratedClassifierCV`), matplotlib, pytest.

**Spec:** `docs/specs/2026-05-21-regression-schreibprozent-design.md`

---

## File Structure

- **Create** `src/evaluation/regression.py` — Stufe-2-Modul. Verantwortlich für: OOF-CSV lesen, rohe Pen-Wahrheit aus `merged.csv` lesen, Aggregation auf Zeitblöcke, MAE/RMSE/Bias, Plots, CLI.
- **Create** `tests/test_regression_eval.py` — Tier-1-Smoke-Tests, trainings-frei (OOF + merged gemockt).
- **Modify** `src/training/train_loso.py` — neues Flag `--save-oof`, isotonische Kalibrierung pro Fold, OOF-Zeilen sammeln und schreiben.
- **Unberührt** `src/evaluation/evaluate.py` — bleibt der bestehende Placeholder.

`reports/figures/` und `models/` existieren bereits.

---

## Task 1: Modul-Skeleton + `load_oof` + `pen_truth_per_session`

**Files:**
- Create: `src/evaluation/regression.py`
- Test: `tests/test_regression_eval.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_regression_eval.py`:

```python
"""Smoke tests für die Schreib-Prozent-Regression (Stufe 2).

Trainings-frei: OOF-CSV und merged.csv werden als synthetische Fixtures
gemockt — Stufe 2 trainiert per Design kein Modell.
"""

import numpy as np
import pandas as pd
import pytest

from src.evaluation import regression as reg


def _write_merged(path, n, writing_mask):
    """Synthetisches merged.csv: n Samples @ 50 Hz, label_writing aus mask."""
    pd.DataFrame(
        {
            "local_ts_ms": np.arange(n, dtype=float) * 20.0,
            "label_writing": np.asarray(writing_mask, dtype=int),
        }
    ).to_csv(path, index=False)


def test_pen_truth_per_session_reads_writing_fraction(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "DATA_PROC", tmp_path)
    # 100 Samples, erste 60 schreibend
    _write_merged(tmp_path / "S001_merged.csv", 100, [1] * 60 + [0] * 40)

    out = reg.pen_truth_per_session("S001")

    assert list(out.columns) == ["local_ts_ms", "label_writing"]
    assert len(out) == 100
    assert out["label_writing"].mean() == pytest.approx(0.60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_regression_eval.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module 'src.evaluation.regression' has no attribute ...`

- [ ] **Step 3: Write minimal implementation**

Create `src/evaluation/regression.py`:

```python
"""Regression: Schreib-Prozent pro Zeitfenster.

Stufe 2 der Schreib-Prozent-Auswertung (siehe
``docs/specs/2026-05-21-regression-schreibprozent-design.md``). Reines
Post-Processing über ``models/loso_oof.csv`` (von ``train_loso.py
--save-oof`` erzeugt) — kein Modell-Training. Liefert MAE/RMSE/Bias der
geschätzten Schreib-Prozente gegen zwei Ground-Truth-Definitionen plus
Calibration-Plots.

CLI
---
::

    python -m src.evaluation.regression                       # Defaults
    python -m src.evaluation.regression --oof PATH
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[2]
DATA_PROC = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
FIG_DIR = ROOT / "reports" / "figures"

# Spaltenschema der OOF-CSV, die train_loso.py --save-oof schreibt.
OOF_COLS = ["session_id", "person_id", "t_center_ms",
            "label", "proba_raw", "proba_cal"]


def load_oof(path: Path) -> pd.DataFrame:
    """Liest models/loso_oof.csv."""
    return pd.read_csv(path)


def pen_truth_per_session(session_id: str) -> pd.DataFrame:
    """Rohe Pen-Wahrheit: label_writing je 50-Hz-Sample aus merged.csv.

    Zeit-Achse ``local_ts_ms`` ist dieselbe, aus der windows.py
    ``t_center_ms`` mittelt — Aggregations-Blöcke greifen ohne Umrechnung.
    """
    path = DATA_PROC / f"{session_id}_merged.csv"
    df = pd.read_csv(path, usecols=["local_ts_ms", "label_writing"])
    return df.dropna(subset=["local_ts_ms"]).sort_values(
        "local_ts_ms"
    ).reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_regression_eval.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/regression.py tests/test_regression_eval.py
git commit -m "feat(evaluation): regression module skeleton + pen-truth loader"
```

---

## Task 2: `aggregate` — Zeitblock-Aggregation

**Files:**
- Modify: `src/evaluation/regression.py`
- Test: `tests/test_regression_eval.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_regression_eval.py`:

```python
def _oof_one_session(n_windows, proba_cal, label, session="S001", person="P01"):
    """Synthetische OOF-Zeilen: 1 Fenster / 0.5 s, t_center_ms ab 500 ms."""
    return pd.DataFrame(
        {
            "session_id": session,
            "person_id": person,
            "t_center_ms": 500.0 + np.arange(n_windows) * 500.0,
            "label": np.asarray(label, dtype=int),
            "proba_raw": np.asarray(proba_cal, dtype=float),
            "proba_cal": np.asarray(proba_cal, dtype=float),
        }
    )


def test_aggregate_whole_session_one_block_per_session():
    # 120 Fenster (= 60 s @ 0.5 s Stride), halb schreibend
    oof = _oof_one_session(120, [0.8] * 120, [1] * 60 + [0] * 60)
    out = reg.aggregate(oof, scale_sec=None, merged_loader=lambda s: pd.DataFrame())

    assert len(out) == 1
    assert out["session_id"].iat[0] == "S001"
    assert out["pred_pct"].iat[0] == pytest.approx(80.0)
    assert out["truth_closed_pct"].iat[0] == pytest.approx(50.0)
    assert out["n_windows"].iat[0] == 120


def test_aggregate_fixed_scale_splits_into_blocks():
    # 240 Fenster = 120 s; bei 60-s-Blöcken → 2 Blöcke à 120 Fenster
    oof = _oof_one_session(240, [0.5] * 240, [1] * 240)
    out = reg.aggregate(oof, scale_sec=60.0, merged_loader=lambda s: pd.DataFrame())

    assert len(out) == 2
    assert list(out["n_windows"]) == [120, 120]


def test_aggregate_pen_pct_from_merged_loader():
    oof = _oof_one_session(120, [0.9] * 120, [1] * 120)
    # merged: 3000 Samples @ 50 Hz = 60 s, 30 s schreibend
    merged = pd.DataFrame(
        {
            "local_ts_ms": np.arange(3000, dtype=float) * 20.0,
            "label_writing": [1] * 1500 + [0] * 1500,
        }
    )
    out = reg.aggregate(oof, scale_sec=None, merged_loader=lambda s: merged)

    assert out["truth_pen_pct"].iat[0] == pytest.approx(50.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_regression_eval.py -k aggregate -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'aggregate'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/evaluation/regression.py`:

```python
def _pen_pct(merged: pd.DataFrame, block_start: float,
             block_end: float | None, anchor: float) -> float:
    """Anteil Pen-down-Samples im Zeitblock [block_start, block_end), in %."""
    if merged.empty:
        return float("nan")
    if block_end is None:
        sel = merged
    else:
        t = merged["local_ts_ms"]
        # Why: Block 0 (block_start == anchor) muss die ~0.5 s vor dem
        # ersten Fenster-Zentrum mitnehmen — sonst fallen frühe Samples
        # durch den window-center-Inset still raus.
        lo = -np.inf if block_start <= anchor else block_start
        sel = merged[(t >= lo) & (t < block_end)]
    if sel.empty:
        return float("nan")
    return float(sel["label_writing"].mean()) * 100.0


def aggregate(oof_df: pd.DataFrame, scale_sec: float | None,
              merged_loader=pen_truth_per_session) -> pd.DataFrame:
    """Eine Zeile pro (Session, Zeitblock).

    ``scale_sec=None`` → ein Block je Session (ganze Session). Sonst
    nicht-überlappende Blöcke der Länge ``scale_sec``, verankert am
    ersten ``t_center_ms`` der Session.
    """
    scale_ms = None if scale_sec is None else scale_sec * 1000.0
    rows: list[dict] = []
    for sid, g in oof_df.groupby("session_id", sort=False):
        g = g.sort_values("t_center_ms")
        anchor = float(g["t_center_ms"].min())
        if scale_ms is None:
            blk = pd.Series(0, index=g.index)
        else:
            blk = ((g["t_center_ms"] - anchor) // scale_ms).astype(int)
        merged = merged_loader(sid)
        for blk_idx, bg in g.groupby(blk, sort=True):
            block_start = anchor if scale_ms is None else anchor + blk_idx * scale_ms
            block_end = None if scale_ms is None else block_start + scale_ms
            rows.append({
                "session_id": sid,
                "person_id": bg["person_id"].iat[0],
                "block_start_ms": block_start,
                "n_windows": int(len(bg)),
                "pred_pct": float(bg["proba_cal"].mean()) * 100.0,
                "truth_closed_pct": float(bg["label"].mean()) * 100.0,
                "truth_pen_pct": _pen_pct(merged, block_start, block_end, anchor),
            })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_regression_eval.py -k aggregate -v`
Expected: PASS (3 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/regression.py tests/test_regression_eval.py
git commit -m "feat(evaluation): time-block aggregation for write-percentage"
```

---

## Task 3: `regression_metrics` — MAE / RMSE / Bias

**Files:**
- Modify: `src/evaluation/regression.py`
- Test: `tests/test_regression_eval.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_regression_eval.py`:

```python
def test_regression_metrics_known_error():
    # pred immer 10 pp über der Wahrheit → MAE=RMSE=Bias=10
    agg = pd.DataFrame(
        {
            "pred_pct": [60.0, 30.0, 90.0],
            "truth_closed_pct": [50.0, 20.0, 80.0],
            "truth_pen_pct": [40.0, 10.0, 70.0],
        }
    )
    m = reg.regression_metrics(agg)

    assert m["closed"]["mae"] == pytest.approx(10.0)
    assert m["closed"]["rmse"] == pytest.approx(10.0)
    assert m["closed"]["bias"] == pytest.approx(10.0)
    # pred liegt 20 pp über der rohen Pen-Wahrheit → positiver Bias
    assert m["pen"]["bias"] == pytest.approx(20.0)
    assert m["closed"]["n"] == 3


def test_regression_metrics_ignores_nan_truth():
    agg = pd.DataFrame(
        {
            "pred_pct": [60.0, 30.0],
            "truth_closed_pct": [50.0, 20.0],
            "truth_pen_pct": [40.0, float("nan")],
        }
    )
    m = reg.regression_metrics(agg)

    assert m["pen"]["n"] == 1
    assert m["pen"]["bias"] == pytest.approx(20.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_regression_eval.py -k metrics -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'regression_metrics'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/evaluation/regression.py`:

```python
def regression_metrics(agg_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """MAE/RMSE/Bias der Schätzung gegen beide Ground-Truth-Definitionen.

    Alle Werte in Prozentpunkten. Bias = mittlerer vorzeichenbehafteter
    Fehler (pred − truth) — positiv = Überschätzung.
    """
    out: dict[str, dict[str, float]] = {}
    for truth_col, name in [("truth_closed_pct", "closed"),
                            ("truth_pen_pct", "pen")]:
        d = agg_df.dropna(subset=[truth_col, "pred_pct"])
        err = d["pred_pct"].to_numpy() - d[truth_col].to_numpy()
        n = len(err)
        out[name] = {
            "n": int(n),
            "mae": float(np.mean(np.abs(err))) if n else float("nan"),
            "rmse": float(np.sqrt(np.mean(err ** 2))) if n else float("nan"),
            "bias": float(np.mean(err)) if n else float("nan"),
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_regression_eval.py -k metrics -v`
Expected: PASS (2 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/regression.py tests/test_regression_eval.py
git commit -m "feat(evaluation): MAE/RMSE/Bias metrics for write-percentage"
```

---

## Task 4: Plots — Calibration-Diagramm + Scatter

**Files:**
- Modify: `src/evaluation/regression.py`

- [ ] **Step 1: Implement the plot functions**

Append to `src/evaluation/regression.py`:

```python
def plot_calibration(oof_df: pd.DataFrame, out_path: Path,
                      n_bins: int = 10) -> None:
    """Reliability-Diagramm der kalibrierten Sekunden-Proba."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = oof_df["proba_cal"].to_numpy()
    y = oof_df["label"].to_numpy()
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, n_bins - 1)
    xs, ys = [], []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            xs.append(p[m].mean())
            ys.append(y[m].mean())

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="grey", label="perfekt kalibriert")
    ax.plot(xs, ys, "o-", label="kalibrierte Proba")
    ax.set_xlabel("vorhergesagte Schreib-Wahrscheinlichkeit")
    ax.set_ylabel("empirische Schreib-Frequenz")
    ax.set_title("Calibration (Sekunden-Ebene)")
    ax.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_scatter(aggs: dict[str, pd.DataFrame], out_path: Path) -> None:
    """Pro Skala ein Panel: geschätztes % vs. wahres % je Zeitblock."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(aggs), figsize=(5 * len(aggs), 5),
                             squeeze=False)
    for ax, (label, agg) in zip(axes[0], aggs.items()):
        d = agg.dropna(subset=["truth_closed_pct", "pred_pct"])
        ax.plot([0, 100], [0, 100], "--", color="grey")
        ax.scatter(d["truth_closed_pct"], d["pred_pct"], alpha=0.6)
        err = d["pred_pct"] - d["truth_closed_pct"]
        mae = float(np.mean(np.abs(err))) if len(d) else float("nan")
        bias = float(np.mean(err)) if len(d) else float("nan")
        ax.set_title(f"{label}  (MAE={mae:.1f}, Bias={bias:+.1f})")
        ax.set_xlabel("wahres % (geschlossen)")
        ax.set_ylabel("geschätztes %")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
```

- [ ] **Step 2: Smoke-check the plot functions in a REPL**

Run:
```bash
python -c "
import numpy as np, pandas as pd
from pathlib import Path
from src.evaluation import regression as reg
oof = pd.DataFrame({'session_id':'S1','person_id':'P1',
  't_center_ms':np.arange(50)*500.0,'label':np.r_[np.ones(25),np.zeros(25)].astype(int),
  'proba_raw':np.linspace(0,1,50),'proba_cal':np.linspace(0,1,50)})
reg.plot_calibration(oof, Path('/tmp/_cal.png'))
agg = reg.aggregate(oof, None, merged_loader=lambda s: pd.DataFrame())
reg.plot_scatter({'session':agg}, Path('/tmp/_sc.png'))
print('OK', Path('/tmp/_cal.png').stat().st_size, Path('/tmp/_sc.png').stat().st_size)
"
```
Expected: `OK <nonzero> <nonzero>` — beide PNG-Dateien erzeugt.

- [ ] **Step 3: Commit**

```bash
git add src/evaluation/regression.py
git commit -m "feat(evaluation): calibration + scatter plots for write-percentage"
```

---

## Task 5: `evaluate` orchestrator + CLI

**Files:**
- Modify: `src/evaluation/regression.py`
- Test: `tests/test_regression_eval.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_regression_eval.py`:

```python
def test_evaluate_writes_metrics_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "DATA_PROC", tmp_path)
    monkeypatch.setattr(reg, "FIG_DIR", tmp_path / "figures")
    _write_merged(tmp_path / "S001_merged.csv", 6000, [1] * 3000 + [0] * 3000)

    oof = _oof_one_session(240, [0.6] * 240, [1] * 120 + [0] * 120)
    oof_path = tmp_path / "loso_oof.csv"
    oof.to_csv(oof_path, index=False)
    out_csv = tmp_path / "regression_metrics.csv"

    result = reg.evaluate(oof_path=oof_path, scales=(60.0, None),
                          out_csv=out_csv)

    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    # 2 Skalen × 2 Wahrheiten = 4 Zeilen
    assert len(df) == 4
    assert set(df["scale"]) == {"60s", "session"}
    assert set(df["truth"]) == {"closed", "pen"}
    assert (tmp_path / "figures" / "regression_calibration.png").exists()
    assert (tmp_path / "figures" / "regression_scatter.png").exists()
    assert "metrics" in result and "aggregates" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_regression_eval.py -k evaluate -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'evaluate'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/evaluation/regression.py`:

```python
def evaluate(oof_path: Path = MODEL_DIR / "loso_oof.csv",
             scales: tuple[float | None, ...] = (60.0, 300.0, None),
             out_csv: Path = MODEL_DIR / "regression_metrics.csv") -> dict:
    """Orchestriert die Regression über alle Skalen, schreibt CSV + Plots."""
    oof = load_oof(oof_path)
    aggs: dict[str, pd.DataFrame] = {}
    metric_rows: list[dict] = []
    for scale in scales:
        label = "session" if scale is None else f"{int(scale)}s"
        agg = aggregate(oof, scale)
        aggs[label] = agg
        for truth, vals in regression_metrics(agg).items():
            metric_rows.append({"scale": label, "truth": truth, **vals})

    metrics = pd.DataFrame(metric_rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out_csv, index=False)
    print(metrics.to_string(index=False))

    plot_calibration(oof, FIG_DIR / "regression_calibration.png")
    plot_scatter(aggs, FIG_DIR / "regression_scatter.png")
    print(f"→ {out_csv}")
    print(f"→ {FIG_DIR / 'regression_calibration.png'}")
    print(f"→ {FIG_DIR / 'regression_scatter.png'}")
    return {"metrics": metrics, "aggregates": aggs}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oof", default=str(MODEL_DIR / "loso_oof.csv"),
                   help="Pfad zur OOF-CSV (default: models/loso_oof.csv).")
    p.add_argument("--out", default=str(MODEL_DIR / "regression_metrics.csv"),
                   help="Ziel-CSV für die Metriken.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    evaluate(oof_path=Path(args.oof), out_csv=Path(args.out))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_regression_eval.py -v`
Expected: PASS (alle Tests)

- [ ] **Step 5: Commit**

```bash
git add src/evaluation/regression.py tests/test_regression_eval.py
git commit -m "feat(evaluation): evaluate orchestrator + CLI for write-percentage"
```

---

## Task 6: `train_loso.py` — `--save-oof` + isotonische Kalibrierung

**Files:**
- Modify: `src/training/train_loso.py`

- [ ] **Step 1: Add the calibration import**

In `src/training/train_loso.py`, nach den bestehenden sklearn-Imports (nach Zeile ~51) ergänzen:

```python
from sklearn.calibration import CalibratedClassifierCV
```

- [ ] **Step 2: Extend `_fit_eval_fold` to calibrate and collect OOF rows**

In `_fit_eval_fold`, nach `y_proba = clf.predict_proba(X_test)[:, 1]` (Zeile ~194) einfügen:

```python
    # Isotonische Kalibrierung für die Schreib-Prozent-Regression (Stufe 1).
    # Why: cv=3 splittet die Trainings-Folds NICHT personen-gruppiert —
    # bei N=10 und monotoner Kalibrierung vertretbar (bekannte Vereinfachung,
    # siehe docs/specs/2026-05-21-regression-schreibprozent-design.md).
    # Eigene Estimator-Instanz, damit der Headline-clf unangetastet bleibt.
    cal = CalibratedClassifierCV(
        RandomForestClassifier(
            n_estimators=n_estimators,
            random_state=random_state,
            class_weight="balanced",
            n_jobs=-1,
        ),
        method="isotonic",
        cv=3,
    )
    cal.fit(X_train, y_train)
    y_proba_cal = cal.predict_proba(X_test)[:, 1]

    oof = pd.DataFrame({
        "session_id": test_df["session_id"].to_numpy(),
        "person_id": test_df["person_id"].to_numpy(),
        "t_center_ms": test_df["t_center_ms"].to_numpy(),
        "label": y_test,
        "proba_raw": y_proba,
        "proba_cal": y_proba_cal,
    })
```

Dann im Return-`dict` von `_fit_eval_fold` (Zeile ~203-215) einen Schlüssel ergänzen:

```python
        "oof": oof,
```

`accuracy`, `f1_writing`, `roc_auc`, `bursts` bleiben unverändert auf `y_proba` / `y_pred` — die Headline-Metriken nutzen weiter die **rohe** Proba. ROC-AUC ist gegen monotone Kalibrierung invariant; Accuracy/F1 ändern sich nicht, weil sie nicht auf `y_proba_cal` zugreifen.

- [ ] **Step 3: Add `save_oof` parameter to `train_loso` and write the CSV**

In der Signatur von `train_loso` (Zeile ~248-257) ergänzen:

```python
    save_oof: Path | None = None,
```

Nach der Fold-Schleife, direkt vor `if save_cv_csv is not None:` (Zeile ~421) einfügen:

```python
    if save_oof is not None:
        oof_all = pd.concat(
            [r["oof"] for r in fold_results], ignore_index=True
        )
        save_oof.parent.mkdir(parents=True, exist_ok=True)
        oof_all.to_csv(save_oof, index=False)
        print(f"\n→ {save_oof}  ({len(oof_all)} OOF-Zeilen)")
```

- [ ] **Step 4: Add the `--save-oof` CLI flag**

In `_parse_args`, nach dem `--save-cv-csv`-Block (Zeile ~473-479) einfügen:

```python
    p.add_argument(
        "--save-oof",
        nargs="?",
        const=str(MODEL_DIR / "loso_oof.csv"),
        default=None,
        help="Write per-window out-of-fold predictions (raw + calibrated "
        "proba) to PATH (default: models/loso_oof.csv).",
    )
```

Und im `train_loso(...)`-Aufruf unter `if __name__ == "__main__":` (Zeile ~485-494) ergänzen:

```python
        save_oof=Path(args.save_oof) if args.save_oof else None,
```

- [ ] **Step 5: Run the existing test suite — headline metrics must be unchanged**

Run: `pytest tests/ -q`
Expected: PASS, 138+ Tests grün (die neuen Regression-Tests zusätzlich). Keine bestehende Datei betroffen.

- [ ] **Step 6: End-to-end smoke — generate the OOF CSV**

Run: `python -m src.training.train_loso --save-oof`
Expected: LOSO läuft durch; Konsolen-Output zeigt unverändert `Accuracy: 0.85x ± 0.03x` / `ROC-AUC: 0.92x` (Headline darf sich **nicht** verschoben haben); am Ende `→ .../models/loso_oof.csv  (~18000 OOF-Zeilen)`.

Verifikation der OOF-CSV:
```bash
python -c "
import pandas as pd
d = pd.read_csv('models/loso_oof.csv')
print(d.columns.tolist())
print(len(d), 'rows')
assert list(d.columns) == ['session_id','person_id','t_center_ms','label','proba_raw','proba_cal']
print('proba_cal range', d.proba_cal.min(), d.proba_cal.max())
"
```
Expected: Spalten exakt wie erwartet, `proba_cal` in [0, 1].

- [ ] **Step 7: End-to-end smoke — run the regression**

Run: `python -m src.evaluation.regression`
Expected: Tabelle mit `scale × truth` (60s/300s/session × closed/pen), MAE/RMSE/Bias-Spalten; `models/regression_metrics.csv` und beide PNGs unter `reports/figures/` erzeugt. Erwartung laut Spec: Bias gegen `closed` ≈ 0, Bias gegen `pen` deutlich positiv (Überschätzung).

- [ ] **Step 8: Commit**

```bash
git add src/training/train_loso.py
git commit -m "feat(training): --save-oof flag with isotonic-calibrated OOF predictions"
```

---

## Task 7: Dokumentation aktualisieren

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the new pipeline step**

In `CLAUDE.md`, im Abschnitt „Merge / features / train / evaluate" die Befehlsliste um eine Zeile ergänzen:

```
python -m src.training.train_loso --save-oof              # + OOF-CSV für Regression
python -m src.evaluation.regression                       # Schreib-Prozent: MAE/RMSE/Bias + Plots
```

Im ML-Pipeline-Abschnitt unter `src/evaluation/` einen kurzen Absatz ergänzen:

```
- `src/evaluation/regression.py` — Schreib-Prozent-Regression (Stufe 2).
  Reines Post-Processing über `models/loso_oof.csv`: aggregiert die
  kalibrierten OOF-Proba auf 60 s / 300 s / ganze-Session-Blöcke und
  reportet MAE/RMSE/Bias gegen geschlossene und rohe Pen-Wahrheit, plus
  Calibration- und Scatter-Plot in `reports/figures/`.
```

- [ ] **Step 2: Run the full test suite a final time**

Run: `pytest tests/ -q`
Expected: alle Tests grün.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document write-percentage regression pipeline step"
```

---

## Self-Review Notes

- **Spec coverage:** Ground-Truth (beide) → Task 2/3; kalibrierte Proba → Task 6; OOF-CSV-Architektur → Task 6; `aggregate`/`regression_metrics`/`pen_truth_per_session`/`evaluate` → Task 1/2/3/5; Plots → Task 4; Tests → Task 1/2/3/5; Headline-Invarianz → Task 6 Step 5/6. Alle Erfolgskriterien des Specs abgedeckt.
- **YAGNI:** keine gleitenden Fenster, keine Stunden-Skala, kein Engagement-Split, kein Deployment-Pfad — wie im Spec ausgeschlossen.
- **Type consistency:** OOF-Spaltenschema `[session_id, person_id, t_center_ms, label, proba_raw, proba_cal]` ist in `OOF_COLS` (Task 1), im Test-Helper (Task 2), und im `train_loso`-Writer (Task 6) identisch.
```
