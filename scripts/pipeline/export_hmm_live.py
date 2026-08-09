#!/usr/bin/env python
"""Exportiert die deploybaren HMM-Live-Parameter nach ``models/hmm_live.json``.

Der Live-Forward-Filter (``src/server/inference.py``) braucht eine feste
Übergangsmatrix + Klassen-Prior. Beides ist eine Eigenschaft der **Label-
Dynamik** (wie klebrig Schreib-/Idle-Phasen sind), nicht des RF — daher
modell-agnostisch aus ``models/loso_oof.csv`` geschätzt und für rf_noah wie
rf_all_live identisch nutzbar. Kein Retraining der Joblibs nötig.

Identische Schätzung wie der Offline-Treiber (``hmm_postprocess_loso.py``):
Übergänge **pro Session** (kein Phantom-Übergang über Session-Grenzen),
Laplace-Glättung, Prior aus allen Labels.

CLI
---
    python scripts/ml/export_hmm_live.py [--smoothing 1.0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.evaluation.hmm import class_priors, estimate_transition_matrix  # noqa: E402

OOF_PATH = ROOT / "models" / "loso_oof.csv"
OUT_PATH = ROOT / "models" / "hmm_live.json"
STRIDE_SEC = 0.5  # Default-Stride in build_windows → für die Latenz-Charakterisierung


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoothing", type=float, default=1.0,
                    help="Laplace-Glättung der Übergangs-Counts (default 1.0).")
    args = ap.parse_args()

    if not OOF_PATH.exists():
        raise SystemExit(
            f"OOF fehlt: {OOF_PATH} — erst `python -m src.training.train_loso "
            f"--save-oof` laufen lassen.")

    oof = pd.read_csv(OOF_PATH)
    seqs = [g.sort_values("t_center_ms")["label"].to_numpy()
            for _, g in oof.groupby("session_id", sort=False)]
    A = estimate_transition_matrix(seqs, smoothing=args.smoothing)
    priors = class_priors(oof["label"].to_numpy(), smoothing=args.smoothing)

    # Klebrigkeit → erwartete Verweildauer pro Zustand → effektives Gedächtnis.
    tau_w = 1.0 / (1.0 - A[1, 1])
    tau_i = 1.0 / (1.0 - A[0, 0])
    mem_s = 0.5 * (tau_w + tau_i) * STRIDE_SEC

    payload = {
        "states": ["idle", "writing"],
        "transition": A.tolist(),
        "priors": priors.tolist(),
        "smoothing": args.smoothing,
        "source": "loso_oof.csv",
        "n_windows": int(len(oof)),
        "n_sessions": int(oof["session_id"].nunique()),
        "effective_memory_sec": round(float(mem_s), 1),
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Sessions: {payload['n_sessions']}   Windows: {payload['n_windows']:,}")
    print(f"A = [[{A[0,0]:.3f} {A[0,1]:.3f}] [{A[1,0]:.3f} {A[1,1]:.3f}]]")
    print(f"priors (idle/writing) = {priors[0]:.3f} / {priors[1]:.3f}")
    print(f"effektives Gedächtnis ~{mem_s:.1f} s")
    print(f"→ {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
