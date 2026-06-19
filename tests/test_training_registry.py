import pytest

from src.training import registry


def test_rf_spec_present_and_well_formed():
    spec = registry.get("rf")
    assert spec.id == "rf"
    assert spec.family == "classical"
    assert spec.speed == "fast"
    assert "legacy" in spec.valid_pools and "auto" in spec.valid_pools
    assert spec.supports_feature_importance is True
    assert spec.causal is True  # RF ist live-tauglich (Sandbox)
    assert spec.description  # nicht leer (Tooltip)


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        registry.get("does-not-exist")


def test_list_models_returns_serialisable_dicts():
    rows = registry.list_models()
    assert any(r["id"] == "rf" for r in rows)
    for r in rows:
        assert {"id", "label", "family", "speed", "valid_pools",
                "supports_feature_importance", "causal", "description"} <= set(r)
        assert isinstance(r["valid_pools"], list)


def test_validate_pool_rejects_invalid_combo():
    assert registry.validate("rf", "legacy") is True
    assert registry.validate("rf", "nonsense") is False


def test_classical_and_deep_enabled_foundation_gated():
    by_id = {r["id"]: r for r in registry.list_models()}
    # Klassische teilen den train_loso-Runner (via --model) und sind verdrahtet.
    for mid in ("rf", "extratrees", "histgb", "logreg", "svm_rbf", "mlp"):
        assert by_id[mid]["family"] == "classical"
        assert by_id[mid]["enabled"] is True, f"{mid} should be enabled"
    # Deep-Sequenz-Modelle teilen den deep-Runner (src.training.deep) — ebenfalls
    # verdrahtet.
    for mid in ("cnn", "lstm", "gru", "tcn"):
        assert by_id[mid]["family"] == "deep"
        assert by_id[mid]["runner"] == "src.training.deep"
        assert by_id[mid]["enabled"] is True, f"{mid} should be enabled"
    # Nur Foundation (harnet) braucht noch eigene Runner-Instrumentierung → gated.
    for mid in ("harnet5", "harnet10", "harnet5_ft"):
        assert by_id[mid]["family"] == "foundation"
        assert by_id[mid]["enabled"] is False, f"{mid} should be gated"
    # nur Tree-Modelle haben Feature-Importance
    assert by_id["logreg"]["supports_feature_importance"] is False
