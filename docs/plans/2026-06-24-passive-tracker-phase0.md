# Passiver Tracker — Phase 0 (Python-Fundament) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das hier-verifizierbare Python-Fundament für die On-Device-Inferenz bauen — High-Pass-Validierung, ein round-trip-fähiger RF→JSON-Export mit Python-Referenz-Evaluator, und eine Golden-Vektor-Fixture — sodass der spätere Swift-Port (Phasen 1–3) gegen eine bewiesene, bit-genaue Referenz portiert wird.

**Architecture:** Reine Python-/numpy-Bausteine, die die On-Device-Pipeline 1:1 spiegeln: `GravityHighPass` (Komplementärfilter, approximiert userAcceleration aus Roh-Accel) → die 47 acc-only-Features aus `src/features/windows.py` → ein aus JSON rekonstruierter RF (`RFReferenceEvaluator`) → der kausale `OnlineForwardFilter` (HMM). Jeder Baustein ist isoliert testbar; die Golden-Vektoren bündeln eine End-to-End-Referenz für das Swift-Test-Target.

**Tech Stack:** Python 3, numpy, pandas, scikit-learn, joblib, pytest. Bestehende Module: `src/features/windows.py` (`_window_features`), `src/evaluation/hmm.py` (`OnlineForwardFilter`), `scripts/ml/acc_only_loso.py` (`_is_gyro_feature`), `scripts/ml/passive_raw_accel_loso.py` (Roh-Accel-Reconstruction). Artefakt: `models/rf_acc_only_live.joblib` (trainiert), `models/hmm_live.json`.

## Global Constraints

- Pfade immer relativ zum Repo-Root via `ROOT = Path(__file__).resolve().parents[N]`; keine absoluten Pfade.
- `pytest tests/` muss nach jeder Task grün bleiben.
- **Volle Float-Präzision** an jeder Serialisierungs-Grenze: Pythons `json` nutzt round-trip-fähige `repr`-Floats (shortest-round-trip seit 3.1) — der Export enthält einen **Round-Trip-Selbsttest** (`json.loads(json.dumps(x)) == x` exakt). Keine gerundeten Thresholds/µ/σ.
- Feature-Reihenfolge IMMER aus `bundle["feature_cols"]` lesen (die 47 acc-only-Namen in Modell-Reihenfolge) — nie neu ableiten.
- Branch: `feature/on-device-inference`. Häufige Commits, ein Commit pro Task.
- Modell-Bundle-Schema (aus `train_acc_only_live.py`): `{model, feature_cols, zscore_mu: dict, zscore_sigma: dict, sample_rate_hz, ...}`.

---

### Task 1: `GravityHighPass` Referenz-Filter

Der Komplementärfilter, der on-device aus der rohen Gesamtbeschleunigung das `userAcceleration`-Signal approximiert. Stateful (laufende Gravity-Schätzung) → spiegelt den resumierbaren Swift-Port. Dies ist die Referenz, gegen die der Swift-Filter in der Golden-Vektor-Parität geprüft wird.

**Files:**
- Create: `src/features/gravity_highpass.py`
- Test: `tests/test_gravity_highpass.py`

**Interfaces:**
- Produces: `GravityHighPass(alpha: float = 0.9)` mit `process(raw: np.ndarray) -> np.ndarray` (raw `(N,3)` → userAccel `(N,3)`), `state -> list|None`, `restore(state)`, `reset()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gravity_highpass.py
import numpy as np
from src.features.gravity_highpass import GravityHighPass


def test_removes_constant_gravity():
    rng = np.random.default_rng(0)
    n = 500
    gravity = np.array([0.0, 0.0, 1.0])
    dynamic = 0.05 * rng.standard_normal((n, 3))
    raw = gravity + dynamic
    user = GravityHighPass(alpha=0.9).process(raw)
    # after warmup the constant gravity component is gone -> mean ~0
    assert np.allclose(user[100:].mean(axis=0), 0.0, atol=0.02)


def test_state_continuity_matches_whole_pass():
    rng = np.random.default_rng(1)
    raw = np.array([0.0, 0.0, 1.0]) + 0.1 * rng.standard_normal((200, 3))
    whole = GravityHighPass(0.9).process(raw)

    hp = GravityHighPass(0.9)
    first = hp.process(raw[:120])
    saved = hp.state
    resumed = GravityHighPass(0.9)
    resumed.restore(saved)
    second = resumed.process(raw[120:])

    assert np.allclose(np.vstack([first, second]), whole)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gravity_highpass.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.features.gravity_highpass'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/features/gravity_highpass.py
"""Komplementär-/High-Pass-Filter: trennt die langsam veränderliche Schwerkraft
von der rohen Gesamtbeschleunigung und approximiert CoreMotions userAcceleration.

    gravity_t = alpha * gravity_{t-1} + (1 - alpha) * raw_t
    user_t    = raw_t - gravity_t

Stateful (die laufende Gravity-Schätzung trägt über Aufrufe hinweg), damit der
Filter zum live-resumierbaren Swift-Port passt. alpha nahe 1 = träge Gravity.
Referenz für die Golden-Vektor-Parität (R-Axis/High-Pass).
"""
from __future__ import annotations

import numpy as np


class GravityHighPass:
    def __init__(self, alpha: float = 0.9):
        self.alpha = float(alpha)
        self._gravity: np.ndarray | None = None

    @property
    def state(self) -> list | None:
        return None if self._gravity is None else self._gravity.tolist()

    def restore(self, state) -> None:
        self._gravity = None if state is None else np.asarray(state, dtype=float).copy()

    def reset(self) -> None:
        self._gravity = None

    def process(self, raw: np.ndarray) -> np.ndarray:
        raw = np.asarray(raw, dtype=float)
        out = np.empty_like(raw)
        g = self._gravity
        a = self.alpha
        for i in range(len(raw)):
            g = raw[i].copy() if g is None else a * g + (1.0 - a) * raw[i]
            out[i] = raw[i] - g
        self._gravity = g
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gravity_highpass.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/features/gravity_highpass.py tests/test_gravity_highpass.py
git commit -m "feat(deploy): GravityHighPass Komplementaerfilter (Roh-Accel -> userAccel)"
```

---

### Task 2: High-Pass-Validierung auf Modern-Sessions

Misst, ob der High-Pass (Option c der Spec) trägt: auf den Modern-Sessions (P12–P15, P17) ist `raw = userAccel + gravity` rekonstruierbar; der Filter darauf soll die *echte* `userAcceleration` treffen. Geprüft auf Feature- und Prediction-Ebene, plus der Failure-Mode anhaltende Rotation. Das ist das Entscheidungs-Gate: trägt (c), bleibt das Modell unangetastet; sonst Rückfall auf (a)/(b).

**Files:**
- Create: `scripts/ml/validate_highpass.py`
- Test: `tests/test_validate_highpass.py`

**Interfaces:**
- Consumes: `GravityHighPass` (Task 1).
- Produces: `highpass_feature_agreement(true_user, raw, fs_hz, feature_cols, alpha) -> dict` mit Keys `rmse`, `max_abs`, `corr` (Mittel über Feature-Spalten, true-userAccel-Features vs. highpass-Features). CLI `python scripts/ml/validate_highpass.py [--alpha 0.9]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate_highpass.py
import numpy as np
from scripts.ml.validate_highpass import highpass_feature_agreement


def test_agreement_high_for_synthetic_useraccel():
    # synthetic: true userAccel is mean-zero dynamic; raw = userAccel + constant gravity
    rng = np.random.default_rng(0)
    n, fs = 600, 50.0
    true_user = np.column_stack([
        0.1 * np.sin(2 * np.pi * 4 * np.arange(n) / fs),
        0.1 * rng.standard_normal(n),
        0.1 * np.cos(2 * np.pi * 3 * np.arange(n) / fs),
    ])
    raw = true_user + np.array([0.0, 0.0, 1.0])
    cols = ["ax_std", "ay_std", "az_std", "ax_jerk_std"]
    out = highpass_feature_agreement(true_user, raw, fs, cols, alpha=0.9)
    # dynamic, mean-invariant features should agree well after high-pass
    assert out["corr"] > 0.95
    assert out["max_abs"] < 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validate_highpass.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ml.validate_highpass'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/ml/validate_highpass.py
"""Validiert den GravityHighPass gegen echte userAcceleration (Modern-Sessions).

raw = userAccel + gravity ist aus den Modern-Sessions rekonstruierbar; der Filter
darauf soll die echte userAccel treffen. Entscheidet, ob Option (c) High-Pass das
Roh-Accel-Problem löst, ohne das Modell anzufassen.

CLI: python scripts/ml/validate_highpass.py [--alpha 0.9]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.gravity_highpass import GravityHighPass  # noqa: E402
from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODERN = [("S038", "P12"), ("S039", "P13"), ("S040", "P14"),
          ("S041", "P15"), ("S043", "P17")]


def _features_over(samples: np.ndarray, fs_hz: float, cols: list[str]) -> np.ndarray:
    """Build 1 s / 0.5 s windows of accel-only feature rows, restricted to cols.

    samples: (N,3) accel; gyro columns are zero-filled so _window_features runs,
    then only the requested acc-only cols are kept.
    """
    win = int(round(1.0 * fs_hz))
    stride = int(round(0.5 * fs_hz))
    six = np.column_stack([samples, np.zeros((len(samples), 3))])
    rows = []
    for start in range(0, len(six) - win + 1, stride):
        feats = _window_features(six[start:start + win], fs_hz=fs_hz)
        rows.append([feats[c] for c in cols])
    return np.asarray(rows, dtype=float)


def highpass_feature_agreement(true_user, raw, fs_hz, feature_cols, alpha=0.9) -> dict:
    f_true = _features_over(np.asarray(true_user, float), fs_hz, feature_cols)
    f_hp = _features_over(GravityHighPass(alpha).process(raw), fs_hz, feature_cols)
    n = min(len(f_true), len(f_hp))
    f_true, f_hp = f_true[:n], f_hp[:n]
    diff = f_true - f_hp
    cols_corr = []
    for j in range(f_true.shape[1]):
        if f_true[:, j].std() > 1e-9 and f_hp[:, j].std() > 1e-9:
            cols_corr.append(np.corrcoef(f_true[:, j], f_hp[:, j])[0, 1])
    return {
        "rmse": float(np.sqrt(np.mean(diff ** 2))),
        "max_abs": float(np.max(np.abs(diff))) if diff.size else float("nan"),
        "corr": float(np.mean(cols_corr)) if cols_corr else float("nan"),
    }


def run(alpha: float) -> None:
    import joblib
    bundle = joblib.load(ROOT / "models" / "rf_acc_only_live.joblib")
    cols = bundle["feature_cols"]
    print(f"alpha={alpha}  features={len(cols)}\n")
    for sid, pid in MODERN:
        merged = pd.read_csv(DATA_PROC / f"{sid}_merged.csv")
        fs = infer_fs_hz(merged)
        true_user = merged[["ax", "ay", "az"]].to_numpy(float)
        raw = true_user + merged[["gx", "gy", "gz"]].to_numpy(float)
        out = highpass_feature_agreement(true_user, raw, fs, cols, alpha)
        print(f"  {pid} ({sid}): corr={out['corr']:.4f}  rmse={out['rmse']:.4f}  "
              f"max_abs={out['max_abs']:.4f}")
    print("\nVerdikt: corr→1 / kleine rmse über alle = High-Pass trägt (Option c).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alpha", type=float, default=0.9)
    run(ap.parse_args().alpha)
```

- [ ] **Step 4: Run test, then the real validation**

Run: `pytest tests/test_validate_highpass.py -v`
Expected: PASS (1 passed)

Run: `python scripts/ml/validate_highpass.py`
Expected: eine Zeile pro Modern-Proband mit `corr`/`rmse`/`max_abs`. **Entscheidung:** ist `corr` über alle fünf hoch (≳0.95) und `rmse` klein, trägt Option (c) — Modell bleibt unangetastet. Sonst im Plan-Issue vermerken und auf (a)/(b) ausweichen.

- [ ] **Step 5: Commit**

```bash
git add scripts/ml/validate_highpass.py tests/test_validate_highpass.py
git commit -m "feat(deploy): High-Pass-Validierung gegen echte userAccel (Modern-Sessions)"
```

---

### Task 3: RF → JSON Export + `RFReferenceEvaluator` + Parität

Serialisiert den trainierten RF in ein round-trip-fähiges JSON (pro Baum: Arrays) und baut einen pure-Python-Evaluator, der aus dem JSON sklearns `predict_proba` exakt reproduziert. Der Parität-Test ist die Spezifikation, die der Swift-`RFEvaluator` treffen muss.

**Files:**
- Create: `src/deploy/__init__.py`
- Create: `src/deploy/rf_json.py`
- Create: `scripts/ml/export_rf_json.py`
- Test: `tests/test_rf_json.py`

**Interfaces:**
- Produces: `export_rf_to_json(bundle: dict) -> dict`; `RFReferenceEvaluator(model_json: dict)` mit `proba(features: np.ndarray) -> np.ndarray` (features `(N, n_feat)` in `feature_cols`-Reihenfolge, **vor** Z-Score; der Evaluator wendet das gebackene µ/σ selbst an).

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
    # every threshold survives JSON round-trip bit-for-bit
    for t_orig, t_re in zip(model_json["trees"], reloaded["trees"]):
        assert t_orig["threshold"] == t_re["threshold"]
    assert model_json["zscore_mu"] == reloaded["zscore_mu"]


def test_reference_evaluator_matches_sklearn():
    bundle = _bundle()
    model_json = export_rf_to_json(bundle)
    ev = RFReferenceEvaluator(model_json)

    rng = np.random.default_rng(0)
    n_feat = len(bundle["feature_cols"])
    # plausible raw (pre-zscore) feature rows
    X = rng.standard_normal((50, n_feat)) * 2.0
    mu = np.array([bundle["zscore_mu"][c] for c in bundle["feature_cols"]])
    sigma = np.array([bundle["zscore_sigma"][c] for c in bundle["feature_cols"]])
    Xz = (X - mu) / sigma
    expected = bundle["model"].predict_proba(Xz)[:, 1]

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
        # class-1 Wahrscheinlichkeit pro Knoten (Leaves relevant): value[node][0]
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
    bundle = joblib.load(MODELS / "rf_acc_only_live.joblib")
    model_json = export_rf_to_json(bundle)
    # Round-Trip-Selbsttest: Floats müssen bit-exakt überleben.
    assert json.loads(json.dumps(model_json)) == model_json, "Float-Round-Trip fehlgeschlagen"
    out = MODELS / "rf_acc_only_live.json"
    out.write_text(json.dumps(model_json), encoding="utf-8")
    n_trees = len(model_json["trees"])
    print(f"-> {out}  ({n_trees} Bäume, {model_json['n_features']} Features, round-trip ok)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test, then the export**

Run: `pytest tests/test_rf_json.py -v`
Expected: PASS (2 passed)

Run: `python scripts/ml/export_rf_json.py`
Expected: `-> models/rf_acc_only_live.json (200 Bäume, 47 Features, round-trip ok)`

- [ ] **Step 5: Commit**

```bash
git add src/deploy/__init__.py src/deploy/rf_json.py scripts/ml/export_rf_json.py tests/test_rf_json.py
git commit -m "feat(deploy): RF->JSON Export + Python-Referenz-Evaluator (sklearn-Paritaet)"
```

---

### Task 4: Golden-Vektor-Dumper (End-to-End-Fixture)

Bündelt eine End-to-End-Referenz für das spätere `ScrybeTests`-Target: N bekannte Roh-Accel-Fenster, jeweils mit erwartetem High-Pass-Output, 47 Features, `proba_raw` und HMM-Posterior — alles in voller Float-Präzision. Der Swift-Port assertet HighPass/Extractor/RF/HMM gegen diese Datei.

**Files:**
- Create: `scripts/ml/dump_golden_vectors.py`
- Test: `tests/test_golden_vectors.py`

**Interfaces:**
- Consumes: `GravityHighPass` (T1), `RFReferenceEvaluator` + `export_rf_to_json` (T3), `_window_features` (windows.py), `OnlineForwardFilter` (hmm.py).
- Produces: `build_golden_vectors(n_windows: int) -> dict` und JSON `tests/fixtures/golden_vectors.json` mit `{feature_cols, cases: [{raw:[[..3..]], user:[[..3..]], features:[..47..], proba_raw, proba_hmm}], hmm:{transition, priors}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_golden_vectors.py
import numpy as np

from scripts.ml.dump_golden_vectors import build_golden_vectors


def test_golden_vectors_self_consistent():
    gv = build_golden_vectors(n_windows=8)
    assert len(gv["cases"]) == 8
    assert len(gv["feature_cols"]) == 47
    for case in gv["cases"]:
        # shapes
        assert len(case["features"]) == 47
        assert np.shape(case["raw"]) == np.shape(case["user"])
        # proba in [0,1]
        assert 0.0 <= case["proba_raw"] <= 1.0
        assert 0.0 <= case["proba_hmm"] <= 1.0


def test_hmm_posterior_is_causal_sequence():
    # the HMM posterior of case k must equal stepping the filter over cases 0..k
    from src.evaluation.hmm import OnlineForwardFilter
    gv = build_golden_vectors(n_windows=6)
    A = gv["hmm"]["transition"]
    priors = gv["hmm"]["priors"]
    filt = OnlineForwardFilter(A, priors)
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
"""Erzeugt die End-to-End-Golden-Vektor-Fixture fürs ScrybeTests-Target.

Pro Fenster: roh-Accel -> GravityHighPass -> userAccel -> 47 Features -> proba_raw
-> kausaler HMM-Posterior. Volle Float-Präzision (json round-trip). Quelle der
Roh-Fenster: eine bekannte Modern-Session (raw = userAccel + gravity rekonstruiert).
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
from src.features.gravity_highpass import GravityHighPass  # noqa: E402
from src.features.windows import _window_features, infer_fs_hz  # noqa: E402

MODELS = ROOT / "models"
DATA_PROC = ROOT / "data" / "processed"
FIXTURE = ROOT / "tests" / "fixtures" / "golden_vectors.json"
SOURCE_SESSION = "S039"  # P13, Modern (userAccel + gravity vorhanden)


def build_golden_vectors(n_windows: int = 16) -> dict:
    bundle = joblib.load(MODELS / "rf_acc_only_live.joblib")
    cols = bundle["feature_cols"]
    ev = RFReferenceEvaluator(export_rf_to_json(bundle))
    hmm_params = json.loads((MODELS / "hmm_live.json").read_text())
    A, priors = hmm_params["transition"], hmm_params["priors"]
    filt = OnlineForwardFilter(A, priors)

    merged = pd.read_csv(DATA_PROC / f"{SOURCE_SESSION}_merged.csv")
    fs = infer_fs_hz(merged)
    raw_all = (merged[["ax", "ay", "az"]].to_numpy(float)
               + merged[["gx", "gy", "gz"]].to_numpy(float))
    win, stride = int(round(fs)), int(round(0.5 * fs))

    cases = []
    for k in range(n_windows):
        s = k * stride
        raw = raw_all[s:s + win]
        if len(raw) < win:
            break
        user = GravityHighPass(0.9).process(raw)
        six = np.column_stack([user, np.zeros((len(user), 3))])
        feats = _window_features(six, fs_hz=fs)
        fvec = np.array([feats[c] for c in cols])
        proba_raw = float(ev.proba(fvec[None, :])[0])
        proba_hmm = float(filt.step(proba_raw))
        cases.append({
            "raw": raw.tolist(),
            "user": user.tolist(),
            "features": fvec.tolist(),
            "proba_raw": proba_raw,
            "proba_hmm": proba_hmm,
        })
    return {"feature_cols": cols, "fs_hz": fs, "alpha": 0.9,
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
Expected: `-> tests/fixtures/golden_vectors.json (16 Fälle, 47 Features)`

- [ ] **Step 5: Run the full suite + commit**

Run: `pytest tests/ -q`
Expected: alles grün (bestehende + 6 neue Tests).

```bash
git add scripts/ml/dump_golden_vectors.py tests/test_golden_vectors.py tests/fixtures/golden_vectors.json
git commit -m "feat(deploy): End-to-End Golden-Vektor-Fixture fuer den Swift-Port"
```

---

## Self-Review

**Spec-Abdeckung (Spec §8 Phase 0):** acc-only-Modell ✅ (vorhanden); High-Pass-Validierung → Task 1+2; Python-Referenzfilter → Task 1; JSON-Export → Task 3; Referenz-Evaluator + Paritätstest → Task 3; Golden-Vektor-Dump inkl. High-Pass-Stufe → Task 4. Float-Präzision (R-Float) → Task 3 Round-Trip-Selbsttest + json-repr. Alle Phase-0-Punkte haben eine Task.

**Platzhalter:** keine — jeder Code-Step zeigt vollständigen Code; jeder Run-Step nennt Befehl + erwartete Ausgabe.

**Typ-Konsistenz:** `export_rf_to_json(bundle) -> dict` und `RFReferenceEvaluator(model_json)` matchen zwischen T3-Definition und T4-Nutzung; `GravityHighPass.process/state/restore` matchen T1↔T2↔T4; `build_golden_vectors(n_windows)` matcht T4-Test↔Impl; `OnlineForwardFilter(A, priors).step()` entspricht der bestehenden `src/evaluation/hmm.py`-Signatur.

**Out-of-scope (spätere Phasen):** Alle Swift-Units (GravityHighPass-Port, AccelFeatureExtractor, RFEvaluator, OnlineForwardFilter-Port, InferenceEngine, PassiveRecorder, PassiveBatchStore, InferenceTrigger, Mode/Interlock) + die Robustheits-Tickets R-* sind Phasen 1–3 und nicht Teil dieses Plans.
