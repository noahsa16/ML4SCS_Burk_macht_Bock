"""Zieht Golden-Vektoren aus echten Sessions und schreibt die Fixtures.

Auswahlregel: je Modell 24 Fenster — 8 sicher positive, 8 sicher negative und
8 schwellennahe. Die schwellennahen sind der eigentliche Wert: dort trennt
sich eine korrekte Konvertierung von einer knapp danebenliegenden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
# Why: a script run directly (not via `python -m`) gets its own directory as
# sys.path[0], not the repo root — `src` would not be importable otherwise.
sys.path.insert(0, str(ROOT))
from src.deploy.checkpoint import CHECKPOINTS, DEPLOY_SEQ_LEN, load_deploy_model  # noqa: E402
from src.deploy.golden import FIXTURES, encode_window  # noqa: E402
from src.training.deep.data import build_raw_windows  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"

N_PER_GROUP = 8

# Why: the fixture used to store the channel-set *name* only, never the
# per-column identity -- a window assembler that emits e.g. [ay, ax, az, ...]
# or forgets to add gravity on the passive path would pass P1/P2/P3
# unchanged (final-review finding I4). channel_names closes that gap.
CHANNEL_NAMES: dict[str, list[str]] = {
    "imu": ["ax", "ay", "az", "rx", "ry", "rz"],
    "raw_accel": ["x", "y", "z"],
    "user_accel": ["ax", "ay", "az"],
}


def _sha256(path: Path) -> str:
    """SHA-256 einer Datei oder eines Verzeichnisses (rekursiv, pfadsortiert)."""
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(path)).encode())
                h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()


def _session_windows(
    session: str, channels: str, suffix: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Gibt (X, y, t_center_ms) zurueck — die Signatur von build_raw_windows."""
    merged = pd.read_csv(DATA_PROC / f"{session}_merged{suffix}.csv")
    _assert_50hz(merged, session, suffix)
    return build_raw_windows(merged, seq_len=DEPLOY_SEQ_LEN, stride=25,
                             channels=channels)


def _assert_50hz(merged: pd.DataFrame, session: str, suffix: str) -> None:
    """Bricht ab, wenn die Quelle nicht ~50 Hz hat.

    Why: es gibt drei merged-Varianten je Session — die native ``_merged.csv``
    (bei Modern-Sessions 100 Hz), die 50-Hz-View ``_merged_legacy.csv`` und die
    50-Hz-mit-Gravity-View ``_merged_raw50.csv``. Beide Deployment-Modelle sind
    auf 50 Hz trainiert; eine 100-Hz-Quelle ergaebe 2,5-s- statt 5-s-Fenster,
    und zwar lautlos. Derselbe Fehlermodus hat im S093-Vorfall jedes Feature
    einer Session verzogen, ohne dass eine Metrik es angezeigt haette.
    """
    ts = merged["ts"].dropna().to_numpy(dtype=float)
    if len(ts) < 2 or ts[-1] <= ts[0]:
        raise SystemExit(f"{session}{suffix}: keine brauchbare ts-Achse")
    fs = (len(ts) - 1) * 1000.0 / (ts[-1] - ts[0])
    if not 45.0 <= fs <= 55.0:
        raise SystemExit(
            f"{session}_merged{suffix}.csv hat {fs:.1f} Hz, erwartet ~50 Hz. "
            f"Fuer das aktive Modell '_legacy' verwenden, fuer das passive "
            f"'_raw50' — die native merged-CSV ist bei Modern-Sessions 100 Hz."
        )


def build(kind: str, sessions: list[str], suffix: str) -> dict:
    model, meta = load_deploy_model(CHECKPOINTS[kind])
    rows = []
    for session in sessions:
        X, y, t = _session_windows(session, meta["channels"], suffix)
        if len(X) == 0:
            continue
        with torch.no_grad():
            logits = model(torch.from_numpy(X)).numpy()
        probas = 1.0 / (1.0 + np.exp(-logits))
        for i in range(len(X)):
            rows.append({"session": session, "i": i, "X": X[i],
                         "logit": float(logits[i]), "proba": float(probas[i]),
                         "label": int(y[i]), "t": float(t[i])})

    near = sorted(rows, key=lambda r: abs(r["proba"] - 0.5))[:N_PER_GROUP]
    near_ids = {(r["session"], r["i"]) for r in near}
    rest = [r for r in rows if (r["session"], r["i"]) not in near_ids]
    pos = sorted((r for r in rest if r["label"] == 1),
                 key=lambda r: -r["proba"])[:N_PER_GROUP]
    neg = sorted((r for r in rest if r["label"] == 0),
                 key=lambda r: r["proba"])[:N_PER_GROUP]

    chosen = near + pos + neg
    if len(chosen) < 3 * N_PER_GROUP:
        raise SystemExit(f"nur {len(chosen)} Fenster gefunden — mehr Sessions angeben")

    return {
        "model": meta["model"],
        "kind": kind,
        "checkpoint": str(CHECKPOINTS[kind].relative_to(ROOT)),
        "checkpoint_sha256": _sha256(CHECKPOINTS[kind]),
        "seq_len": DEPLOY_SEQ_LEN,
        "n_channels": int(meta["n_channels"]),
        "channels": meta["channels"],
        "channel_names": CHANNEL_NAMES[meta["channels"]],
        "fs_hz": int(meta["fs_hz"]),
        "dtype": "float32",
        "layout": "row-major (seq_len, n_channels)",
        "windows": [
            {"id": f"{r['session']}@{r['i']}", "t_center_ms": r["t"],
             "label": r["label"], "logit": r["logit"], "proba": r["proba"],
             "data_b64": encode_window(r["X"])}
            for r in chosen
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["active", "passive"], required=True)
    ap.add_argument("--sessions", nargs="+", required=True)
    ap.add_argument("--merged-suffix", default="",
                    help="'_raw50' fuer den passiven Pool")
    args = ap.parse_args()

    fx = build(args.kind, args.sessions, args.merged_suffix)
    FIXTURES[args.kind].parent.mkdir(parents=True, exist_ok=True)
    FIXTURES[args.kind].write_text(json.dumps(fx, indent=1))
    print(f"{FIXTURES[args.kind]}: {len(fx['windows'])} Fenster")


if __name__ == "__main__":
    main()
