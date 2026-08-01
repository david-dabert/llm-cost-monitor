"""Tests for the pricing module."""

import json
import tempfile
from pathlib import Path

from llm_cost_monitor.pricing import (
    ModelPricing,
    PricingDatabase,
)


class TestModelPricing:
    """Tests for ModelPricing dataclass."""

    def test_basic_cost_calculation(self):
        pricing = ModelPricing(
            model_id="test-model",
            provider="test",
            input_per_m=2.0,
            output_per_m=8.0,
        )
        cost = pricing.cost_for_tokens(input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.006) < 1e-9

    def test_zero_tokens_cost(self):
        pricing = ModelPricing(
            model_id="test-model",
            provider="test",
            input_per_m=2.0,
            output_per_m=8.0,
        )
        cost = pricing.cost_for_tokens(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_large_token_count(self):
        pricing = ModelPricing(
            model_id="test-model",
            provider="test",
            input_per_m=2.0,
            output_per_m=8.0,
        )
        cost = pricing.cost_for_tokens(input_tokens=1_000_000, output_tokens=1_000_000)
        assert abs(cost - 10.0) < 1e-9

    def test_cached_tokens_reduce_cost(self):
        pricing = ModelPricing(
            model_id="test-model",
            provider="test",
            input_per_m=10.0,
            output_per_m=30.0,
            cached_input_per_m=1.0,
        )
        cost = pricing.cost_for_tokens(
            input_tokens=1000,
            output_tokens=200,
            cached_input_tokens=600,
        )
        expected = (400 / 1e6 * 10.0) + (600 / 1e6 * 1.0) + (200 / 1e6 * 30.0)
        assert abs(cost - expected) < 1e-9

    def test_cached_tokens_no_cache_price(self):
        """When cached_input_per_m is None, cached tokens are ignored."""
        pricing = ModelPricing(
            model_id="test-model",
            provider="test",
            input_per_m=2.0,
            output_per_m=8.0,
            cached_input_per_m=None,
        )
        cost = pricing.cost_for_tokens(
            input_tokens=1000,
            output_tokens=500,
            cached_input_tokens=500,
        )
        expected = (1000 / 1e6 * 2.0) + (500 / 1e6 * 8.0)
        assert abs(cost - expected) < 1e-9

    def test_serialization_roundtrip(self):
        pricing = ModelPricing(
            model_id="gpt-4o",
            provider="openai",
            input_per_m=2.5,
            output_per_m=10.0,
            cached_input_per_m=1.25,
        )
        data = pricing.to_dict()
        restored = ModelPricing.from_dict(data)
        assert restored.model_id == pricing.model_id
        assert restored.provider == pricing.provider
        assert restored.input_per_m == pricing.input_per_m
        assert restored.output_per_m == pricing.output_per_m
        assert restored.cached_input_per_m == pricing.cached_input_per_m


class TestPricingDatabase:
    """Tests for PricingDatabase."""

    def test_defaults_loaded(self):
        db = PricingDatabase()
        assert len(db.list_models()) > 0
        assert len(db.list_providers()) > 0

    def test_known_models_exist(self):
        db = PricingDatabase()
        known = ["gpt-4o", "claude-opus-4-6", "gemini-2.5-pro", "mistral-large"]
        for model in known:
            pricing = db.get_pricing(model)
            assert pricing is not None, f"Missing pricing for {model}"
            assert pricing.input_per_m > 0
            assert pricing.output_per_m > 0

    def test_alias_resolution(self):
        db = PricingDatabase()
        resolved = db.resolve_model("gpt-4o-2024-11-20")
        assert resolved == "gpt-4o"

    def test_alias_pricing_lookup(self):
        db = PricingDatabase()
        pricing = db.get_pricing("claude-opus-4-6-20250801")
        assert pricing is not None
        assert pricing.model_id == "claude-opus-4-6"

    def test_unknown_model_returns_none(self):
        db = PricingDatabase()
        pricing = db.get_pricing("totally-fake-model-xyz")
        assert pricing is None

    def test_calculate_cost(self):
        db = PricingDatabase()
        cost = db.calculate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
        assert cost is not None
        assert cost > 0

    def test_calculate_cost_unknown_model(self):
        db = PricingDatabase()
        cost = db.calculate_cost("fake-model", input_tokens=1000, output_tokens=500)
        assert cost is None

    def test_set_custom_pricing(self):
        db = PricingDatabase()
        custom = ModelPricing(
            model_id="my-custom-model",
            provider="custom",
            input_per_m=1.0,
            output_per_m=2.0,
        )
        db.set_pricing("my-custom-model", custom)
        pricing = db.get_pricing("my-custom-model")
        assert pricing is not None
        assert pricing.input_per_m == 1.0

    def test_add_alias(self):
        db = PricingDatabase()
        db.add_alias("my-alias", "gpt-4o")
        pricing = db.get_pricing("my-alias")
        assert pricing is not None
        assert pricing.model_id == "gpt-4o"

    def test_models_by_provider(self):
        db = PricingDatabase()
        openai_models = db.models_by_provider("openai")
        assert len(openai_models) > 0
        assert all(m.provider == "openai" for m in openai_models)

    def test_load_from_config_file(self):
        config = {
            "models": {
                "test-model": {
                    "provider": "test",
                    "input_per_m": 5.0,
                    "output_per_m": 15.0,
                }
            },
            "aliases": {
                "test-alias": "test-model",
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config, f)
            config_path = Path(f.name)

        db = PricingDatabase(config_path=config_path)
        pricing = db.get_pricing("test-model")
        assert pricing is not None
        assert pricing.input_per_m == 5.0

        alias_pricing = db.get_pricing("test-alias")
        assert alias_pricing is not None

        config_path.unlink()

    def test_save_to_file(self):
        db = PricingDatabase()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "pricing.json"
            db.save_to_file(path)
            assert path.exists()
            with open(path) as f:
                data = json.load(f)
            assert "models" in data
            assert "aliases" in data

    def test_anthropic_opus_pricing_values(self):
        """Verify specific pricing values for Claude Opus 4.6."""
        db = PricingDatabase()
        pricing = db.get_pricing("claude-opus-4-6")
        assert pricing is not None
        assert pricing.input_per_m == 15.0
        assert pricing.output_per_m == 75.0
        assert pricing.cached_input_per_m == 1.50

    def test_all_default_models_have_positive_pricing(self):
        """Every default model must have positive input and output pricing."""
        db = PricingDatabase()
        for model in db.list_models():
            assert model.input_per_m > 0, f"{model.model_id} has zero input price"
            assert model.output_per_m > 0, f"{model.model_id} has zero output price"
