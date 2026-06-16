"""Nicht-destruktive Run-Verzeichnisse + explizite Headline-Promotion.

Jeder Lauf lebt in models/runs/{run_id}/ (cv.csv, oof.csv, model.joblib,
config.json, events.jsonl). Die kanonischen Artefakte (rf_all.joblib,
loso_cv.csv, loso_oof.csv) ändern sich ausschließlich über promote().
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
RUNS_ROOT = ROOT / "models" / "runs"
CANONICAL_DIR = ROOT / "models"

# Welche Run-Datei auf welchen kanonischen Namen promotet wird.
_PROMOTE_MAP = {
    "cv.csv": "loso_cv.csv",
    "oof.csv": "loso_oof.csv",
    "model.joblib": "rf_all.joblib",
}


def new_run_id(model: str, pool: str, now: str | None = None) -> str:
    stamp = now or datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"{stamp}_{model}_{pool}"


def run_dir(run_id: str, root: Path = RUNS_ROOT) -> Path:
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_config(d: Path, config: dict) -> None:
    (d / "config.json").write_text(json.dumps(config, indent=2))


def list_runs(root: Path = RUNS_ROOT) -> list[dict]:
    if not root.exists():
        return []
    rows = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        cfg = d / "config.json"
        if cfg.exists():
            data = json.loads(cfg.read_text())
            data["run_id"] = d.name
            rows.append(data)
    rows.sort(key=lambda r: r["run_id"], reverse=True)
    return rows


def promote(run_id: str, root: Path = RUNS_ROOT,
            canonical_dir: Path = CANONICAL_DIR) -> None:
    src = root / run_id
    if not src.exists():
        raise FileNotFoundError(f"run {run_id} not found")
    canonical_dir.mkdir(parents=True, exist_ok=True)
    for run_file, canon_name in _PROMOTE_MAP.items():
        p = src / run_file
        if p.exists():
            shutil.copy2(p, canonical_dir / canon_name)
