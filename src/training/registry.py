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
    enabled: bool = True   # Runner verdrahtet? (MVP: nur rf; Rest post-MVP)


_CLASSIC = frozenset({"auto", "legacy", "modern"})
_SEQ = frozenset({"legacy", "modern"})  # rohe Sequenzen mischen keine Sample-Raten


def _spec(id, label, family, speed, pools, fi, causal, runner, desc, enabled=False):
    return ModelSpec(id=id, label=label, family=family, speed=speed,
                     valid_pools=pools, supports_feature_importance=fi,
                     supports_zscore=True, causal=causal, runner=runner,
                     description=desc, enabled=enabled)


# Volles Menü (gruppiert nach Familie). Klassische Modelle teilen sich den
# train_loso-Runner (via --model); die Deep-Sequenz-Modelle teilen den
# deep-Runner (src.training.deep, --model) — beide Familien sind verdrahtet.
# Nur Foundation (harnet) braucht noch eigene Runner-Instrumentierung und
# bleibt enabled=False (im UI disabled + 400-Gate).
MODELS: dict[str, ModelSpec] = {m.id: m for m in [
    _spec("rf", "RandomForest", "classical", "fast", _CLASSIC, True, True,
          "src.training.train_loso",
          "Klassisch, 88/92 Features. Schnell (live-demo-tauglich). "
          "Per-Session-Z-Score an. Feature-Gruppen-Importance verfügbar.",
          enabled=True),
    _spec("extratrees", "ExtraTrees", "classical", "fast", _CLASSIC, True, True,
          "src.training.train_loso", "Extra-randomisierte Bäume — schnelle Tree-Alternative.",
          enabled=True),
    _spec("histgb", "HistGradBoost", "classical", "fast", _CLASSIC, True, True,
          "src.training.train_loso", "Histogram-Gradient-Boosting auf den 88 Features.",
          enabled=True),
    _spec("logreg", "LogisticRegression", "classical", "fast", _CLASSIC, False, True,
          "src.training.train_loso", "Lineares Baseline-Modell.", enabled=True),
    _spec("svm_rbf", "SVM-RBF", "classical", "slow", _CLASSIC, False, True,
          "src.training.train_loso", "Kernel-SVM (probability=True) — langsam.",
          enabled=True),
    _spec("mlp", "MLP", "classical", "slow", _CLASSIC, False, True,
          "src.training.train_loso", "Kleines Feed-Forward-Netz auf den 88 Features.",
          enabled=True),
    _spec("cnn", "CNN", "deep", "slow", _SEQ, False, True,
          "src.training.deep", "1D-CNN auf rohen IMU-Sequenzen (~Minuten, Hintergrund).",
          enabled=True),
    _spec("lstm", "LSTM", "deep", "slow", _SEQ, False, True,
          "src.training.deep", "Unidirektionales LSTM (kausal).", enabled=True),
    _spec("gru", "GRU", "deep", "slow", _SEQ, False, True,
          "src.training.deep", "GRU-Sequenzmodell.", enabled=True),
    _spec("tcn", "TCN", "deep", "slow", _SEQ, False, True,
          "src.training.deep", "Dilatierte Kausal-Convs (Bai et al. 2018) — "
          "kausal, ~6k Params.", enabled=True),
    _spec("harnet5", "harnet5 frozen", "foundation", "slow", _SEQ, False, True,
          "src.training.deep.harnet", "Oxford ssl-wearables, frozen (5-s-Fenster)."),
    _spec("harnet10", "harnet10 frozen", "foundation", "slow", _SEQ, False, True,
          "src.training.deep.harnet", "Oxford ssl-wearables, frozen (10-s-Fenster)."),
    _spec("harnet5_ft", "harnet5 finetune", "foundation", "slow", _SEQ, False, True,
          "src.training.deep.harnet_finetune", "harnet5 end-to-end fine-tuned (lang)."),
]}


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
