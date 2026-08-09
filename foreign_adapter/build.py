"""Build our watch/pen CSV schema from the ETH Zürich foreign datasets.

Only the five sessions with *verified* real pen ground truth are included
(see memory/foreign_swiss_dataset.md) — S3/T8/T9/T10 report a connected pen
but logged zero pen_down/pen_move/pen_up events, so they carry no sample-level
label and are left out until that's clarified with the Zürich team.

Output is fully self-contained under foreign_adapter/output/ — nothing is
written to data/raw/ or data/sessions.csv. This is deliberately a staging
area: inspect the per-session summary this script prints (label balance,
alignment sigma) before deciding to fold any session into the canonical
cohort (copy the CSVs into data/raw/{watch,pen}/ and append the matching
row from output/sessions_foreign.csv to data/sessions.csv).

Usage::

    python -m foreign_adapter.build
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.merge.merge import merge_watch_pen  # noqa: E402
from src.profiles import detect_profile  # noqa: E402
from src.server.config import SESSIONS_FIELDNAMES  # noqa: E402

from foreign_adapter.ege_pipeline import load_ege_session  # noqa: E402
from foreign_adapter.sensorlogger_pipeline import load_sensorlogger_session  # noqa: E402

FOREIGN_DATA = ROOT / "data" / "foreign_data"
OUT = Path(__file__).parent / "output"
OUT_WATCH = OUT / "raw" / "watch"
OUT_PEN = OUT / "raw" / "pen"
OUT_PROC = OUT / "processed"

# Only the sessions confirmed to carry real pen_down/pen_move/pen_up events —
# S3/T8/T9/T10 (data_ege_sensorlogger_pipeline) reported "pen connected" but
# logged zero pen events and are excluded until clarified.
SESSIONS = [
    {
        "session_id": "F-T6", "person_id": "CH_T6",
        "loader": "ege", "path": FOREIGN_DATA / "data_ege_pipeline" / "T6",
        "description": "[FOREIGN] ETH Zürich — Ege watchOS pipeline — T6",
    },
    {
        "session_id": "F-T7", "person_id": "CH_T7",
        "loader": "ege", "path": FOREIGN_DATA / "data_ege_pipeline" / "T7",
        "description": "[FOREIGN] ETH Zürich — Ege watchOS pipeline — T7",
    },
    {
        "session_id": "F-E1", "person_id": "CH_E1",
        "loader": "sensorlogger", "path": FOREIGN_DATA / "data_ege_sensorlogger_pipeline" / "E1_session3",
        "description": "[FOREIGN] ETH Zürich — SensorLogger pipeline — E1 (exam)",
    },
    {
        "session_id": "F-E2", "person_id": "CH_E2",
        "loader": "sensorlogger", "path": FOREIGN_DATA / "data_ege_sensorlogger_pipeline" / "E2_session6",
        "description": "[FOREIGN] ETH Zürich — SensorLogger pipeline — E2 (exam)",
    },
    {
        "session_id": "F-E3", "person_id": "CH_E3",
        "loader": "sensorlogger", "path": FOREIGN_DATA / "data_ege_sensorlogger_pipeline" / "E3_session1",
        "description": "[FOREIGN] ETH Zürich — SensorLogger pipeline — E3 (exam)",
    },
]

LOADERS = {"ege": load_ege_session, "sensorlogger": load_sensorlogger_session}


def _verdict_for_sigma(sigma: float) -> tuple[str, str]:
    if sigma != sigma:  # NaN
        return "skip", "alignment sigma undefined — inspect manually"
    if sigma <= -3.0:
        return "trainable", ""
    if sigma <= -2.0:
        return "usable", "sigma in [-3,-2] — review alignment plot before training"
    return "skip", f"sigma={sigma:.2f} above -2 threshold — weak alignment confidence"


def build_session(spec: dict) -> dict:
    sid = spec["session_id"]
    watch_df, pen_df = LOADERS[spec["loader"]](spec["path"], sid)

    OUT_WATCH.mkdir(parents=True, exist_ok=True)
    OUT_PEN.mkdir(parents=True, exist_ok=True)
    OUT_PROC.mkdir(parents=True, exist_ok=True)
    watch_path = OUT_WATCH / f"{sid}_watch.csv"
    pen_path = OUT_PEN / f"{sid}_pen.csv"
    watch_df.to_csv(watch_path, index=False)
    pen_df.to_csv(pen_path, index=False)

    merged = merge_watch_pen(pen_path, watch_path)
    delta = merged.attrs.get("pen_clock_offset_sec", 0.0)
    sigma = merged.attrs.get("pen_clock_sigma", float("nan"))
    merged_path = OUT_PROC / f"{sid}_merged.csv"
    merged.to_csv(merged_path, index=False)

    n_writing = int(merged["label_writing"].sum())
    n_total = len(merged)
    duration_s = (merged["ts"].max() - merged["ts"].min()) / 1000.0
    start = pd.to_datetime(merged["ts"].min(), unit="ms", utc=True)
    end = pd.to_datetime(merged["ts"].max(), unit="ms", utc=True)
    profile = detect_profile(merged)
    verdict, note = _verdict_for_sigma(sigma)

    print(
        f"{sid:6s} {spec['loader']:12s} dur={duration_s/60:6.1f}min  "
        f"writing%={n_writing/n_total:5.1%}  delta={delta:7.2f}s  sigma={sigma:6.2f}  "
        f"profile={profile:10s} verdict={verdict}"
        + (f"  ({note})" if note else "")
    )

    return {
        "session_id": sid, "person_id": spec["person_id"],
        "description": spec["description"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
        "pen_samples": len(pen_df), "watch_samples": len(watch_df),
        "airpods_samples": 0, "status": "completed",
        "duration_seconds": round(duration_s, 1),
        "ml_status": "", "recording_status": "",
        "alignment_sigma": round(sigma, 3) if sigma == sigma else "",
        "verdict": verdict, "issue_codes": "",
        "flagged": "", "flag_note": note,
        "study_mode": "free", "protocol_id": "", "subject_index": "",
        "watch_profile": profile,
    }


def main() -> None:
    rows = [build_session(spec) for spec in SESSIONS]
    manifest = pd.DataFrame(rows)[SESSIONS_FIELDNAMES]
    manifest_path = OUT / "sessions_foreign.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"\nManifest: {manifest_path}")
    print(
        "\nNichts wurde in data/raw/ oder data/sessions.csv geschrieben — "
        "das ist bewusst ein isolierter Staging-Bereich. Zum Übernehmen einer "
        "Session: {sid}_watch.csv/{sid}_pen.csv nach data/raw/{watch,pen}/ "
        "kopieren und die passende Zeile aus sessions_foreign.csv an "
        "data/sessions.csv anhängen."
    )


if __name__ == "__main__":
    main()
