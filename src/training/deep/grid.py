"""Config-getriebene HP-Grid-Search (Spec + Runner + Collect).

Eine Config-Datei (configs/hp/{model}.json) definiert Modell, Pool,
Fenster, Folds, Seeds und das HP-Grid. Runner (Task 6) und Collect
(Task 7) bauen darauf auf. Wissenschaftliches Protokoll siehe
docs/superpowers/specs/2026-07-03-colab-grid-search-design.md § 8.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.training.deep.models import MODELS

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
