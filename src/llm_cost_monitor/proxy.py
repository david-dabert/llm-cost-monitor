"""Transparent Flask proxy that intercepts LLM API calls.

Sits between your application and the LLM provider APIs, extracting
model names, token counts, and calculating costs. All usage is logged
to the cost tracker (SQLite-backed).

Supports OpenAI, Anthropic, Google Gemini, and Mistral APIs.
Handles both standard and streaming responses.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import requests
from flask import Flask, request, Response, jsonify

from llm_cost_monitor.pricing import PricingDatabase
from llm_cost_monitor.tracker import CostTracker, UsageRecord

logger = logging.getLogger(__name__)

# Provider endpoint defaults
DEFAULT_ENDPOINTS = {
    "openai": os.environ.get("OPENAI_API_BASE", "https://api.openai.com"),
    "anthropic": os.environ.get("ANTHROPIC_API_BASE", "https://api.anthropic.com"),
    "google": os.environ.get(
        "GOOGLE_API_BASE", "https://generativelanguage.googleapis.com"
    ),
    "mistral": os.environ.get("MISTRAL_API_BASE", "https://api.mistral.ai"),
}

# Paths that indicate completion/message endpoints worth tracking
COMPLETION_PATHS = {
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/messages",
    "/v1/chat",
}


@dataclass
class ProxyConfig:
    """Configuration for the proxy server."""

    host: str = "0.0.0.0"
    port: int = 8080
    db_path: str = "costs.db"
    log_level: str = "INFO"


def detect_provider_from_path(path: str) -> Optional[str]:
    """Detect the LLM provider from the URL path prefix.

    The proxy expects requests to arrive at paths like:
      /openai/v1/chat/completions
      /anthropic/v1/messages
      /google/v1beta/models/gemini-2.5-pro:generateContent
      /mistral/v1/chat/completions
    """
    parts = path.strip("/").split("/")
    if not parts:
        return None
    prefix = parts[0].lower()
    if prefix in DEFAULT_ENDPOINTS:
        return prefix
    return None


def detect_provider_from_headers(headers: dict) -> Optional[str]:
    """Detect the LLM provider from request headers."""
    if headers.get("X-Llm-Provider"):
        return headers["X-Llm-Provider"].lower()
    if "Anthropic-Version" in headers:
        return "anthropic"
    return None


def strip_provider_prefix(path: str) -> str:
    """Remove the /provider/ prefix from the path before forwarding."""
    parts = path.strip("/").split("/", 1)
    if len(parts) > 1 and parts[0].lower() in DEFAULT_ENDPOINTS:
        return "/" + parts[1]
    return path


def extract_openai_usage(req_body: dict, resp_body: dict) -> UsageRecord:
    """Extract usage from an OpenAI-format response."""
    model = resp_body.get("model", req_body.get("model", "unknown"))
    usage = resp_body.get("usage", {})
    cached = 0
    prompt_details = usage.get("prompt_tokens_details", {})
    if isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens", 0)
    return UsageRecord(
        model=model,
        provider="openai",
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        cached_input_tokens=cached,
        total_tokens=usage.get("total_tokens", 0),
    )


def extract_anthropic_usage(req_body: dict, resp_body: dict) -> UsageRecord:
    """Extract usage from an Anthropic-format response."""
    model = resp_body.get("model", req_body.get("model", "unknown"))
    usage = resp_body.get("usage", {})
    return UsageRecord(
        model=model,
        provider="anthropic",
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cached_input_tokens=usage.get("cache_read_input_tokens", 0),
        total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
    )


def extract_google_usage(req_body: dict, resp_body: dict) -> UsageRecord:
    """Extract usage from a Google Gemini response."""
    model = req_body.get("model", "unknown")
    metadata = resp_body.get("usageMetadata", {})
    return UsageRecord(
        model=model,
        provider="google",
        input_tokens=metadata.get("promptTokenCount", 0),
        output_tokens=metadata.get("candidatesTokenCount", 0),
        cached_input_tokens=metadata.get("cachedContentTokenCount", 0),
        total_tokens=metadata.get("totalTokenCount", 0),
    )


def extract_mistral_usage(req_body: dict, resp_body: dict) -> UsageRecord:
    """Extract usage from a Mistral-format response."""
    model = resp_body.get("model", req_body.get("model", "unknown"))
    usage = resp_body.get("usage", {})
    return UsageRecord(
        model=model,
        provider="mistral",
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        cached_input_tokens=0,
        total_tokens=usage.get("total_tokens", 0),
    )


EXTRACTORS = {
    "openai": extract_openai_usage,
    "anthropic": extract_anthropic_usage,
    "google": extract_google_usage,
    "mistral": extract_mistral_usage,
}


def is_streaming_request(req_body: dict) -> bool:
    """Check if the request asks for streaming."""
    return req_body.get("stream", False) is True


def extract_streaming_usage(chunks: list[bytes], provider: str) -> Optional[dict]:
    """Extract usage data from streaming response chunks.

    Many providers include usage in the final SSE chunk.
    """
    for chunk in reversed(chunks):
        text = chunk.decode("utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    data = json.loads(line[6:])
                    if "usage" in data or "usageMetadata" in data:
                        return data
                except json.JSONDecodeError:
                    continue
    return None


def is_completion_path(path: str) -> bool:
    """Check if this path corresponds to a completion endpoint."""
    stripped = strip_provider_prefix(path)
    for cp in COMPLETION_PATHS:
        if stripped.startswith(cp):
            return True
    if ":generateContent" in path:
        return True
    return False


def create_proxy_app(
    pricing: PricingDatabase,
    tracker: CostTracker,
    config: Optional[ProxyConfig] = None,
) -> Flask:
    """Create and configure the Flask proxy application."""
    app = Flask(__name__)
    if config is None:
        config = ProxyConfig()

    _request_count = {"value": 0}
    _total_cost = {"value": 0.0}

    @app.route("/_health", methods=["GET"])
    def health():
        return jsonify({
            "status": "healthy",
            "requests_proxied": _request_count["value"],
            "total_cost_usd": round(_total_cost["value"], 6),
        })

    @app.route("/_stats", methods=["GET"])
    def stats():
        summary = tracker.get_summary()
        return jsonify({
            "requests_proxied": _request_count["value"],
            "session_cost_usd": round(_total_cost["value"], 6),
            "all_time": summary,
        })

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def proxy_handler(path):
        full_path = "/" + path
        start_time = time.monotonic()

        # Detect provider
        provider = detect_provider_from_headers(dict(request.headers))
        if provider is None:
            provider = detect_provider_from_path(full_path)
        if provider is None:
            provider = "openai"

        # Extract project tag from X-Cost-Project header
        project = request.headers.get("X-Cost-Project", "default")

        # Build upstream URL
        target_base = DEFAULT_ENDPOINTS.get(provider, "")
        if not target_base:
            return jsonify({"error": f"Unknown provider: {provider}"}), 400

        upstream_path = strip_provider_prefix(full_path)
        upstream_url = target_base + upstream_path
        if request.query_string:
            upstream_url += "?" + request.query_string.decode("utf-8")

        # Forward headers, stripping proxy-specific ones
        skip_headers = {"host", "transfer-encoding", "connection",
                        "x-llm-provider", "x-cost-project"}
        forward_headers = {
            k: v for k, v in request.headers
            if k.lower() not in skip_headers
        }

        # Read request body
        req_body_raw = request.get_data()
        req_body = {}
        if req_body_raw:
            try:
                req_body = json.loads(req_body_raw)
            except json.JSONDecodeError:
                pass

        # Check if streaming
        streaming = is_streaming_request(req_body)

        try:
            upstream_resp = requests.request(
                method=request.method,
                url=upstream_url,
                headers=forward_headers,
                data=req_body_raw,
                stream=streaming,
                timeout=300,
            )
        except requests.RequestException as exc:
            logger.error("Upstream request failed: %s", exc)
            return jsonify({"error": f"Upstream request failed: {str(exc)}"}), 502

        elapsed = time.monotonic() - start_time

        if streaming and upstream_resp.status_code == 200:
            # For streaming, collect chunks, forward them, and extract usage at the end
            chunks = []

            def generate():
                for chunk in upstream_resp.iter_content(chunk_size=4096):
                    chunks.append(chunk)
                    yield chunk

                # After streaming completes, try to extract usage
                if is_completion_path(full_path):
                    usage_data = extract_streaming_usage(chunks, provider)
                    if usage_data:
                        extractor = EXTRACTORS.get(provider)
                        if extractor:
                            record = extractor(req_body, usage_data)
                            record.project = project
                            record.latency_ms = int(elapsed * 1000)
                            cost = pricing.calculate_cost(
                                record.model,
                                record.input_tokens,
                                record.output_tokens,
                                record.cached_input_tokens,
                            )
                            record.cost_usd = cost if cost is not None else 0.0
                            _request_count["value"] += 1
                            _total_cost["value"] += record.cost_usd
                            tracker.record_usage(record)
                            logger.info(
                                "Stream #%d | %s/%s | %d in + %d out | $%.6f | %dms",
                                _request_count["value"],
                                provider,
                                record.model,
                                record.input_tokens,
                                record.output_tokens,
                                record.cost_usd,
                                record.latency_ms,
                            )

            resp_headers = {
                k: v for k, v in upstream_resp.headers.items()
                if k.lower() not in {"transfer-encoding", "connection", "content-encoding"}
            }
            return Response(
                generate(),
                status=upstream_resp.status_code,
                headers=resp_headers,
                content_type=upstream_resp.headers.get("Content-Type"),
            )

        # Non-streaming response
        resp_body_raw = upstream_resp.content

        if is_completion_path(full_path) and upstream_resp.status_code == 200:
            try:
                resp_body = json.loads(resp_body_raw)
                extractor = EXTRACTORS.get(provider)
                if extractor:
                    record = extractor(req_body, resp_body)
                    record.project = project
                    record.latency_ms = int(elapsed * 1000)

                    cost = pricing.calculate_cost(
                        record.model,
                        record.input_tokens,
                        record.output_tokens,
                        record.cached_input_tokens,
                    )
                    record.cost_usd = cost if cost is not None else 0.0
                    _request_count["value"] += 1
                    _total_cost["value"] += record.cost_usd

                    tracker.record_usage(record)

                    logger.info(
                        "Request #%d | %s/%s | %d in + %d out tokens | $%.6f | %dms",
                        _request_count["value"],
                        provider,
                        record.model,
                        record.input_tokens,
                        record.output_tokens,
                        record.cost_usd,
                        record.latency_ms,
                    )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.debug("Could not extract usage from response: %s", exc)

        # Filter response headers
        resp_headers = {
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in {"transfer-encoding", "connection", "content-encoding"}
        }

        return Response(
            resp_body_raw,
            status=upstream_resp.status_code,
            headers=resp_headers,
        )

    return app


def start_proxy(
    host: str = "0.0.0.0",
    port: int = 8080,
    db_path: str = "costs.db",
    log_level: str = "INFO",
) -> None:
    """Start the Flask proxy server."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    config = ProxyConfig(host=host, port=port, db_path=db_path, log_level=log_level)
    pricing = PricingDatabase()
    tracker = CostTracker(db_path)

    app = create_proxy_app(pricing, tracker, config)

    logger.info("LLM Cost Monitor proxy starting on %s:%d", host, port)
    logger.info("Database: %s", db_path)
    logger.info("Route requests to http://%s:%d/<provider>/v1/...", host, port)

    app.run(host=host, port=port, debug=False, threaded=True)
