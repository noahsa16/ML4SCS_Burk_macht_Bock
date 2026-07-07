"""3-s-Fenster + HMM — die ungetestete Mitte der Kontext-Leiter.

Die Leiter (`reports/hmm_context_ladder.md`) deckte RF/Deep × 1s/5s ab: HMM hilft
den 1-s-Modellen, schadet den 5-s-Modellen. 3 s liegt am Vorzeichen-Wechsel.
Dieses Skript rechnet den 3-s-RF-Punkt bit-identisch (``_eval_oof`` aus
``hmm_cross_model``) und stellt ihn neben die bekannten 1s/5s-RF-Sprossen.

Voraussetzung::

    python -m src.training.train_loso --pool legacy --window-sec 3 --save-oof /tmp/rf3_oof.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ml.hmm_cross_model import _eval_oof  # noqa: E402

OOF3 = Path("/tmp/rf3_oof_legacy.csv")
# Referenz-Sprossen aus der publizierten Leiter (N=15, RF, proba_cal).
REF = {
    "RF-1s": dict(floor=0.881, hmm=0.905, dacc=+0.0243, p=0.0001),
    "RF-5s": dict(floor=0.887, hmm=0.879, dacc=-0.0076, p=0.0131),
}


def main() -> None:
    if not OOF3.exists():
        raise SystemExit(f"{OOF3} fehlt — erst das 3-s-OOF erzeugen (Docstring).")
    r = _eval_oof(OOF3, "label", "proba_cal")

    print("HMM-Kontext-Leiter mit dem neuen 3-s-Punkt (RF, legacy):\n")
    print(f"  {'Basismodell':10s} {'Floor':>7} {'HMM':>7} {'Δacc':>9} {'p':>9}  {'Neg.-Kontrolle':>14}")
    print(f"  {'RF-1s':10s} {REF['RF-1s']['floor']:7.3f} {REF['RF-1s']['hmm']:7.3f} "
          f"{REF['RF-1s']['dacc']:+9.4f} {REF['RF-1s']['p']:9.4f}  {'—':>14}")
    print(f"  {'RF-3s (neu)':10s} {r['floor_acc']:7.3f} {r['hmm_acc']:7.3f} "
          f"{r['dacc']:+9.4f} {r['p']:9.4f}  {r['nc']:14.3f}   "
          f"{'← ' + ('HILFT' if r['dacc'] > 0 else 'SCHADET') + (' (sig)' if r['sig'] else ' (n.s.)')}")
    print(f"  {'RF-5s':10s} {REF['RF-5s']['floor']:7.3f} {REF['RF-5s']['hmm']:7.3f} "
          f"{REF['RF-5s']['dacc']:+9.4f} {REF['RF-5s']['p']:9.4f}  {'—':>14}")
    print(f"\n  3-s-Floor-AUC {r['floor_auc']:.3f} → HMM-AUC {r['hmm_auc']:.3f}   (N={r['n']})")
    print("\n  Lesart: liegt Δacc > 0 → der Vorzeichen-Wechsel sitzt jenseits 3 s "
          "(3-s-Fenster noch 'flackrig' genug); Δacc ≤ 0 → er sitzt schon vor 3 s.")


if __name__ == "__main__":
    main()
