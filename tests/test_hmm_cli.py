"""Smoke fuer die neuen --oof/--out-Flags von scripts/ml/hmm_postprocess_loso.py.

Beweist, dass --oof die *uebergebene* OOF liest (nicht den fixen Default) —
ohne echte OOF-Daten, ueber den Fehlerpfad. Subprozess, weil der Modul-Import
torch/sklearn zieht.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_oof_flag_is_honoured(tmp_path):
    missing = tmp_path / "loso_oof_modern.csv"
    r = subprocess.run(
        [sys.executable, "scripts/ml/hmm_postprocess_loso.py",
         "--oof", str(missing), "--out", str(tmp_path / "cv.csv")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode != 0
    # Die Fehlermeldung nennt den uebergebenen Pfad, nicht models/loso_oof.csv.
    assert "loso_oof_modern.csv" in (r.stdout + r.stderr)
