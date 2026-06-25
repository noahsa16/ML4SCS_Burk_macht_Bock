# Passiver Tracker — Phase 0 (Python-Fundament) Implementation Plan — Option (b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das hier-verifizierbare Python-Fundament für die On-Device-Inferenz unter **Option (b)** (gravity-invariante Feature-Teilmenge, kein Filter) bauen — Invarianz-Validierung, ein round-trip-fähiger RF→JSON-Export mit Python-Referenz-Evaluator, und eine Golden-Vektor-Fixture — sodass der spätere Swift-Port (Phasen 1–3) gegen eine bewiesene, bit-genaue Referenz portiert wird.

**Architecture:** Das Deployment-Modell (`models/rf_acc_only_live.joblib`) ist auf die **30 schwerkraft-offset-invarianten Features** trainiert (std/range/FFT-DC-removed/zcr/jerk/corr). Diese sind auf roher Gesamtbeschleunigung == userAcceleration (konstanter Schwerkraft-Offset ändert sie nicht), daher **kein High-Pass-Filter** nötig. Pipeline: roh-Accel → 30 invariante Features (`_window_features`-Subset) → RF-aus-JSON (`RFReferenceEvaluator`) → kausaler `OnlineForwardFilter` (HMM). Jeder Baustein isoliert testbar; die Golden-Vektoren bündeln eine End-to-End-Referenz fürs Swift-Test-Target.

**Tech Stack:** Python 3, numpy, pandas, scikit-learn, joblib, pytest. Bestehende Module: `src/features/windows.py` (`_window_features`, `infer_fs_hz`), `src/evaluation/hmm.py` (`OnlineForwardFilter`). Artefakte: `models/rf_acc_only_live.joblib` (auf 30 invariante Features trainiert, ✅), `models/hmm_live.json`.

## Global Constraints

- Pfade immer relativ zum Repo-Root via `ROOT = Path(__file__).resolve().parents[N]`; keine absoluten Pfade.
- `pytest tests/` muss nach jeder Task grün bleiben.
- **Feature-Reihenfolge IMMER aus `bundle["feature_cols"]` lesen** (die 30 invarianten Namen in Modell-Reihenfolge) — nie neu ableiten. Das Bundle hat zusätzlich `features == "gravity_invariant"`.
- **Volle Float-Präzision** an jeder Serialisierungs-Grenze: Pythons `json` nutzt round-trip-fähige `repr`-Floats — der Export enthält einen **Round-Trip-Selbsttest** (`json.loads(json.dumps(x)) == x` exakt). Keine gerundeten Thresholds/µ/σ.
- **Kein Filter / kein GravityHighPass** — die Features sind by-construction gravity-invariant. (Der frühere High-Pass-Ansatz wurde verworfen, siehe Spec §9.)
- Modell-Bundle-Schema: `{model, feature_cols (30), zscore_mu: dict, zscore_sigma: dict, sample_rate_hz: 50, features: "gravity_invariant", ...}`.
- Branch: `feature/on-device-inference`. Ein Commit pro Task.

---

### Task 1: Invarianz-Validierung (`validate_invariant_deploy.py`)

Verifiziert die (b)-Kernannahme: die 30 Features sind auf roher Gesamtbeschleunigung == userAcceleration. Unit-Test beweist die *exakte* Offset-Invarianz (konstanter Offset ändert die Features nicht); die reale Modern-Session-Auswertung misst die *praktische* Übereinstimmung (Rest = Within-Window-Gravity-Rotation, zweiter Ordnung).

**Files:**
- Create: `scripts/ml/validate_invariant_deploy.py`
- Test: `tests/test_validate_invariant_deploy.py`

**Interfaces:**
- Produces: `invariant_features(accel3: np.ndarray, fs_hz: float, cols: list[str]) -> np.ndarray` (baut die `cols`-Feature-Zeilen aus einem `(N,3)`-Accel-Signal); `feature_agreement(true_user, raw, fs_hz, cols) -> dict` mit `max_abs`, `corr`. CLI `python scripts/ml/validate_invariant_deploy.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate_invariant_deploy.py
import numpy as np
from scripts.ml.validate_invariant_deploy import invariant_features


def test_features_unchanged_by_constant_gravity_offset():
    # The (b) claim: invariant features are identical under a constant offset.
    rng = np.random.default_rng(0)
    user = 0.1 * rng.standard_normal((100, 3))
    raw = user + np.array([0.3, -0.5, 0.8])  # constant gravity vector
    cols = ["ax_std", "ax_range", "ax_zcr", "ax_jerk_std", "corr_ax_ay", "ay_band_3_8"]
    fu = invariant_features(user, 50.0, cols)
    fr = invariant_features(raw, 50.0, cols)
    assert np.allclose(fu, fr, atol=1e-9)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validate_invariant_deploy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ml.validate_invariant_deploy'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/ml/validate_invariant_deploy.py
"""Validiert die (b)-Kernannahme: die 30 gravity-invarianten Features sind auf
roher Gesamtbeschleunigung == userAcceleration.

Unit-Test: exakte Offset-Invarianz. Reale Auswertung (CLI): auf den Modern-Sessions
(userAccel + gravity vorhanden) die Features beidseitig bauen (echte userAccel vs.
rekonstruierte Roh-Accel = userAccel + gravity) und vergleichen. Erwartet ~identisch;
der kleine Rest ist Within-Window-Gravity-Rotation (zweiter Ordnung).

CLI: python scripts/ml/validate_invariant_deploy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODERN = [("S038", "P12"), ("S039", "P13"), ("S040", "P14"),
          ("S041", "P15"), ("S043", "P17")]


def invariant_features(accel3: np.ndarray, fs_hz: float, cols: list[str]) -> np.ndarray:
    """1 s / 0.5 s windows of the requested feature columns from a (N,3) accel signal.

    Gyro columns are zero-filled so _window_features runs; only `cols` are kept.
    """
    accel3 = np.asarray(accel3, dtype=float)
    win, stride = int(round(fs_hz)), int(round(0.5 * fs_hz))
    six = np.column_stack([accel3, np.zeros((len(accel3), 3))])
    rows = [[_window_features(six[s:s + win], fs_hz=fs_hz)[c] for c in cols]
            for s in range(0, len(six) - win + 1, stride)]
    return np.asarray(rows, dtype=float)


def feature_agreement(true_user, raw, fs_hz, cols) -> dict:
    ft = invariant_features(true_user, fs_hz, cols)
    fr = invariant_features(raw, fs_hz, cols)
    n = min(len(ft), len(fr))
    ft, fr = ft[:n], fr[:n]
    diff = ft - fr
    corr = [np.corrcoef(ft[:, j], fr[:, j])[0, 1]
            for j in range(ft.shape[1])
            if ft[:, j].std() > 1e-9 and fr[:, j].std() > 1e-9]
    return {"max_abs": float(np.max(np.abs(diff))) if diff.size else float("nan"),
            "corr": float(np.mean(corr)) if corr else float("nan")}


def run() -> None:
    import joblib
    bundle = joblib.load(ROOT / "models" / "rf_acc_only_live.joblib")  # first-party model
    cols = bundle["feature_cols"]
    print(f"features={len(cols)} (gravity-invariant)\n")
    for sid, pid in MODERN:
        m = pd.read_csv(DATA_PROC / f"{sid}_merged.csv")
        fs = infer_fs_hz(m)
        user = m[["ax", "ay", "az"]].to_numpy(float)
        raw = user + m[["gx", "gy", "gz"]].to_numpy(float)
        a = feature_agreement(user, raw, fs, cols)
        print(f"  {pid} ({sid}): corr={a['corr']:.5f}  max_abs={a['max_abs']:.5f}")
    print("\ncorr→1 / max_abs→0 = invariante Features deployen sauber auf Roh-Accel.")


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test, then the real validation**

Run: `pytest tests/test_validate_invariant_deploy.py -v`
Expected: PASS (1 passed)

Run: `python scripts/ml/validate_invariant_deploy.py`
Expected: eine Zeile pro Modern-Proband mit `corr` nahe 1.0 und kleinem `max_abs` (Rest = Within-Window-Gravity-Rotation). Report the numbers; they confirm clean deployment.

- [ ] **Step 5: Commit**

```bash
git add scripts/ml/validate_invariant_deploy.py tests/test_validate_invariant_deploy.py
git commit -m "feat(deploy): Invarianz-Validierung der 30 Features (raw == userAccel)"
```

---

### Task 2: RF → JSON Export + `RFReferenceEvaluator` + Parität

Serialisiert den trainierten 30-Feature-RF in ein round-trip-fähiges JSON (pro Baum: Arrays) und baut einen pure-Python-Evaluator, der aus dem JSON sklearns `predict_proba` exakt reproduziert. Der Parität-Test ist die Spezifikation, die der Swift-`RFEvaluator` treffen muss.

**Files:**
- Create: `src/deploy/__init__.py`
- Create: `src/deploy/rf_json.py`
- Create: `scripts/ml/export_rf_json.py`
- Test: `tests/test_rf_json.py`

**Interfaces:**
- Produces: `export_rf_to_json(bundle: dict) -> dict`; `RFReferenceEvaluator(model_json: dict)` mit `proba(features: np.ndarray) -> np.ndarray` (features `(N, 30)` in `feature_cols`-Reihenfolge, **vor** Z-Score; der Evaluator wendet das gebackene µ/σ selbst an).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rf_json.py
import json
from pathlib import Path

import joblib
import numpy as np

from src.deploy.rf_json import export_rf_to_json, RFReferenceEvaluator

ROOT = Path(__file__).resolve().parents[1]


def _bundle():
    return joblib.load(ROOT / "models" / "rf_acc_only_live.joblib")


def test_thresholds_round_trip_exactly():
    model_json = export_rf_to_json(_bundle())
    reloaded = json.loads(json.dumps(model_json))
    for t_orig, t_re in zip(model_json["trees"], reloaded["trees"]):
        assert t_orig["threshold"] == t_re["threshold"]
    assert model_json["zscore_mu"] == reloaded["zscore_mu"]


def test_reference_evaluator_matches_sklearn():
    bundle = _bundle()
    model_json = export_rf_to_json(bundle)
    ev = RFReferenceEvaluator(model_json)

    rng = np.random.default_rng(0)
    n_feat = len(bundle["feature_cols"])
    X = rng.standard_normal((50, n_feat)) * 2.0
    mu = np.array([bundle["zscore_mu"][c] for c in bundle["feature_cols"]])
    sigma = np.array([bundle["zscore_sigma"][c] for c in bundle["feature_cols"]])
    expected = bundle["model"].predict_proba((X - mu) / sigma)[:, 1]

    got = ev.proba(X)
    assert np.max(np.abs(got - expected)) < 1e-12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rf_json.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.deploy'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/deploy/__init__.py
```

```python
# src/deploy/rf_json.py
"""RF -> JSON Export + pure-Python-Referenz-Evaluator.

Serialisiert RandomForestClassifier (sklearn) in flache per-Baum-Arrays + das
gebackene pooled µ/σ. Pythons json schreibt round-trip-fähige Floats (shortest
repr) -> bit-exakte De-/Serialisierung. Der RFReferenceEvaluator rekonstruiert
predict_proba exakt; er ist die Spezifikation für den Swift-RFEvaluator.
"""
from __future__ import annotations

import numpy as np


def export_rf_to_json(bundle: dict) -> dict:
    clf = bundle["model"]
    cols = list(bundle["feature_cols"])
    trees = []
    for est in clf.estimators_:
        t = est.tree_
        value = t.value.reshape(t.value.shape[0], -1)  # (n_nodes, n_classes)
        proba1 = (value[:, 1] / value.sum(axis=1)).astype(float)
        trees.append({
            "feature": t.feature.astype(int).tolist(),
            "threshold": t.threshold.astype(float).tolist(),
            "left": t.children_left.astype(int).tolist(),
            "right": t.children_right.astype(int).tolist(),
            "proba1": proba1.tolist(),
        })
    return {
        "feature_cols": cols,
        "zscore_mu": {c: float(bundle["zscore_mu"][c]) for c in cols},
        "zscore_sigma": {c: float(bundle["zscore_sigma"][c]) for c in cols},
        "trees": trees,
        "n_features": len(cols),
    }


class RFReferenceEvaluator:
    def __init__(self, model_json: dict):
        self.cols = model_json["feature_cols"]
        self.mu = np.array([model_json["zscore_mu"][c] for c in self.cols])
        self.sigma = np.array([model_json["zscore_sigma"][c] for c in self.cols])
        self.trees = model_json["trees"]

    def _tree_proba(self, tree: dict, x: np.ndarray) -> float:
        node = 0
        feat, thr = tree["feature"], tree["threshold"]
        left, right = tree["left"], tree["right"]
        while left[node] != -1:  # not a leaf
            node = left[node] if x[feat[node]] <= thr[node] else right[node]
        return tree["proba1"][node]

    def proba(self, features: np.ndarray) -> np.ndarray:
        X = (np.asarray(features, dtype=float) - self.mu) / self.sigma
        out = np.empty(len(X))
        for i, x in enumerate(X):
            out[i] = np.mean([self._tree_proba(t, x) for t in self.trees])
        return out
```

```python
# scripts/ml/export_rf_json.py
"""CLI: rf_acc_only_live.joblib -> models/rf_acc_only_live.json (round-trip-geprüft)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.deploy.rf_json import export_rf_to_json  # noqa: E402

MODELS = ROOT / "models"


def main() -> None:
    bundle = joblib.load(MODELS / "rf_acc_only_live.joblib")  # first-party model
    model_json = export_rf_to_json(bundle)
    assert json.loads(json.dumps(model_json)) == model_json, "Float-Round-Trip fehlgeschlagen"
    out = MODELS / "rf_acc_only_live.json"
    out.write_text(json.dumps(model_json), encoding="utf-8")
    print(f"-> {out}  ({len(model_json['trees'])} Bäume, {model_json['n_features']} Features, round-trip ok)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, then the export**

Run: `pytest tests/test_rf_json.py -v`
Expected: PASS (2 passed)

Run: `python scripts/ml/export_rf_json.py`
Expected: `-> models/rf_acc_only_live.json (200 Bäume, 30 Features, round-trip ok)`

- [ ] **Step 5: Commit**

```bash
git add src/deploy/__init__.py src/deploy/rf_json.py scripts/ml/export_rf_json.py tests/test_rf_json.py
git commit -m "feat(deploy): RF->JSON Export + Python-Referenz-Evaluator (sklearn-Paritaet)"
```

---

### Task 3: Golden-Vektor-Dumper (End-to-End-Fixture)

Bündelt eine End-to-End-Referenz fürs `ScrybeTests`-Target: N bekannte **Roh-Accel**-Fenster, jeweils mit den 30 invarianten Features, `proba_raw` und HMM-Posterior — alles in voller Float-Präzision, **ohne Filter**. Der Swift-Port assertet Extractor/RF/HMM gegen diese Datei.

**Files:**
- Create: `scripts/ml/dump_golden_vectors.py`
- Test: `tests/test_golden_vectors.py`

**Interfaces:**
- Consumes: `invariant_features` (T1), `RFReferenceEvaluator` + `export_rf_to_json` (T2), `OnlineForwardFilter` (hmm.py).
- Produces: `build_golden_vectors(n_windows: int) -> dict` und JSON `tests/fixtures/golden_vectors.json` mit `{feature_cols, fs_hz, hmm:{transition,priors}, cases:[{raw, features, proba_raw, proba_hmm}]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_golden_vectors.py
import numpy as np

from scripts.ml.dump_golden_vectors import build_golden_vectors


def test_golden_vectors_self_consistent():
    gv = build_golden_vectors(n_windows=8)
    assert len(gv["cases"]) == 8
    assert len(gv["feature_cols"]) == 30
    for case in gv["cases"]:
        assert len(case["features"]) == 30
        assert 0.0 <= case["proba_raw"] <= 1.0
        assert 0.0 <= case["proba_hmm"] <= 1.0


def test_hmm_posterior_is_causal_sequence():
    from src.evaluation.hmm import OnlineForwardFilter
    gv = build_golden_vectors(n_windows=6)
    filt = OnlineForwardFilter(gv["hmm"]["transition"], gv["hmm"]["priors"])
    for case in gv["cases"]:
        expected = filt.step(case["proba_raw"])
        assert abs(expected - case["proba_hmm"]) < 1e-12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_vectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ml.dump_golden_vectors'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/ml/dump_golden_vectors.py
"""End-to-End-Golden-Vektor-Fixture fürs ScrybeTests-Target (Option b, kein Filter).

Pro Fenster: roh-Accel -> 30 invariante Features -> proba_raw -> kausaler HMM-Posterior.
Volle Float-Präzision (json round-trip). Quelle der Roh-Fenster: eine Modern-Session
(raw = userAccel + gravity rekonstruiert = das echte CMSensorRecorder-Signal).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.deploy.rf_json import export_rf_to_json, RFReferenceEvaluator  # noqa: E402
from src.evaluation.hmm import OnlineForwardFilter  # noqa: E402
from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

MODELS = ROOT / "models"
DATA_PROC = ROOT / "data" / "processed"
FIXTURE = ROOT / "tests" / "fixtures" / "golden_vectors.json"
SOURCE_SESSION = "S039"  # P13, Modern (userAccel + gravity vorhanden)


def build_golden_vectors(n_windows: int = 16) -> dict:
    bundle = joblib.load(MODELS / "rf_acc_only_live.joblib")  # first-party model
    cols = bundle["feature_cols"]
    ev = RFReferenceEvaluator(export_rf_to_json(bundle))
    hmm = json.loads((MODELS / "hmm_live.json").read_text())
    A, priors = hmm["transition"], hmm["priors"]
    filt = OnlineForwardFilter(A, priors)

    m = pd.read_csv(DATA_PROC / f"{SOURCE_SESSION}_merged.csv")
    fs = infer_fs_hz(m)
    raw_all = (m[["ax", "ay", "az"]].to_numpy(float)
               + m[["gx", "gy", "gz"]].to_numpy(float))  # CMSensorRecorder-like raw
    win, stride = int(round(fs)), int(round(0.5 * fs))

    cases = []
    for k in range(n_windows):
        s = k * stride
        raw = raw_all[s:s + win]
        if len(raw) < win:
            break
        six = np.column_stack([raw, np.zeros((len(raw), 3))])
        feats = _window_features(six, fs_hz=fs)
        fvec = np.array([feats[c] for c in cols])
        proba_raw = float(ev.proba(fvec[None, :])[0])
        proba_hmm = float(filt.step(proba_raw))
        cases.append({"raw": raw.tolist(), "features": fvec.tolist(),
                      "proba_raw": proba_raw, "proba_hmm": proba_hmm})
    return {"feature_cols": cols, "fs_hz": fs,
            "hmm": {"transition": A, "priors": priors}, "cases": cases}


def main() -> None:
    gv = build_golden_vectors(n_windows=16)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(gv), encoding="utf-8")
    print(f"-> {FIXTURE}  ({len(gv['cases'])} Fälle, {len(gv['feature_cols'])} Features)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, then generate the fixture**

Run: `pytest tests/test_golden_vectors.py -v`
Expected: PASS (2 passed)

Run: `python scripts/ml/dump_golden_vectors.py`
Expected: `-> tests/fixtures/golden_vectors.json (16 Fälle, 30 Features)`

- [ ] **Step 5: Run the full suite + commit**

Run: `pytest tests/ -q`
Expected: alles grün (bestehende + 5 neue Tests).

```bash
git add scripts/ml/dump_golden_vectors.py tests/test_golden_vectors.py tests/fixtures/golden_vectors.json
git commit -m "feat(deploy): End-to-End Golden-Vektor-Fixture (30 invariante Features, kein Filter)"
```

---

## Self-Review

**Spec-Abdeckung (Spec §8 Phase 0, Option b):** Deployment-Modell auf 30 invariante Features ✅ (trainiert); Invarianz-Validierung → Task 1; JSON-Export + Referenz-Evaluator + Paritätstest → Task 2; Golden-Vektor-Dump (kein High-Pass) → Task 3. Float-Präzision (Round-Trip-Selbsttest) → Task 2. Alle Phase-0-Punkte haben eine Task.

**Platzhalter:** keine — jeder Code-Step zeigt vollständigen Code; jeder Run-Step nennt Befehl + erwartete Ausgabe.

**Typ-Konsistenz:** `invariant_features(accel3, fs_hz, cols)` matcht T1↔T1-Test; `export_rf_to_json(bundle) -> dict` + `RFReferenceEvaluator(model_json)` matchen T2-Definition ↔ T3-Nutzung; `build_golden_vectors(n_windows)` matcht T3-Test ↔ Impl; `OnlineForwardFilter(transition, priors).step()` entspricht der bestehenden `src/evaluation/hmm.py`-Signatur.

**Pivot-Hinweis:** Der frühere GravityHighPass-Filter + die High-Pass-Validierung wurden entfernt (Commit `9eeb326`); diese 3 Tasks ersetzen die ursprünglichen 4. Out-of-scope (Phasen 1–3): alle Swift-Units + die R-*-Robustheits-Tickets.
