"""Pricing database for 30+ LLM models across major providers.

All prices are in USD per 1 million tokens. Each model entry contains:
- input_per_m: cost per 1M input tokens
- output_per_m: cost per 1M output tokens
- cached_input_per_m: cost per 1M cached input tokens (if supported)

Covers Claude, GPT, Gemini, Llama, Mistral families.
Last updated: 2026-08-01.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Prices are per 1M tokens (input, output) in USD.

DEFAULT_PRICING: dict[str, dict] = {
    # --- OpenAI ---
    "gpt-4o": {
        "provider": "openai",
        "input_per_m": 2.50,
        "output_per_m": 10.00,
        "cached_input_per_m": 1.25,
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "input_per_m": 0.15,
        "output_per_m": 0.60,
        "cached_input_per_m": 0.075,
    },
    "gpt-4.1": {
        "provider": "openai",
        "input_per_m": 2.00,
        "output_per_m": 8.00,
        "cached_input_per_m": 0.50,
    },
    "gpt-4.1-mini": {
        "provider": "openai",
        "input_per_m": 0.40,
        "output_per_m": 1.60,
        "cached_input_per_m": 0.10,
    },
    "gpt-4.1-nano": {
        "provider": "openai",
        "input_per_m": 0.10,
        "output_per_m": 0.40,
        "cached_input_per_m": 0.025,
    },
    "o3": {
        "provider": "openai",
        "input_per_m": 10.00,
        "output_per_m": 40.00,
        "cached_input_per_m": 2.50,
    },
    "o3-mini": {
        "provider": "openai",
        "input_per_m": 1.10,
        "output_per_m": 4.40,
        "cached_input_per_m": 0.55,
    },
    "o4-mini": {
        "provider": "openai",
        "input_per_m": 1.10,
        "output_per_m": 4.40,
        "cached_input_per_m": 0.275,
    },
    "gpt-4-turbo": {
        "provider": "openai",
        "input_per_m": 10.00,
        "output_per_m": 30.00,
        "cached_input_per_m": 5.00,
    },
    "gpt-3.5-turbo": {
        "provider": "openai",
        "input_per_m": 0.50,
        "output_per_m": 1.50,
        "cached_input_per_m": 0.25,
    },
    # --- Anthropic ---
    "claude-opus-4-6": {
        "provider": "anthropic",
        "input_per_m": 15.00,
        "output_per_m": 75.00,
        "cached_input_per_m": 1.50,
    },
    "claude-sonnet-4": {
        "provider": "anthropic",
        "input_per_m": 3.00,
        "output_per_m": 15.00,
        "cached_input_per_m": 0.30,
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic",
        "input_per_m": 3.00,
        "output_per_m": 15.00,
        "cached_input_per_m": 0.30,
    },
    "claude-haiku-4-5": {
        "provider": "anthropic",
        "input_per_m": 0.80,
        "output_per_m": 4.00,
        "cached_input_per_m": 0.08,
    },
    "claude-haiku-3-5": {
        "provider": "anthropic",
        "input_per_m": 0.80,
        "output_per_m": 4.00,
        "cached_input_per_m": 0.08,
    },
    "claude-3-5-sonnet": {
        "provider": "anthropic",
        "input_per_m": 3.00,
        "output_per_m": 15.00,
        "cached_input_per_m": 0.30,
    },
    # --- Google ---
    "gemini-2.5-pro": {
        "provider": "google",
        "input_per_m": 1.25,
        "output_per_m": 5.00,
        "cached_input_per_m": 0.3125,
    },
    "gemini-2.5-flash": {
        "provider": "google",
        "input_per_m": 0.15,
        "output_per_m": 0.60,
        "cached_input_per_m": 0.0375,
    },
    "gemini-2.0-flash": {
        "provider": "google",
        "input_per_m": 0.10,
        "output_per_m": 0.40,
        "cached_input_per_m": 0.025,
    },
    "gemini-1.5-pro": {
        "provider": "google",
        "input_per_m": 1.25,
        "output_per_m": 5.00,
        "cached_input_per_m": 0.3125,
    },
    "gemini-1.5-flash": {
        "provider": "google",
        "input_per_m": 0.075,
        "output_per_m": 0.30,
        "cached_input_per_m": 0.01875,
    },
    # --- Meta (via API providers like Together, Fireworks) ---
    "llama-4-scout": {
        "provider": "meta",
        "input_per_m": 0.17,
        "output_per_m": 0.36,
        "cached_input_per_m": None,
    },
    "llama-4-maverick": {
        "provider": "meta",
        "input_per_m": 0.27,
        "output_per_m": 0.85,
        "cached_input_per_m": None,
    },
    "llama-3.3-70b": {
        "provider": "meta",
        "input_per_m": 0.18,
        "output_per_m": 0.36,
        "cached_input_per_m": None,
    },
    "llama-3.1-405b": {
        "provider": "meta",
        "input_per_m": 3.00,
        "output_per_m": 3.00,
        "cached_input_per_m": None,
    },
    "llama-3.1-70b": {
        "provider": "meta",
        "input_per_m": 0.18,
        "output_per_m": 0.36,
        "cached_input_per_m": None,
    },
    "llama-3.1-8b": {
        "provider": "meta",
        "input_per_m": 0.05,
        "output_per_m": 0.08,
        "cached_input_per_m": None,
    },
    # --- Mistral ---
    "mistral-large": {
        "provider": "mistral",
        "input_per_m": 2.00,
        "output_per_m": 6.00,
        "cached_input_per_m": 0.50,
    },
    "mistral-medium": {
        "provider": "mistral",
        "input_per_m": 2.70,
        "output_per_m": 8.10,
        "cached_input_per_m": 0.675,
    },
    "mistral-small": {
        "provider": "mistral",
        "input_per_m": 0.20,
        "output_per_m": 0.60,
        "cached_input_per_m": 0.05,
    },
    "codestral": {
        "provider": "mistral",
        "input_per_m": 0.30,
        "output_per_m": 0.90,
        "cached_input_per_m": 0.075,
    },
    "mistral-nemo": {
        "provider": "mistral",
        "input_per_m": 0.15,
        "output_per_m": 0.15,
        "cached_input_per_m": 0.0375,
    },
    "pixtral-large": {
        "provider": "mistral",
        "input_per_m": 2.00,
        "output_per_m": 6.00,
        "cached_input_per_m": 0.50,
    },
}

# Aliases map common model name variants to canonical names.
MODEL_ALIASES: dict[str, str] = {
    "gpt-4o-2024-11-20": "gpt-4o",
    "gpt-4o-2025-03-27": "gpt-4o",
    "gpt-4.1-2025-04-14": "gpt-4.1",
    "claude-opus-4-6-20250801": "claude-opus-4-6",
    "claude-sonnet-4-20250514": "claude-sonnet-4",
    "claude-sonnet-4-5-20250514": "claude-sonnet-4-5",
    "claude-sonnet-4-0": "claude-sonnet-4",
    "claude-3-5-haiku-20241022": "claude-haiku-3-5",
    "claude-3-haiku-20240307": "claude-haiku-3-5",
    "claude-3-5-sonnet-20241022": "claude-3-5-sonnet",
    "claude-3-5-sonnet-20240620": "claude-3-5-sonnet",
    "gemini-2.5-pro-preview": "gemini-2.5-pro",
    "gemini-2.5-flash-preview": "gemini-2.5-flash",
    "models/gemini-2.5-pro": "gemini-2.5-pro",
    "models/gemini-2.5-flash": "gemini-2.5-flash",
    "mistral-large-latest": "mistral-large",
    "mistral-medium-latest": "mistral-medium",
    "mistral-small-latest": "mistral-small",
    "codestral-latest": "codestral",
    "open-mistral-nemo": "mistral-nemo",
    "pixtral-large-latest": "pixtral-large",
}


@dataclass
class ModelPricing:
    """Pricing specification for a single model."""

    model_id: str
    provider: str
    input_per_m: float
    output_per_m: float
    cached_input_per_m: Optional[float] = None

    def cost_for_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> float:
        """Calculate total cost in USD for a given token count.

        When cached_input_tokens > 0 and cached pricing is available,
        those tokens are charged at the cached rate instead of the full
        input rate.
        """
        effective_input = input_tokens
        cached_cost = 0.0

        if cached_input_tokens > 0 and self.cached_input_per_m is not None:
            cached_cost = (cached_input_tokens / 1_000_000) * self.cached_input_per_m
            effective_input = max(0, input_tokens - cached_input_tokens)

        input_cost = (effective_input / 1_000_000) * self.input_per_m
        output_cost = (output_tokens / 1_000_000) * self.output_per_m

        return input_cost + output_cost + cached_cost

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelPricing":
        """Deserialize from dictionary."""
        return cls(**data)


class PricingDatabase:
    """Manages model pricing with support for overrides and config files."""

    def __init__(self, config_path: Optional[Path] = None):
        self._models: dict[str, ModelPricing] = {}
        self._aliases: dict[str, str] = dict(MODEL_ALIASES)
        self._load_defaults()
        if config_path and config_path.exists():
            self.load_from_file(config_path)

    def _load_defaults(self) -> None:
        """Load built-in default pricing."""
        for model_id, spec in DEFAULT_PRICING.items():
            self._models[model_id] = ModelPricing(
                model_id=model_id,
                provider=spec["provider"],
                input_per_m=spec["input_per_m"],
                output_per_m=spec["output_per_m"],
                cached_input_per_m=spec.get("cached_input_per_m"),
            )

    def load_from_file(self, path: Path) -> None:
        """Load pricing overrides from a JSON config file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for model_id, spec in data.get("models", {}).items():
                self._models[model_id] = ModelPricing(
                    model_id=model_id,
                    provider=spec.get("provider", "custom"),
                    input_per_m=spec["input_per_m"],
                    output_per_m=spec["output_per_m"],
                    cached_input_per_m=spec.get("cached_input_per_m"),
                )
            for alias, canonical in data.get("aliases", {}).items():
                self._aliases[alias] = canonical
            logger.info("Loaded pricing overrides from %s", path)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load pricing config from %s: %s", path, exc)

    def save_to_file(self, path: Path) -> None:
        """Save current pricing to a JSON config file."""
        data = {
            "models": {mid: m.to_dict() for mid, m in self._models.items()},
            "aliases": self._aliases,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def resolve_model(self, model_name: str) -> str:
        """Resolve a model name through aliases to the canonical name."""
        return self._aliases.get(model_name, model_name)

    def get_pricing(self, model_name: str) -> Optional[ModelPricing]:
        """Get pricing for a model, resolving aliases first."""
        canonical = self.resolve_model(model_name)
        return self._models.get(canonical)

    def calculate_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> Optional[float]:
        """Calculate cost for a request. Returns None if model is unknown."""
        pricing = self.get_pricing(model_name)
        if pricing is None:
            logger.warning("No pricing data for model: %s", model_name)
            return None
        return pricing.cost_for_tokens(input_tokens, output_tokens, cached_input_tokens)

    def find_cheaper_alternative(
        self, model_name: str, same_provider: bool = False
    ) -> list[tuple[ModelPricing, float]]:
        """Find cheaper models sorted by savings ratio descending.

        Returns list of (ModelPricing, savings_ratio). savings_ratio is
        the fraction of cost saved, e.g. 0.8 means 80% cheaper.
        """
        current = self.get_pricing(model_name)
        if current is None:
            return []

        current_avg = (current.input_per_m + current.output_per_m) / 2
        if current_avg == 0:
            return []

        results = []
        for mid, pricing in self._models.items():
            if mid == (self.resolve_model(model_name)):
                continue
            if same_provider and pricing.provider != current.provider:
                continue

            alt_avg = (pricing.input_per_m + pricing.output_per_m) / 2
            if alt_avg < current_avg:
                savings = 1.0 - (alt_avg / current_avg)
                results.append((pricing, round(savings, 4)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def set_pricing(self, model_id: str, pricing: ModelPricing) -> None:
        """Set or override pricing for a model."""
        self._models[model_id] = pricing

    def add_alias(self, alias: str, canonical: str) -> None:
        """Add a model alias."""
        self._aliases[alias] = canonical

    def list_models(self, provider: Optional[str] = None) -> list[ModelPricing]:
        """Return all known model pricings, optionally filtered by provider."""
        models = list(self._models.values())
        if provider:
            models = [m for m in models if m.provider == provider.lower()]
        models.sort(key=lambda m: (m.provider, m.input_per_m))
        return models

    def list_providers(self) -> list[str]:
        """Return all known providers."""
        return sorted(set(m.provider for m in self._models.values()))

    def models_by_provider(self, provider: str) -> list[ModelPricing]:
        """Return models for a specific provider."""
        return [m for m in self._models.values() if m.provider == provider]
