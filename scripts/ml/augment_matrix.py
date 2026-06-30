"""Baut die Augmentation-A/B-Matrix (Seed x {aug, no-aug}) als JSON.

Jede (Seed, Bedingung)-Kombination wird EIN paralleler GitHub-Actions-Job,
statt alle sequentiell in einem Job zu fahren (das lief auf einem CPU-Runner
in den 6-h-Bereich). Bei 3 Seeds -> 6 Jobs parallel; Wall-Time ~ ein einzelner
LOSO-Lauf statt 6x.

Env-Eingaben (alle optional, Defaults = Headline-Konfig):
  SEEDS  Leerzeichen- oder Komma-getrennte Seed-Liste (Default "42 43 44")
  MODEL  Deep-Modell (Default "tcn6")
  POOL   "modern" | "legacy" (Default "modern")
  WIN    Input-Fenster in s (Default "5")

Gibt eine Zeile aus: {"include": [{"name": ..., "cmd": ...}, ...]}
Die collect-Stufe (scripts/ml/augment_ab_collect.py) erkennt die Bedingung am
Job-Namen-Suffix ("-aug" vs "-noaug").
"""
from __future__ import annotations

import json
import os


def _seeds() -> list[str]:
    raw = (os.environ.get("SEEDS", "").strip() or "42 43 44").replace(",", " ")
    return [s.strip() for s in raw.split() if s.strip()]


def build() -> dict:
    model = os.environ.get("MODEL", "").strip() or "tcn6"
    pool = os.environ.get("POOL", "").strip() or "modern"
    win = os.environ.get("WIN", "").strip() or "5"
    inc: list[dict] = []
    for seed in _seeds():
        for cond, flag in (("noaug", ""), ("aug", "--augment")):
            cmd = (
                f"python -u -m src.training.deep --model {model} --pool {pool} "
                f"--win {win} --seed {seed} {flag}"
            )
            inc.append({"name": f"s{seed}-{cond}", "cmd": " ".join(cmd.split())})
    return {"include": inc}


if __name__ == "__main__":
    print(json.dumps(build()))
