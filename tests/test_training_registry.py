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


def test_menu_grouped_families_only_rf_enabled():
    by_id = {r["id"]: r for r in registry.list_models()}
    assert by_id["rf"]["enabled"] is True
    # Weitere Familien sind gelistet (volles Menü), aber Runner noch nicht
    # verdrahtet → enabled False (post-MVP).
    assert by_id["cnn"]["family"] == "deep" and by_id["cnn"]["enabled"] is False
    assert any(r["family"] == "foundation" for r in by_id.values())
    assert any(r["family"] == "classical" and r["id"] != "rf"
               for r in by_id.values())
    # nur Tree-Modelle haben Feature-Importance
    assert by_id["logreg"]["supports_feature_importance"] is False
