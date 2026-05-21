#!/usr/bin/env python3
"""Forensic sequence-gap analysis for a watch CSV.

Reports which batch sequence numbers landed in the CSV, which are missing,
batch-size distribution, and wall-clock anchors for each gap region. Use
when a session's iPhone-reported "uploaded" count exceeds the server-CSV
row count — sequence gaps localise where the loss occurred in time.

Usage:
    python scripts/checks/check_sequence_gaps.py S002
    python scripts/checks/check_sequence_gaps.py path/to/S002_watch.csv
    python scripts/checks/check_sequence_gaps.py            # most recent session
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "watch"


def _resolve(arg: str | None) -> Path:
    if arg is None:
        files = sorted(RAW.glob("*_watch.csv"))
        if not files:
            sys.exit(f"no watch CSVs in {RAW}")
        return files[-1]
    p = Path(arg)
    if p.exists():
        return p
    sid = arg.strip()
    candidate = RAW / f"{sid}_watch.csv"
    if candidate.exists():
        return candidate
    sys.exit(f"not found: {arg} (tried {candidate})")


def _fmt_ts(ms: int | None) -> str:
    if ms is None:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    except (OSError, OverflowError, ValueError):
        return "—"


def analyze(path: Path) -> dict:
    distinct_seqs: list[int] = []
    last_seq = None
    batch_sizes: Counter[int] = Counter()
    seq_first_local_ms: dict[int, int] = {}
    seq_last_local_ms: dict[int, int] = {}
    total_rows = 0
    rows_without_seq = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            total_rows += 1
            raw_seq = r.get("sequence")
            try:
                seq = int(raw_seq) if raw_seq not in (None, "") else None
            except ValueError:
                seq = None
            if seq is None:
                rows_without_seq += 1
                continue
            if seq != last_seq:
                distinct_seqs.append(seq)
                last_seq = seq
            batch_sizes[seq] += 1
            try:
                ts = int(r["local_ts_ms"]) if r.get("local_ts_ms") else None
            except ValueError:
                ts = None
            if ts is not None:
                seq_first_local_ms.setdefault(seq, ts)
                seq_last_local_ms[seq] = ts

    gap_regions: list[dict] = []
    for prev, cur in zip(distinct_seqs, distinct_seqs[1:]):
        if cur > prev + 1:
            gap_regions.append({
                "after_seq": prev,
                "next_seq": cur,
                "missing": cur - prev - 1,
                "after_local_ts_ms": seq_last_local_ms.get(prev),
                "before_local_ts_ms": seq_first_local_ms.get(cur),
            })
    total_missing = sum(g["missing"] for g in gap_regions)

    size_counter = Counter(batch_sizes.values())
    seq_min = distinct_seqs[0] if distinct_seqs else None
    seq_max = distinct_seqs[-1] if distinct_seqs else None
    expected_batches = (seq_max - seq_min + 1) if (seq_min is not None and seq_max is not None) else 0

    return {
        "path": str(path),
        "total_rows": total_rows,
        "rows_without_seq": rows_without_seq,
        "distinct_batches": len(distinct_seqs),
        "seq_min": seq_min,
        "seq_max": seq_max,
        "expected_batches": expected_batches,
        "missing_batches": total_missing,
        "gap_regions": gap_regions,
        "batch_size_distribution": dict(size_counter),
        "batch_size_min": min(batch_sizes.values()) if batch_sizes else 0,
        "batch_size_max": max(batch_sizes.values()) if batch_sizes else 0,
        "batch_size_mean": (
            sum(batch_sizes.values()) / len(batch_sizes) if batch_sizes else 0.0
        ),
    }


def print_report(result: dict, max_regions: int = 20) -> None:
    print(f"File: {result['path']}")
    print(f"Total CSV rows:           {result['total_rows']:,}  "
          f"(rows without sequence: {result['rows_without_seq']:,})")
    print(f"Distinct batch sequences: {result['distinct_batches']:,}")
    print(f"Sequence range:           {result['seq_min']} … {result['seq_max']}  "
          f"(expected {result['expected_batches']:,} batches)")
    print(f"Missing batches:          {result['missing_batches']:,} "
          f"in {len(result['gap_regions'])} gap region(s)")
    print()
    print("Batch-size distribution (samples-per-batch → count):")
    for size, count in sorted(result["batch_size_distribution"].items()):
        print(f"  {size:>3}: {count:,}")
    print(f"  → min={result['batch_size_min']}  "
          f"max={result['batch_size_max']}  "
          f"mean={result['batch_size_mean']:.2f}")
    print()
    regions = result["gap_regions"]
    if not regions:
        print("No sequence gaps. CSV is contiguous across batch numbers.")
        return
    print("Gap regions:")
    print(f"  {'after_seq':>10}  {'next_seq':>10}  {'missing':>8}  "
          f"{'after_wallclock':>17}  {'before_wallclock':>17}")
    for g in regions[:max_regions]:
        print(
            f"  {g['after_seq']:>10}  {g['next_seq']:>10}  {g['missing']:>8}  "
            f"{_fmt_ts(g['after_local_ts_ms']):>17}  "
            f"{_fmt_ts(g['before_local_ts_ms']):>17}"
        )
    if len(regions) > max_regions:
        print(f"  … (+{len(regions) - max_regions} more)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", help="session id (e.g. S002) or path to a watch CSV")
    parser.add_argument("--limit", type=int, default=20, help="max gap regions to print")
    args = parser.parse_args()

    path = _resolve(args.target)
    result = analyze(path)
    print_report(result, max_regions=args.limit)


if __name__ == "__main__":
    main()
