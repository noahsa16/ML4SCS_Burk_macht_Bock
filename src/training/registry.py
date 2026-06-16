"""Single source of truth für das Modell-Menü, Pool-Validität und Tooltips.

MVP: nur RandomForest ist verdrahtet. Weitere Modelle (Deep/harnet/klassisch)
docken hier mit demselben Schema an, ohne Launcher/Frontend zu ändern.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    family: str            # "classical" | "deep" | "foundation"
    speed: str             # "fast" (live-demo) | "slow" (background)
    valid_pools: frozenset[str]
    supports_feature_importance: bool
    supports_zscore: bool
    causal: bool           # False => nicht live-tauglich (z. B. BiLSTM)
    runner: str            # python -m <runner>
    description: str


MODELS: dict[str, ModelSpec] = {
    "rf": ModelSpec(
        id="rf",
        label="RandomForest",
        family="classical",
        speed="fast",
        valid_pools=frozenset({"auto", "legacy", "modern"}),
        supports_feature_importance=True,
        supports_zscore=True,
        causal=True,
        runner="src.training.train_loso",
        description=(
            "Klassisch, 88/92 Features. Schnell (live-demo-tauglich). "
            "Per-Session-Z-Score an. Feature-Gruppen-Importance verfügbar."
        ),
    ),
}


def get(model_id: str) -> ModelSpec:
    if model_id not in MODELS:
        raise KeyError(f"unknown model {model_id!r}; have {sorted(MODELS)}")
    return MODELS[model_id]


def list_models() -> list[dict]:
    out = []
    for spec in MODELS.values():
        d = asdict(spec)
        d["valid_pools"] = sorted(spec.valid_pools)
        out.append(d)
    return out


def validate(model_id: str, pool: str) -> bool:
    return model_id in MODELS and pool in MODELS[model_id].valid_pools
