"""Sichert je trainable Subject BEIDE moeglichen Window-Profile im processed-
Cache, damit ein both-Pool-Sweep kein Subject still droppt.

``train_loso._select_sessions(profile=…)`` filtert Subjects ohne
``windows/{profil}/``-File **still** heraus. Laeuft eine Familie auf legacy *und*
modern, muss daher jedes trainable Subject beide moeglichen Profile haben:

- ``50hz``-Session       -> ``windows/50hz/``
- ``100hz_grav``-Session -> ``windows/100hz_grav/`` (nativ) + ``windows/50hz/``
                            (Downsample-View)
- ``100hz``-Session      -> ``windows/50hz/`` (Downsample-View; kein Gravity ->
                            nicht im modern-Pool)

Fehlende Profile werden via der Cross-Pool-Chain erzeugt (idempotent: vorhandene
bleiben). "Trainable" = es existiert eine native ``{sid}_merged.csv`` (also
Pen-Ground-Truth vorhanden); pen-lose ``free``-Aufnahmen ohne merged werden
uebersprungen. Am Ende: Vollstaendigkeits-Check mit hartem Fail, wenn ein
trainable Subject ein erwartetes Profil nach dem Build immer noch vermisst.

Aufruf (vor scripts/ops/pack_sweep_data.sh):
    python scripts/ops/ensure_views.py           # baut fehlende Views
    python scripts/ops/ensure_views.py --dry-run  # nur Report
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
from src.profiles import find_windows  # noqa: E402

PROC = ROOT / "data" / "processed"
SESSIONS = ROOT / "data" / "sessions.csv"

# native watch_profile -> welche Window-Profile dieses Subject haben muss.
_TARGETS = {
    "50hz": ["50hz"],
    "100hz_grav": ["100hz_grav", "50hz"],
    "100hz": ["50hz"],
}


def targets_for(profile: str) -> list[str]:
    """Profile, die ein Subject mit nativem ``profile`` haben sollte."""
    return list(_TARGETS.get(profile, []))


def plan(sessions: pd.DataFrame, has_merged, has_windows) -> dict[str, list[str]]:
    """``{sid: [fehlende Profile]}`` fuer trainable non-test Subjects. Pure.

    ``has_merged(sid) -> bool``      — native ``{sid}_merged.csv`` vorhanden?
    ``has_windows(sid, profile) -> bool`` — windows/{profile}/{sid} vorhanden?
    """
    out: dict[str, list[str]] = {}
    for r in sessions.itertuples():
        if str(getattr(r, "study_mode", "")) == "test":
            continue
        if not has_merged(r.session_id):
            continue  # pen-lose/ungemergte Aufnahme -> nicht trainable
        prof = str(getattr(r, "watch_profile", "") or "")
        miss = [p for p in targets_for(prof) if not has_windows(r.session_id, p)]
        if miss:
            out[r.session_id] = miss
    return out


def _has_merged(sid: str) -> bool:
    return (PROC / f"{sid}_merged.csv").exists()


def _has_windows(sid: str, profile: str) -> bool:
    return find_windows(sid, profile) is not None


def _run(cmd: list[str]) -> bool:
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode == 0


def build_profile(sid: str, native: str, profile: str) -> bool:
    """Erzeuge ``windows/{profile}/{sid}``. ``native`` = watch_profile."""
    if profile == native:
        # native Features aus {sid}_merged.csv
        return _run([sys.executable, "-m", "src.features", sid])
    if profile == "50hz":
        # Downsample-View-Kette: 100(hz|_grav) -> 50hz-View
        return (
            _run([sys.executable, "-m", "src.features.downsample", sid, "--target-hz", "50"])
            and _run([sys.executable, "-m", "src.merge", sid, "--watch-suffix", "legacy"])
            and _run([sys.executable, "-m", "src.features", sid, "--merged-suffix", "legacy"])
        )
    return _run([sys.executable, "-m", "src.features", sid])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="nur den Fehlbestand reporten, nichts bauen")
    args = ap.parse_args()

    sessions = pd.read_csv(SESSIONS)
    todo = plan(sessions, _has_merged, _has_windows)
    if not todo:
        print("Vollstaendig: alle trainable Subjects haben beide Profile.")
        return
    print(f"Fehlende Profile: {todo}")
    if args.dry_run:
        return

    native_by = dict(zip(sessions.session_id, sessions.watch_profile))
    for sid, profs in todo.items():
        for p in profs:
            print(f"[build] {sid} -> {p}")
            build_profile(sid, str(native_by.get(sid, "")), p)

    remaining = plan(sessions, _has_merged, _has_windows)
    if remaining:
        raise SystemExit(f"FAIL: Profile fehlen nach dem Build: {remaining}")
    print("OK: alle trainable Subjects haben jetzt beide Profile.")


if __name__ == "__main__":
    main()
