"""Baut die GitHub-Actions-Sweep-Matrix als JSON aus Umgebungs-Eingaben.

Der ``prepare``-Job ruft das Skript; die Eingaben kommen aus den
``workflow_dispatch``-Feldern (Self-Service) bzw. sind beim ``schedule``-Lauf
leer.

**Cron (leere Eingaben) faehrt nur die drei HEADLINE-Familien auf BEIDEN Pools:**
  1. Deep auf langen Fenstern (cnn/tcn/tcn6 @5/10 s, lstm/gru @5 s)
  2. MLP mit Hyperparameter-Tuning
  3. RF + HMM-Post-Processing
Der alte breite Explorations-Sweep ist hinter ``BROAD=true`` verborgen
(Dispatch-only), laeuft also nicht mehr automatisch.

Env-Eingaben (alle optional; leer/Cron -> Headline-Default):
  POOLS        Komma-Liste Pools (Default "legacy,modern"); ``none`` = aus
  DEEP_MODELS  Override der Nightly-Deep-Liste als ``model:win``-Paare
               (z. B. "transformer:5"); leer -> Default NIGHTLY_DEEP (ohne
               transformer). transformer ist bewusst nur per Override dabei.
  AUGMENT      "on"/"off" (Default off): Deep-Configs zusaetzlich mit --augment
  BROAD        true/false (Default false): statt Headline den alten breiten
               Sweep fahren. Nur dann sind MODELS/GAPS/WINDOWS/EXTRAS/DEEP_WINS
               relevant.

Gibt eine Zeile aus: {"include": [{"name": ..., "cmd": ...}, ...]}
"""
from __future__ import annotations

import json
import os

# --- Headline-Konfiguration ------------------------------------------------

# Nightly-Deep: (model, win). lstm/gru nur @5 s (sequentiell/teuer auf CPU);
# cnn/tcn spannen 5 + 10 s. transformer NICHT im Default (N<=15 -> teuer +
# voraussichtlich unter TCN; via DEEP_MODELS="transformer:5" dispatchbar).
NIGHTLY_DEEP: list[tuple[str, int]] = [
    ("cnn", 5), ("tcn", 5), ("tcn6", 5), ("tcn", 10), ("lstm", 5), ("gru", 5),
]
# MLP-HP-Gitter: (Label, model-params-JSON). hidden_layer_sizes als Liste —
# sklearn akzeptiert das, JSON kennt keine Tupel.
MLP_GRID: list[tuple[str, str]] = [
    ("h128-a1e4", '{"hidden_layer_sizes": [128], "alpha": 0.0001}'),
    ("h128-64-a1e4", '{"hidden_layer_sizes": [128, 64], "alpha": 0.0001}'),
    ("h128-64-a1e3", '{"hidden_layer_sizes": [128, 64], "alpha": 0.001}'),
    ("h256-128-a1e4", '{"hidden_layer_sizes": [256, 128], "alpha": 0.0001}'),
]

# --- Broad-Sweep (Dispatch-only, alter Default) ----------------------------

DEEP_BROAD = {"cnn", "lstm", "gru", "tcn"}
ALL_MODELS = ["rf", "extratrees", "histgb", "logreg", "svm_rbf", "mlp",
              "cnn", "lstm", "gru", "tcn"]


def _list(env: str, default: str) -> list[str]:
    raw = os.environ.get(env, "").strip() or default
    if raw.lower() in ("none", "off", "-", "skip"):
        return []
    return [x.strip() for x in raw.replace(" ", "").split(",") if x.strip()]


def _bool(env: str, default: bool = False) -> bool:
    v = os.environ.get(env, "").strip().lower()
    return default if v == "" else v in ("true", "1", "yes", "y", "on")


def _classical(model: str, pool: str, extra: str = "") -> str:
    cmd = (f"python -m src.training.train_loso --pool {pool} --model {model} "
           f"{extra}--save-cv-csv")
    return " ".join(cmd.split())


def _nightly_deep() -> list[tuple[str, int]]:
    """Default NIGHTLY_DEEP, oder Override via DEEP_MODELS='model:win,...'."""
    raw = os.environ.get("DEEP_MODELS", "").strip()
    if not raw or raw.lower() in ("none", "off"):
        return NIGHTLY_DEEP
    out: list[tuple[str, int]] = []
    for tok in raw.replace(" ", "").split(","):
        if ":" in tok:
            m, w = tok.split(":", 1)
            out.append((m, int(w)))
    return out or NIGHTLY_DEEP


def _headline(pools: list[str], augment: bool) -> list[dict]:
    inc: list[dict] = []
    deep_models = _nightly_deep()
    aug_variants = [""] + (["--augment"] if augment else [])
    for pool in pools:
        # 1. Deep auf langen Fenstern
        for model, win in deep_models:
            for aug in aug_variants:
                sfx = "-aug" if aug else ""
                cmd = (f"python -u -m src.training.deep --model {model} "
                       f"--pool {pool} --win {win} {aug}")
                inc.append({"name": f"deep-{model}{win}s-{pool}{sfx}",
                            "cmd": " ".join(cmd.split())})
        # 2. MLP-Hyperparameter-Tuning
        for label, params in MLP_GRID:
            inc.append({"name": f"mlp-{label}-{pool}",
                        "cmd": _classical("mlp", pool, f"--model-params '{params}' ")})
        # 3. RF + HMM (pro Pool eigene OOF/cv, sonst kollidiert/fehlt modern)
        suff = "" if pool == "legacy" else f"_{pool}"
        cmd = (f"python -m src.training.train_loso --pool {pool} --save-oof && "
               f"python scripts/ml/hmm_postprocess_loso.py "
               f"--oof models/loso_oof{suff}.csv "
               f"--out models/hmm_postprocess{suff}_cv.csv")
        inc.append({"name": f"rf-hmm-{pool}", "cmd": cmd})
    return inc


def _broad() -> list[dict]:
    """Der alte breite Explorations-Sweep (legacy-Pool, 1-s-Vergleich +
    gap/window/extras/deep_wins). Nur bei BROAD=true."""
    inc: list[dict] = []
    for m in _list("MODELS", ",".join(ALL_MODELS)):
        cmd = (f"python -m src.training.deep --model {m} --pool legacy"
               if m in DEEP_BROAD else _classical(m, "legacy"))
        inc.append({"name": m, "cmd": cmd})
    for g in _list("GAPS", "300,1000,2000,3000"):
        inc.append({"name": f"rf-gap{g}", "cmd": _classical("rf", "legacy", f"--max-gap-ms {g} ")})
    for w in _list("WINDOWS", "3,5"):
        inc.append({"name": f"rf-win{w}", "cmd": _classical("rf", "legacy", f"--window-sec {w} ")})
    if _bool("EXTRAS", True):
        inc += [
            {"name": "rf-nozscore", "cmd": _classical("rf", "legacy", "--no-zscore ")},
            {"name": "rf-trees100", "cmd": _classical("rf", "legacy", "--n-estimators 100 ")},
            {"name": "rf-trees400", "cmd": _classical("rf", "legacy", "--n-estimators 400 ")},
            {"name": "wsweep-w2", "cmd": "python scripts/ml/sweep_window_size.py --pool legacy --models --config 2,1 --config 2,0.5"},
            {"name": "wsweep-w3", "cmd": "python scripts/ml/sweep_window_size.py --pool legacy --models --config 3,1.5 --config 3,1"},
            {"name": "wsweep-w5", "cmd": "python scripts/ml/sweep_window_size.py --pool legacy --models --config 5,2.5 --config 5,1"},
            {"name": "svm-C0.1", "cmd": _classical("svm_rbf", "legacy", '--model-params \'{"C": 0.1}\' ')},
            {"name": "svm-C10", "cmd": _classical("svm_rbf", "legacy", '--model-params \'{"C": 10}\' ')},
            {"name": "et-depth12", "cmd": _classical("extratrees", "legacy", '--model-params \'{"max_depth": 12}\' ')},
        ]
    deep_wins = _list("DEEP_WINS", "none")
    for w in deep_wins:
        for m in ("cnn", "tcn"):
            inc.append({"name": f"{m}-win{w}",
                        "cmd": f"python -m src.training.deep --model {m} --pool legacy --win {w}"})
    if "5" in deep_wins:
        inc.append({"name": "tcn6-win5",
                    "cmd": "python -m src.training.deep --model tcn6 --pool legacy --win 5"})
    return inc


def build() -> dict:
    if _bool("BROAD", False):
        return {"include": _broad()}
    pools = _list("POOLS", "legacy,modern")
    return {"include": _headline(pools, _bool("AUGMENT", False))}


if __name__ == "__main__":
    print(json.dumps(build()))
