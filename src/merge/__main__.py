"""CLI: Session finden, watch-base mergen, als CSV speichern.

Aufruf::

    python -m src.merge              # neueste Session
    python -m src.merge S025         # spezifische Session
    python -m src.merge S025 --out custom.csv

Standard-Output: ``data/processed/{session}_merged.csv``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from .merge import merge_watch_pen

DATA_RAW  = Path(__file__).parents[2] / "data" / "raw"
DATA_PROC = Path(__file__).parents[2] / "data" / "processed"

_SESSION_RE = re.compile(r"^(S\d+)_(?:pen|watch)\.csv$")


def _session_pairs(watch_suffix: str = "") -> dict[str, dict[str, Path]]:
    """Find all S###_pen.csv + S###_watch[suffix].csv pairs in data/raw/.

    watch_suffix='legacy' looks for S###_watch_legacy.csv (downsampled
    Modern→Legacy variant from src.features.downsample), pen stays at
    canonical S###_pen.csv. Empty suffix = original behaviour.
    """
    pairs: dict[str, dict[str, Path]] = {}
    pen_re = re.compile(r"^(S\d+)_pen\.csv$")
    if watch_suffix:
        watch_re = re.compile(rf"^(S\d+)_watch_{re.escape(watch_suffix)}\.csv$")
    else:
        watch_re = re.compile(r"^(S\d+)_watch\.csv$")
    for path in (DATA_RAW / "pen").glob("S*.csv"):
        m = pen_re.match(path.name)
        if m:
            pairs.setdefault(m.group(1), {})["pen"] = path
    for path in (DATA_RAW / "watch").glob("S*.csv"):
        m = watch_re.match(path.name)
        if m:
            pairs.setdefault(m.group(1), {})["watch"] = path
    return {sid: p for sid, p in pairs.items() if "pen" in p and "watch" in p}


def _resolve_session(
    session: str | None, watch_suffix: str = "",
) -> tuple[str, Path, Path]:
    pairs = _session_pairs(watch_suffix=watch_suffix)
    if not pairs:
        suffix_note = f" (watch suffix={watch_suffix!r})" if watch_suffix else ""
        raise SystemExit(
            f"Keine S###_pen.csv + S###_watch.csv Paare unter data/raw/{suffix_note}."
        )
    sid = session or sorted(pairs)[-1]
    if sid not in pairs:
        raise SystemExit(f"Session {sid} hat kein vollständiges Paar. Verfügbar: {sorted(pairs)}")
    return sid, pairs[sid]["pen"], pairs[sid]["watch"]


def run(sid: str, pen_csv: Path, watch_csv: Path, out: Path | None = None) -> pd.DataFrame:
    df = merge_watch_pen(pen_csv, watch_csv)
    delta = df.attrs.get("pen_clock_offset_sec", 0.0)
    sigma = df.attrs.get("pen_clock_sigma", float("nan"))
    n_writing = int(df["label_writing"].sum())
    n_idle = len(df) - n_writing
    print(
        f"Merged dataset: {len(df)} Watch-Samples | "
        f"writing={n_writing}, idle={n_idle} | δ = {delta:.3f} s | σ = {sigma:.2f}"
    )
    out = out or (DATA_PROC / f"{sid}_merged.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Gespeichert: {out}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.merge")
    parser.add_argument("session", nargs="?", help="z. B. S027 — default: neueste Session")
    parser.add_argument("--out", type=Path, help="Ausgabepfad (default: data/processed/{session}_merged.csv)")
    parser.add_argument(
        "--watch-suffix", default="",
        help="Watch-CSV-Variante: '' (default, canonical S###_watch.csv) "
        "oder 'legacy' (downsampled S###_watch_legacy.csv aus "
        "src.features.downsample). Output bekommt denselben Suffix.",
    )
    args = parser.parse_args()
    sid, pen, watch = _resolve_session(args.session, watch_suffix=args.watch_suffix)
    print(f"Session {sid}: {pen.name} + {watch.name}")
    out = args.out
    if out is None and args.watch_suffix:
        out = DATA_PROC / f"{sid}_merged_{args.watch_suffix}.csv"
    run(sid, pen, watch, out)


if __name__ == "__main__":
    main()
