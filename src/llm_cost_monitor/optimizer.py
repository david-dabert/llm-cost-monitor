"""Cost optimization engine with five concrete strategies.

Analyzes usage patterns and produces actionable recommendations,
each with an estimated monthly savings figure.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from llm_cost_monitor.pricing import PricingDatabase
from llm_cost_monitor.tracker import CostTracker

logger = logging.getLogger(__name__)


class CostOptimizer:
    """Runs five optimization strategies against usage data."""

    def __init__(self, tracker: CostTracker, pricing: PricingDatabase):
        self.tracker = tracker
        self.pricing = pricing

    def run_all(self, days: int = 30) -> list[dict]:
        """Run all five optimization strategies. Returns list of recommendations."""
        start = datetime.utcnow() - timedelta(days=days)
        records = self.tracker.get_recent_records(limit=10000)

        # Filter to the relevant time window
        filtered = []
        cutoff = start.isoformat()
        for r in records:
            if r.get("timestamp", "") >= cutoff:
                filtered.append(r)

        recommendations = []
        for strategy in [
            self._model_downgrade,
            self._caching_opportunities,
            self._batch_api_usage,
            self._prompt_compression,
            self._cache_prefix_optimization,
        ]:
            result = strategy(filtered, days)
            if result is not None:
                recommendations.append(result)

        recommendations.sort(key=lambda r: r["estimated_savings"], reverse=True)
        return recommendations

    def _model_downgrade(self, records: list[dict], days: int) -> Optional[dict]:
        """Strategy 1: Suggest cheaper models for high-spend models.

        If a model accounts for significant spend, check whether a cheaper
        alternative exists that could handle similar workloads.
        """
        model_costs = defaultdict(float)
        model_counts = defaultdict(int)
        for r in records:
            model_costs[r["model"]] += r.get("cost_usd", 0)
            model_counts[r["model"]] += 1

        if not model_costs:
            return None

        # Find the most expensive model
        top_model = max(model_costs, key=model_costs.get)
        top_cost = model_costs[top_model]

        if top_cost < 0.10:
            return None

        alternatives = self.pricing.find_cheaper_alternative(top_model)
        if not alternatives:
            return None

        best_alt, savings_ratio = alternatives[0]
        monthly_factor = 30.0 / max(days, 1)
        estimated_savings = top_cost * savings_ratio * monthly_factor

        return {
            "strategy": "Model Downgrade",
            "description": (
                f"Replace '{top_model}' (${top_cost:.2f} over {days}d, "
                f"{model_counts[top_model]} requests) with '{best_alt.model_id}' "
                f"({savings_ratio * 100:.0f}% cheaper). "
                f"Input: ${best_alt.input_per_m:.2f}/1M, "
                f"Output: ${best_alt.output_per_m:.2f}/1M."
            ),
            "estimated_savings": round(estimated_savings, 2),
            "current_model": top_model,
            "suggested_model": best_alt.model_id,
        }

    def _caching_opportunities(self, records: list[dict], days: int) -> Optional[dict]:
        """Strategy 2: Detect requests with low cache hit rates.

        If many requests have zero cached tokens, caching could reduce costs.
        """
        total_input = 0
        total_cached = 0
        cacheable_cost = 0.0

        for r in records:
            inp = r.get("input_tokens", 0)
            cached = r.get("cached_input_tokens", 0)
            total_input += inp
            total_cached += cached
            if cached == 0 and inp > 500:
                cacheable_cost += r.get("cost_usd", 0)

        if total_input == 0:
            return None

        cache_ratio = total_cached / total_input if total_input > 0 else 0

        if cache_ratio > 0.5:
            return None

        # Estimate savings: cached tokens typically cost 10% of input
        potential_cache_savings = cacheable_cost * 0.7
        monthly_factor = 30.0 / max(days, 1)
        estimated_savings = potential_cache_savings * monthly_factor

        if estimated_savings < 0.01:
            return None

        return {
            "strategy": "Enable Prompt Caching",
            "description": (
                f"Cache hit rate is {cache_ratio * 100:.0f}%. "
                f"{total_input - total_cached:,} input tokens were not served from cache. "
                f"Enable prompt caching (supported by Anthropic, OpenAI, Google) to reduce "
                f"input token costs by up to 90% on repeated system prompts."
            ),
            "estimated_savings": round(estimated_savings, 2),
            "cache_hit_rate": round(cache_ratio, 4),
        }

    def _batch_api_usage(self, records: list[dict], days: int) -> Optional[dict]:
        """Strategy 3: Detect patterns suitable for batch API.

        If many small requests are made to the same model within short
        time windows, batch API could reduce per-request overhead and
        often provides a 50% discount.
        """
        model_small_requests = defaultdict(int)
        model_total_cost = defaultdict(float)

        for r in records:
            total_tokens = r.get("total_tokens", 0)
            if total_tokens < 2000:
                model_small_requests[r["model"]] += 1
                model_total_cost[r["model"]] += r.get("cost_usd", 0)

        if not model_small_requests:
            return None

        top_model = max(model_small_requests, key=model_small_requests.get)
        count = model_small_requests[top_model]
        cost = model_total_cost[top_model]

        if count < 10:
            return None

        # Batch API typically gives 50% discount
        monthly_factor = 30.0 / max(days, 1)
        estimated_savings = cost * 0.50 * monthly_factor

        if estimated_savings < 0.01:
            return None

        return {
            "strategy": "Batch API Usage",
            "description": (
                f"Found {count} small requests (<2K tokens) to '{top_model}' "
                f"over {days} days. Using the Batch API (available from OpenAI, "
                f"Anthropic) provides a 50% discount on these requests. "
                f"Batch requests complete within 24 hours."
            ),
            "estimated_savings": round(estimated_savings, 2),
            "affected_model": top_model,
            "small_request_count": count,
        }

    def _prompt_compression(self, records: list[dict], days: int) -> Optional[dict]:
        """Strategy 4: Detect requests with high input-to-output ratio.

        A high ratio suggests long prompts (system prompts, context) that
        could be compressed or shortened.
        """
        high_ratio_cost = 0.0
        high_ratio_count = 0
        avg_input = 0
        total = 0

        for r in records:
            inp = r.get("input_tokens", 0)
            out = r.get("output_tokens", 0)
            total += 1
            avg_input += inp

            if out > 0 and inp / out > 10:
                high_ratio_cost += r.get("cost_usd", 0)
                high_ratio_count += 1

        if total == 0 or high_ratio_count < 5:
            return None

        avg_input = avg_input / total

        # Estimate 30% savings from prompt compression on high-ratio requests
        monthly_factor = 30.0 / max(days, 1)
        estimated_savings = high_ratio_cost * 0.30 * monthly_factor

        if estimated_savings < 0.01:
            return None

        return {
            "strategy": "Prompt Compression",
            "description": (
                f"Found {high_ratio_count} requests with input:output ratio >10:1 "
                f"(avg input: {avg_input:,.0f} tokens). These long prompts may contain "
                f"redundant context. Consider: shorter system prompts, structured "
                f"few-shot examples, or reference-by-ID patterns to reduce input costs."
            ),
            "estimated_savings": round(estimated_savings, 2),
            "high_ratio_count": high_ratio_count,
            "avg_input_tokens": round(avg_input),
        }

    def _cache_prefix_optimization(self, records: list[dict], days: int) -> Optional[dict]:
        """Strategy 5: Optimize cache prefix structure.

        If requests use caching but the cache write cost is high relative
        to read savings, the prefix structure can be improved.
        """
        models_with_cache = set()
        total_cost = 0.0
        cached_cost_savings = 0.0

        for r in records:
            cached = r.get("cached_input_tokens", 0)
            if cached > 0:
                models_with_cache.add(r["model"])
                # Estimate what the cost would have been without caching
                model_pricing = self.pricing.get_pricing(r["model"])
                if model_pricing and model_pricing.cached_input_per_m is not None:
                    full_cost = (cached / 1_000_000) * model_pricing.input_per_m
                    cached_actual = (cached / 1_000_000) * model_pricing.cached_input_per_m
                    cached_cost_savings += (full_cost - cached_actual)
            total_cost += r.get("cost_usd", 0)

        if not models_with_cache or total_cost == 0:
            return None

        cache_savings_ratio = cached_cost_savings / total_cost if total_cost > 0 else 0

        if cache_savings_ratio > 0.3:
            return None  # Already well-optimized

        # Estimate additional savings from better prefix design
        additional_savings = total_cost * 0.15  # Conservative 15% improvement
        monthly_factor = 30.0 / max(days, 1)
        estimated_savings = additional_savings * monthly_factor

        if estimated_savings < 0.01:
            return None

        return {
            "strategy": "Cache Prefix Optimization",
            "description": (
                f"Cache is active on {len(models_with_cache)} model(s) but savings "
                f"are only {cache_savings_ratio * 100:.0f}% of total cost. "
                f"Restructure prompts to maximize the static prefix: move system "
                f"instructions and few-shot examples before dynamic content. "
                f"Ensure cache-eligible prefixes are at least 1024 tokens (Anthropic) "
                f"or follow provider-specific minimum lengths."
            ),
            "estimated_savings": round(estimated_savings, 2),
            "current_savings_ratio": round(cache_savings_ratio, 4),
            "models_with_cache": sorted(models_with_cache),
        }
