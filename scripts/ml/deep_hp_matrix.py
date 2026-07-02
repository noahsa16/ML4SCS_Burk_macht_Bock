"""Baut die Deep-HP-Suchphasen-Matrix (Architektur x Sobol-Trial @1 Seed) als JSON."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))
from src.training.deep.hp_search import sobol_configs  # noqa: E402


def _trial_cmd(model: str, name: str, cfg: dict, seed: str | int,
               pool: str, win: str) -> str:
    cmd = (f"python -u scripts/ml/deep_hp_study.py --mode trial "
           f"--model {model} --name {name} "
           f"--pool {pool} --win {win} --seed {seed} --max-epochs 120 "
           f"--lr {cfg['lr']} --dropout {cfg['dropout']} "
           f"--batch-size {cfg['batch_size']} --weight-decay {cfg['weight_decay']} "
           f"--hp-dir models/hp/{pool}")
    return " ".join(cmd.split())


def build() -> dict:
    models_env = (os.environ.get("MODELS", "").strip()
                  or "cnn,tcn,tcn6,lstm,gru,transformer")
    # Why: "none" = reiner CUSTOM-Dispatch (Varianz-Seeds/Boundary-Proben)
    # ohne das volle Sobol-Grid mitzuschleppen.
    models = ([] if models_env == "none"
              else [x for x in models_env.replace(" ", "").split(",") if x])
    pool = os.environ.get("POOL", "").strip() or "legacy"
    win = os.environ.get("WIN", "").strip() or "5"
    n = int(os.environ.get("N_TRIALS", "").strip() or "16")
    seed = os.environ.get("SEED", "").strip() or "42"
    trials_env = os.environ.get("TRIALS", "").strip()
    trials = {int(x) for x in trials_env.split(",") if x} if trials_env else None
    # Why: Seed im Namen haelt Artefakte verschiedener Varianz-Runs
    # kollisionsfrei; Default 42 bleibt namensgleich zur Suchphase.
    suffix = "" if seed == "42" else f"-s{seed}"
    inc = []
    for model in models:
        for t, c in enumerate(sobol_configs(n, seed=0)):
            if trials is not None and t not in trials:
                continue
            name = f"{model}-t{t}{suffix}"
            inc.append({"name": name,
                        "cmd": _trial_cmd(model, name, c, seed, pool, win)})
    for e in json.loads(os.environ.get("CUSTOM", "").strip() or "[]"):
        e_seed = e.get("seed", seed)
        name = e.get("name", f"{e['model']}-custom-s{e_seed}")
        inc.append({"name": name,
                    "cmd": _trial_cmd(e["model"], name, e, e_seed, pool, win)})
    if not inc:
        raise SystemExit("Matrix leer -- MODELS=none ohne CUSTOM-Eintraege?")
    return {"include": inc}


if __name__ == "__main__":
    print(json.dumps(build()))
