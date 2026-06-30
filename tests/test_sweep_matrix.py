"""Tests fuer den Headline-Refokus des Sweep-Matrix-Builders (scripts/ml/sweep_matrix.py).

``scripts`` ist kein Paket -> Modul per importlib ueber den Pfad laden.
Cron (leeres Environment) faehrt seit dem Refokus die drei Headline-Familien auf
beiden Pools; der alte breite Sweep liegt hinter BROAD=true.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "sweep_matrix", ROOT / "scripts" / "ml" / "sweep_matrix.py"
)
sweep_matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep_matrix)

_ENV_KEYS = ("POOLS", "DEEP_MODELS", "AUGMENT", "BROAD",
             "MODELS", "GAPS", "WINDOWS", "EXTRAS", "DEEP_WINS")
# Broad-Deep-Lang-Fenster-Jobs heissen cnn-win5 / tcn-win10 / tcn6-win5.
_DEEP_WIN_PREFIXES = ("cnn-win", "tcn-win", "tcn6-win")


def _build_with(monkeypatch, **env) -> dict[str, str]:
    """build() mit kontrolliertem Environment -> {name: cmd}."""
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return {j["name"]: j["cmd"] for j in sweep_matrix.build()["include"]}


def _deep_win_jobs(names: set[str]) -> set[str]:
    return {n for n in names if n.startswith(_DEEP_WIN_PREFIXES)}


# --- Headline-Default (Cron) ------------------------------------------------

def test_cron_default_is_headline_both_pools(monkeypatch):
    by = _build_with(monkeypatch)
    names = set(by)
    assert "deep-cnn5s-legacy" in names and "deep-cnn5s-modern" in names
    assert "deep-tcn65s-legacy" in names and "deep-tcn610s-legacy" not in names
    assert "deep-tcn10s-legacy" in names                      # cnn/tcn auch @10s
    assert "deep-lstm5s-legacy" in names and "deep-gru5s-modern" in names
    assert any(n.startswith("mlp-") and n.endswith("-legacy") for n in names)
    assert "rf-hmm-legacy" in names and "rf-hmm-modern" in names
    # kein Transformer im Default, kein breiter Sweep
    assert not any("transformer" in n for n in names)
    assert "rf" not in names and "rf-gap300" not in names


def test_lstm_gru_only_at_5s(monkeypatch):
    names = set(_build_with(monkeypatch))
    assert "deep-lstm10s-legacy" not in names
    assert "deep-gru10s-legacy" not in names


def test_augment_on_doubles_only_deep(monkeypatch):
    by = _build_with(monkeypatch, AUGMENT="on")
    names = set(by)
    assert "deep-cnn5s-legacy" in names and "deep-cnn5s-legacy-aug" in names
    assert not any(n.endswith("-aug") and ("mlp" in n or "rf-hmm" in n) for n in names)
    assert "--augment" in by["deep-cnn5s-legacy-aug"]


def test_augment_off_has_no_aug_variants(monkeypatch):
    assert not any(n.endswith("-aug") for n in _build_with(monkeypatch, AUGMENT="off"))


def test_deep_models_override_runs_transformer(monkeypatch):
    names = set(_build_with(monkeypatch, DEEP_MODELS="transformer:5", POOLS="legacy"))
    assert "deep-transformer5s-legacy" in names
    assert "deep-cnn5s-legacy" not in names                   # Default-Liste ersetzt


def test_pools_legacy_only(monkeypatch):
    names = set(_build_with(monkeypatch, POOLS="legacy"))
    assert not any(n.endswith("-modern") for n in names)
    assert "rf-hmm-legacy" in names


def test_rf_hmm_modern_uses_pool_suffixed_paths(monkeypatch):
    cmd = _build_with(monkeypatch, POOLS="modern")["rf-hmm-modern"]
    assert "--pool modern" in cmd
    assert "loso_oof_modern.csv" in cmd
    assert "hmm_postprocess_modern_cv.csv" in cmd


def test_mlp_grid_carries_model_params(monkeypatch):
    by = _build_with(monkeypatch, POOLS="legacy")
    mlp = next(c for n, c in by.items() if n.startswith("mlp-"))
    assert "--model mlp" in mlp and "--model-params" in mlp


# --- Broad-Modus (Dispatch-only, alter Sweep) ------------------------------

def test_broad_replaces_headline(monkeypatch):
    names = set(_build_with(monkeypatch, BROAD="true"))
    assert "rf" in names and "rf-gap300" in names and "rf-win5" in names
    assert not any(n.startswith("deep-") for n in names)      # keine Headline-Deep
    assert "rf-hmm-legacy" not in names


def test_broad_deep_wins_default_off(monkeypatch):
    assert not _deep_win_jobs(set(_build_with(monkeypatch, BROAD="true")))


def test_broad_deep_wins_enabled(monkeypatch):
    by = _build_with(monkeypatch, BROAD="true", DEEP_WINS="5,10")
    for m in ("cnn", "tcn"):
        assert f"{m}-win5" in by and f"{m}-win10" in by
    assert "tcn6-win5" in by and "tcn6-win10" not in by       # tcn6 nur @5s


def test_broad_classic_jobs_present(monkeypatch):
    by = _build_with(monkeypatch, BROAD="true")
    assert by["rf"].startswith("python -m src.training.train_loso")
    assert by["tcn"] == "python -m src.training.deep --model tcn --pool legacy"
