"""Baut die Deep-HP-Suchphasen-Matrix (Architektur x Sobol-Trial @1 Seed) als JSON."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
from src.training.deep.hp_search import sobol_configs  # noqa: E402


def build() -> dict:
    models = [x for x in (os.environ.get("MODELS", "").strip()
              or "cnn,tcn,tcn6,lstm,gru,transformer").replace(" ", "").split(",") if x]
    pool = os.environ.get("POOL", "").strip() or "legacy"
    win = os.environ.get("WIN", "").strip() or "5"
    n = int(os.environ.get("N_TRIALS", "").strip() or "16")
    seed = os.environ.get("SEED", "").strip() or "42"
    inc = []
    for model in models:
        for t, c in enumerate(sobol_configs(n, seed=0)):
            cmd = (f"python -u -m src.training.deep --model {model} --pool {pool} "
                   f"--win {win} --seed {seed} --max-epochs 120 "
                   f"--lr {c['lr']} --dropout {c['dropout']} "
                   f"--batch-size {c['batch_size']} --weight-decay {c['weight_decay']}")
            inc.append({"name": f"{model}-t{t}", "cmd": " ".join(cmd.split())})
    return {"include": inc}


if __name__ == "__main__":
    print(json.dumps(build()))
