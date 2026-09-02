"""Konvertiert die Deployment-Checkpoints nach Core ML.

Laeuft im isolierten venv:
    .venv-coreml/bin/python scripts/pipeline/export_coreml.py --kind passive

FP32 ist festgenagelt (Spec §7.3): ein einziges Paritaetskriterium auf allen
drei Ebenen, und Core ML kann nicht still auf eine andere Praezision fallen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import coremltools as ct
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
# Why: als Skript gestartet ist sys.path[0] das Skript-Verzeichnis, nicht das
# Repo-Root — ohne diese Zeile scheitert der src-Import. Gleiche Konvention wie
# in den uebrigen scripts/pipeline/*.py.
sys.path.insert(0, str(ROOT))

from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model


def _sha256(path: Path) -> str:
    """SHA-256 einer Datei oder eines Verzeichnisses (rekursiv, pfadsortiert).

    Ein .mlpackage ist ein Verzeichnis — ein Hash ueber eine einzelne Datei
    wuerde stillschweigend nur einen Teil abdecken.
    """
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(path)).encode())
                h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()

OUT_DIR = ROOT / "models" / "coreml"
OUT_NAMES = {"active": "ScrybeActive", "passive": "ScrybePassive"}

# Step 1: `.venv-coreml/bin/python -c "import coremltools as ct; print([t for t
# in dir(ct.target) if not t.startswith('_')])"` -> iOS13..iOS18, iOS26 sind
# verfuegbar. Ziel ist iOS16, nicht iOS17: die WatchStreamer-App setzt
# IPHONEOS_DEPLOYMENT_TARGET nicht selbst und erbt den Projekt-Default 16.0
# (project.pbxproj, nicht editierbar) -> ein hoeheres Modell-Ziel wuerde
# MLModel(contentsOf:) auf einem echten iOS-16-Geraet werfen lassen, obwohl
# die App formal iOS 16 traegt. Watch-Seite (WATCHOS_DEPLOYMENT_TARGET 10.6,
# die zu iOS 17 passende Generation) bekommt trotzdem denselben Wert, damit
# es nur eine Zahl zum Nachdenken gibt statt zwei. ML-Program-Format braucht
# nur iOS 15 -> iOS16 ist innerhalb des unterstuetzten Bereichs.
DEPLOYMENT_TARGET = ct.target.iOS16

INPUT_NAME = "window"
OUTPUT_NAME = "logit"


def export(kind: str) -> Path:
    model, meta = load_deploy_model(CHECKPOINTS[kind])
    n_ch = int(meta["n_channels"])
    example = torch.zeros(1, DEPLOY_SEQ_LEN, n_ch, dtype=torch.float32)

    # model.eval() ist in load_deploy_model gesetzt — Tracing im Trainingsmodus
    # wuerde Dropout und BatchNorm-Batch-Statistiken einbacken.
    assert model.training is False
    traced = torch.jit.trace(model, example)

    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name=INPUT_NAME,
                              shape=(1, DEPLOY_SEQ_LEN, n_ch),
                              dtype=np.float32)],
        outputs=[ct.TensorType(name=OUTPUT_NAME, dtype=np.float32)],
        convert_to="mlprogram",
        compute_precision=ct.precision.FLOAT32,
        minimum_deployment_target=DEPLOYMENT_TARGET,
    )
    mlmodel.short_description = (
        f"{meta['model']} — {meta['channels']}, {n_ch} Kanaele, "
        f"{DEPLOY_SEQ_LEN} Samples @ {meta['fs_hz']} Hz, Schwelle 0.5"
    )
    mlmodel.version = f"{meta['model']}-s{meta['seed']}-{meta['git_sha']}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{OUT_NAMES[kind]}.mlpackage"
    mlmodel.save(str(out))

    # Spec §7.2: Begleitartefakt mit Version und SHA-256, damit spaeter
    # nachweisbar ist, welches Gewicht auf dem Geraet lief.
    sidecar = {
        "artifact": out.name,
        "sha256": _sha256(out),
        "model": meta["model"],
        "channels": meta["channels"],
        "n_channels": n_ch,
        "seq_len": DEPLOY_SEQ_LEN,
        "fs_hz": int(meta["fs_hz"]),
        "threshold": 0.5,
        "compute_precision": "FLOAT32",
        "input_name": INPUT_NAME,
        "output_name": OUTPUT_NAME,
        "source_checkpoint": str(CHECKPOINTS[kind].relative_to(ROOT)),
        "source_checkpoint_sha256": _sha256(CHECKPOINTS[kind]),
        "coremltools": ct.__version__,
        "torch": str(torch.__version__),
    }
    (OUT_DIR / f"{OUT_NAMES[kind]}.json").write_text(json.dumps(sidecar, indent=1))
    print(f"{out}  ({meta['model']}, {n_ch} Kanaele)  sha256={sidecar['sha256'][:12]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["active", "passive", "both"], default="both")
    args = ap.parse_args()
    kinds = ["active", "passive"] if args.kind == "both" else [args.kind]
    for k in kinds:
        export(k)


if __name__ == "__main__":
    main()
