"""Baut die GitHub-Actions-Sweep-Matrix als JSON aus Umgebungs-Eingaben.

Der ``prepare``-Job ruft das Skript; die Eingaben kommen aus den
``workflow_dispatch``-Feldern (Self-Service) bzw. sind beim ``schedule``-Lauf
leer → dann greifen hier die Defaults (= die volle kuratierte Matrix). So
braucht es zum Variieren der Parameter kein YAML-Editieren mehr.

Env-Eingaben (alle optional). Leer/ungesetzt → Default (so läuft der Cron auf
der vollen Matrix, ohne Eingaben); ``none`` (bzw. off/-) schaltet die Dimension
gezielt ab:
  MODELS   Komma-Liste der Modelle für den Headline-Config-Lauf
  GAPS     Komma-Liste RF-Label-Gaps in ms (``none`` = aus)
  WINDOWS  Komma-Liste RF-Feature-Fenster in s, 50% Overlap (``none`` = aus)
  EXTRAS   true/false: kuratierte Extras (Overlap-Sweep + SVM/ExtraTrees-HP)

Gibt eine Zeile aus: {"include": [{"name": ..., "cmd": ...}, ...]}
"""
from __future__ import annotations

import json
import os

DEEP = {"cnn", "lstm", "gru", "tcn"}
ALL_MODELS = ["rf", "extratrees", "histgb", "logreg", "svm_rbf", "mlp",
              "cnn", "lstm", "gru", "tcn"]


def _list(env: str, default: str) -> list[str]:
    # leer/ungesetzt → Default (Cron-tauglich); "none" → Dimension aus.
    raw = os.environ.get(env, "").strip() or default
    if raw.lower() in ("none", "off", "-", "skip"):
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _bool(env: str, default: bool = True) -> bool:
    v = os.environ.get(env, "").strip().lower()
    return default if v == "" else v in ("true", "1", "yes", "y")


def _classical(model: str, extra: str = "") -> str:
    cmd = f"python -m src.training.train_loso --pool legacy --model {model} {extra}--save-cv-csv"
    return " ".join(cmd.split())  # doppelte Spaces glätten


def _cmd_for(model: str) -> str:
    if model in DEEP:
        return f"python -m src.training.deep --model {model} --pool legacy"
    return _classical(model)


def build() -> dict:
    inc: list[dict] = []
    # Modell-Sweep (Headline-Config)
    for m in _list("MODELS", ",".join(ALL_MODELS)):
        inc.append({"name": m, "cmd": _cmd_for(m)})
    # RF Label-Gap-Sweep
    for g in _list("GAPS", "300,1000,2000,3000"):
        inc.append({"name": f"rf-gap{g}", "cmd": _classical("rf", f"--max-gap-ms {g} ")})
    # RF Feature-Fenster-Sweep (50% Overlap)
    for w in _list("WINDOWS", "3,5"):
        inc.append({"name": f"rf-win{w}", "cmd": _classical("rf", f"--window-sec {w} ")})
    # Kuratierte Extras: Overlap-Sweep + SVM/ExtraTrees-Hyperparameter
    if _bool("EXTRAS", True):
        inc += [
            {"name": "rf-nozscore", "cmd": _classical("rf", "--no-zscore ")},
            {"name": "rf-trees100", "cmd": _classical("rf", "--n-estimators 100 ")},
            {"name": "rf-trees400", "cmd": _classical("rf", "--n-estimators 400 ")},
            {"name": "wsweep-w2", "cmd": "python scripts/ml/sweep_window_size.py --pool legacy --models --config 2,1 --config 2,0.5"},
            {"name": "wsweep-w3", "cmd": "python scripts/ml/sweep_window_size.py --pool legacy --models --config 3,1.5 --config 3,1"},
            {"name": "wsweep-w5", "cmd": "python scripts/ml/sweep_window_size.py --pool legacy --models --config 5,2.5 --config 5,1"},
            {"name": "svm-C0.1", "cmd": _classical("svm_rbf", '--model-params \'{"C": 0.1}\' ')},
            {"name": "svm-C10", "cmd": _classical("svm_rbf", '--model-params \'{"C": 10}\' ')},
            {"name": "svm-gammaAuto", "cmd": _classical("svm_rbf", '--model-params \'{"gamma": "auto"}\' ')},
            {"name": "et-depth12", "cmd": _classical("extratrees", '--model-params \'{"max_depth": 12}\' ')},
            {"name": "et-sqrt", "cmd": _classical("extratrees", '--model-params \'{"max_features": "sqrt"}\' ')},
        ]
    return {"include": inc}


if __name__ == "__main__":
    print(json.dumps(build()))
