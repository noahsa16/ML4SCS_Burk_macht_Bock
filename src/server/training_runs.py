"""Nicht-destruktive Run-Verzeichnisse + explizite Headline-Promotion.

Jeder Lauf lebt in models/runs/{run_id}/ (cv.csv, oof.csv, model.joblib,
config.json, events.jsonl). Die kanonischen Artefakte (rf_all.joblib,
loso_cv.csv, loso_oof.csv) ändern sich ausschließlich über promote().
"""
from __future__ import annotations

import json
import shutil
import statistics
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


def write_timing(d: Path, folds: list[dict], total_sec: float | None) -> None:
    """Persistiert die gemessene Laufzeit eines Runs (timing.json).

    ``folds`` = [{"person", "sec"}, …] (pro Fold), ``total_sec`` = Gesamtzeit
    inkl. Setup. Quelle für die datengetriebene Dauer-Schätzung (``estimate``)
    statt eines hartkodierten Vorschau-Strings.
    """
    (d / "timing.json").write_text(json.dumps(
        {"total_sec": total_sec, "folds": folds}, indent=2))


def estimate(model: str, pool: str, root: Path = RUNS_ROOT) -> dict:
    """Pro-Fold-Sekunden (Median) aus vergangenen Läufen desselben model/pool.

    Poolt die Fold-Dauern aller passenden Läufe und nimmt den Median — robust
    gegen Ausreißer und gegen unterschiedliche Fold-Zahlen je Lauf. Ohne
    Historie → ``per_fold_sec = None`` (das Frontend zeigt dann keine erfundene
    Zeit, nur die Fold-Zahl).
    """
    empty = {"per_fold_sec": None, "n_runs": 0}
    if not root.exists():
        return empty
    secs: list[float] = []
    n_runs = 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        cfg, tim = d / "config.json", d / "timing.json"
        if not (cfg.exists() and tim.exists()):
            continue
        try:
            c = json.loads(cfg.read_text())
            if c.get("model") != model or c.get("pool") != pool:
                continue
            fold_secs = [float(f["sec"]) for f in json.loads(tim.read_text())
                         .get("folds", []) if f.get("sec") is not None]
        except (ValueError, OSError, KeyError):
            continue
        if fold_secs:
            secs.extend(fold_secs)
            n_runs += 1
    if not secs:
        return empty
    return {"per_fold_sec": float(statistics.median(secs)), "n_runs": n_runs}


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
            # Why: config.json wird beim Start ohne Ergebnis geschrieben — die
            # per-fold-Metriken liegen in cv.csv. Hier mitteln, damit die
            # Run-Historie/Leaderboard mean_acc zeigen (sonst überall "–").
            _attach_cv_summary(data, d / "cv.csv")
            _attach_timing(data, d / "timing.json")
            rows.append(data)
    rows.sort(key=lambda r: r["run_id"], reverse=True)
    return rows


def delete_run(run_id: str, root: Path = RUNS_ROOT) -> bool:
    """Löscht ein Run-Verzeichnis. Gibt False zurück, wenn es nicht existiert
    oder (Path-Traversal-Schutz) außerhalb von ``root`` läge."""
    d = root / run_id
    if not d.is_dir() or d.resolve().parent != root.resolve():
        return False
    shutil.rmtree(d)
    return True


def _attach_timing(data: dict, tim_path: Path) -> None:
    """Hängt die persistierte Gesamtlaufzeit an (no-op ohne timing.json)."""
    if not tim_path.exists():
        return
    try:
        total = json.loads(tim_path.read_text()).get("total_sec")
    except (ValueError, OSError):
        return
    if total is not None:
        data["total_sec"] = total


def _attach_cv_summary(data: dict, cv_path: Path) -> None:
    """Mittelt accuracy/roc_auc aus cv.csv in ``data`` (no-op ohne Datei)."""
    if not cv_path.exists():
        return
    import csv
    try:
        with open(cv_path, newline="") as f:
            recs = list(csv.DictReader(f))
    except Exception:
        return

    def _col_mean(key: str):
        vals = []
        for r in recs:
            v = r.get(key)
            if v in (None, ""):
                continue
            try:
                fv = float(v)
            except ValueError:
                continue
            if fv == fv:  # NaN-Filter
                vals.append(fv)
        return (sum(vals) / len(vals)) if vals else None

    acc = _col_mean("accuracy")
    if acc is not None:
        data["mean_acc"] = acc
        data["n_folds"] = sum(1 for r in recs if r.get("accuracy") not in (None, ""))
    auc = _col_mean("roc_auc")
    if auc is not None:
        data["mean_auc"] = auc


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
