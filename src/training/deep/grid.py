"""Config-getriebene HP-Grid-Search (Spec + Runner + Collect).

Eine Config-Datei (configs/hp/{model}.json) definiert Modell, Pool,
Fenster, Folds, Seeds und das HP-Grid. Runner (Task 6) und Collect
(Task 7) bauen darauf auf. Wissenschaftliches Protokoll siehe
docs/superpowers/specs/2026-07-03-colab-grid-search-design.md § 8.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.training.deep.history import epoch_history_sink, tee
from src.training.deep.hp_search import grid_configs
from src.training.deep.models import MODELS
from src.training.deep.train_loso import train_deep_loso

ROOT = Path(__file__).parents[3]


class GridDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lr: list[float] = Field(min_length=1)
    dropout: list[float] = Field(min_length=1)
    batch_size: list[int] = Field(min_length=1)
    weight_decay: list[float] = Field(min_length=1)

    @field_validator("lr")
    @classmethod
    def _lr_positive(cls, v):
        if any(x <= 0 for x in v):
            raise ValueError("lr-Werte muessen > 0 sein")
        return v

    @field_validator("dropout")
    @classmethod
    def _dropout_range(cls, v):
        if any(not (0.0 <= x < 1.0) for x in v):
            raise ValueError("dropout muss in [0, 1) liegen")
        return v

    @field_validator("batch_size")
    @classmethod
    def _batch_floor(cls, v):
        if any(x < 8 for x in v):
            raise ValueError("batch_size muss >= 8 sein")
        return v

    @field_validator("weight_decay")
    @classmethod
    def _wd_nonneg(cls, v):
        if any(x < 0 for x in v):
            raise ValueError("weight_decay muss >= 0 sein")
        return v


class GridSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model: str
    pool: str
    win: int = Field(gt=0)
    folds: int | None = None
    seeds: list[int] = Field(min_length=1)
    max_epochs: int = Field(gt=0)
    patience: int = Field(gt=0)
    grid: GridDef

    @field_validator("model")
    @classmethod
    def _model_registered(cls, v):
        if v not in MODELS:
            raise ValueError(f"unbekanntes Modell {v!r} -- registriert: {sorted(MODELS)}")
        return v

    @field_validator("pool")
    @classmethod
    def _pool_known(cls, v):
        if v not in ("legacy", "modern"):
            raise ValueError("pool muss 'legacy' oder 'modern' sein")
        return v


def load_grid_spec(path: Path) -> GridSpec:
    return GridSpec(**json.loads(Path(path).read_text()))


def trial_name(model: str, cfg_idx: int, seed: int) -> str:
    # Why: -g{idx} ist disjunkt zum Sobol--t{idx} -- keine Kollisionen,
    # falls Verzeichnisse je gemischt werden.
    return f"{model}-g{cfg_idx:02d}-s{seed}"


def grid_outdir(spec: GridSpec, config_path: Path) -> Path:
    # Why: Stem statt Modellname -- identisch fuer die 13 kanonischen
    # Dateien, erlaubt aber Smoke-Configs ohne Freeze-Kollision.
    return ROOT / "models" / "hp_grid" / spec.pool / Path(config_path).stem


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _check_or_write_meta(outdir: Path, raw_config: dict, n_configs: int) -> None:
    meta_path = outdir / "run_meta.json"
    if meta_path.exists():
        frozen = json.loads(meta_path.read_text())
        if frozen.get("config") != raw_config:
            raise SystemExit(
                f"run_meta.json in {outdir} traegt eine ANDERE Config als die "
                f"uebergebene -- Grid nach Ergebnis-Ansicht geaendert? Neue "
                f"Explorationsrunde = neues Verzeichnis (Config-Datei "
                f"umbenennen) oder Verzeichnis bewusst leeren. Stilles "
                f"Mischen zweier Grids ist gesperrt (Spec § 8)."
            )
        return
    meta_path.write_text(json.dumps({
        "config": raw_config,
        "git_sha": _git_sha(),
        "created": datetime.now().isoformat(timespec="seconds"),
        "n_configs": n_configs,
    }, indent=2) + "\n")


def run_grid(config_path: Path, on_event=None, after_trial=None) -> Path:
    config_path = Path(config_path)
    raw = json.loads(config_path.read_text())
    spec = GridSpec(**raw)
    cfgs = grid_configs(spec.grid.model_dump())
    outdir = grid_outdir(spec, config_path)
    outdir.mkdir(parents=True, exist_ok=True)
    _check_or_write_meta(outdir, raw, len(cfgs))

    for idx, cfg in enumerate(cfgs):
        for seed in spec.seeds:
            name = trial_name(spec.model, idx, seed)
            trial_csv = outdir / f"trial_{name}.csv"
            if trial_csv.exists():
                continue
            cfg_id = f"g{idx:02d}"
            sink = epoch_history_sink(
                outdir / f"history_{name}.csv",
                model=spec.model, cfg_id=cfg_id, seed=seed, lr=cfg["lr"],
            )
            try:
                events = tee(sink, on_event) if on_event else sink
                df = train_deep_loso(
                    spec.model, spec.win, pool=spec.pool, seed=seed,
                    lr=cfg["lr"], dropout=cfg["dropout"],
                    batch_size=cfg["batch_size"], weight_decay=cfg["weight_decay"],
                    patience=spec.patience, max_epochs=spec.max_epochs,
                    folds=spec.folds, on_event=events,
                )
                pd.DataFrame([{
                    "model": spec.model, "cfg_id": cfg_id, **cfg, "seed": seed,
                    "accuracy": float(df["accuracy"].mean()),
                    "roc_auc": float(df["roc_auc"].mean()),
                    "best_epoch": float(df["best_epoch"].mean()),
                }]).to_csv(trial_csv, index=False)
            finally:
                # Why: deterministisches Schliessen des History-File-Handles
                # statt GC-Cleanup zu vertrauen -- relevant bei ~100+ Trials.
                sink.close()
            if after_trial is not None:
                after_trial(outdir)
    return outdir
