"""CLI: Session finden, mergen, als CSV speichern.

Aufruf::

    python -m src.merge              # neueste Session
    python -m src.merge S025         # spezifische Session
    python -m src.merge S025 --out custom.csv

Standard-Output: ``data/processed/merged_dataset.csv``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from .merge import merge_pen_watch

DATA_RAW  = Path(__file__).parents[2] / "data" / "raw"
DATA_PROC = Path(__file__).parents[2] / "data" / "processed"

_SESSION_RE = re.compile(r"^(S\d+)_(?:pen|watch)\.csv$")


def _session_pairs() -> dict[str, dict[str, Path]]:
    pairs: dict[str, dict[str, Path]] = {}
    for kind in ("pen", "watch"):
        for path in (DATA_RAW / kind).glob("S*.csv"):
            m = _SESSION_RE.match(path.name)
            if m:
                pairs.setdefault(m.group(1), {})[kind] = path
    return {sid: p for sid, p in pairs.items() if "pen" in p and "watch" in p}


def _resolve_session(session: str | None) -> tuple[str, Path, Path]:
    pairs = _session_pairs()
    if not pairs:
        raise SystemExit("Keine S###_pen.csv + S###_watch.csv Paare unter data/raw/.")
    sid = session or sorted(pairs)[-1]
    if sid not in pairs:
        raise SystemExit(f"Session {sid} hat kein vollständiges Paar. Verfügbar: {sorted(pairs)}")
    return sid, pairs[sid]["pen"], pairs[sid]["watch"]


def run(pen_csv: Path, watch_csv: Path, out: Path | None = None) -> pd.DataFrame:
    df = merge_pen_watch(pen_csv, watch_csv)
    delta = df.attrs.get("pen_clock_offset_sec", 0.0)
    sigma = df.attrs.get("pen_clock_sigma", float("nan"))
    print(f"Merged dataset: {len(df)} Zeilen | δ = {delta:.3f} s | σ = {sigma:.2f}")
    out = out or (DATA_PROC / "merged_dataset.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Gespeichert: {out}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.merge")
    parser.add_argument("session", nargs="?", help="z. B. S027 — default: neueste Session")
    parser.add_argument("--out", type=Path, help="Ausgabepfad (default: data/processed/merged_dataset.csv)")
    args = parser.parse_args()
    sid, pen, watch = _resolve_session(args.session)
    print(f"Session {sid}: {pen.name} + {watch.name}")
    run(pen, watch, args.out)


if __name__ == "__main__":
    main()
