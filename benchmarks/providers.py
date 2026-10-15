"""Explicit development-only transport; the submission CLI remains OpenRouter."""

import json
import math
import os
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any
from unittest.mock import patch

from src.llm_agent import DEFAULT_MODEL, LLMAgent, QueryState

FREE_DEVELOPMENT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class FreeDevelopmentAgent(LLMAgent):
    """Pin a verified free model and pace all HTTP attempts, including retries."""

    def __init__(
        self,
        *,
        free_catalog: dict[str, Any],
        free_request_limit: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=free_catalog["id"], **kwargs)
        self.free_context = int(free_catalog["context_length"])
        self.free_request_limit = free_request_limit
        self.free_requests = 0
        self.free_next_request = 0.0
        self.free_request_lock = threading.Lock()

    def _before_request(self, payload: dict[str, Any], state: QueryState) -> None:
        bound = (
            sum(
                len(message["content"].encode()) + 64 for message in payload["messages"]
            )
            + payload["max_tokens"]
        )
        if bound > self.free_context * 0.95:
            raise ValueError("Workbook prompt exceeds development model context")
        payload["provider"] = {
            "require_parameters": True,
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
        }
        with self.free_request_lock:
            if self.free_requests >= self.free_request_limit:
                self.fatal_error = "Free development request allowance exhausted"
                raise ValueError(self.fatal_error)
            delay = max(0.0, self.free_next_request - time.monotonic())
            if delay >= state.deadline - time.monotonic() - 1:
                raise TimeoutError("Free request pacing exceeds remaining deadline")
            if delay:
                time.sleep(delay)
            self.free_next_request = time.monotonic() + 3.1
            self.free_requests += 1


@contextmanager
def provider_transport(
    provider: str,
    module: ModuleType,
    development_model: str | None = None,
    local_base_url: str = "http://127.0.0.1:8000/v1",
) -> Iterator[dict[str, Any]]:
    if provider == "gateway":
        from .gateway import GatewayAgent, gateway_opener, gateway_settings

        settings = gateway_settings(development_model)
        request = urllib.request.Request(
            settings["gateway_url"] + "/models",
            headers={
                "Authorization": "Bearer " + settings["api_key"],
                "Connection": "close",
            },
        )
        with gateway_opener().open(request, timeout=25) as response:
            models = json.load(response)["data"]
        matching = [
            model for model in models if model.get("id") == settings["gateway_model"]
        ]
        if len(matching) != 1:
            raise ValueError("Gateway model unavailable; no automatic substitute")
        yield {
            "api_key": settings.pop("api_key"),
            "pricing": (0.0, 0.0),
            "base_url": settings["gateway_url"],
            "catalog_model": matching[0],
            "client_class": GatewayAgent,
            "client_kwargs": settings,
        }
        return
    if provider == "colab-local":
        from .colab_local import LOCAL_MODEL, LocalDevelopmentAgent, loopback_url

        if development_model not in {None, LOCAL_MODEL}:
            raise ValueError("Only the pinned Qwen T4 development model is supported")
        base = loopback_url(local_base_url)
        yield {
            "api_key": "local-development-placeholder",
            "pricing": (0.0, 0.0),
            "base_url": base,
            "client_class": LocalDevelopmentAgent,
            "client_kwargs": {"local_base_url": base},
        }
        return
    if development_model is not None and provider != "openrouter-free":
        raise ValueError("Development model selection requires openrouter-free")
    if provider == "openrouter-free":
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is not configured")
        model_id = development_model or FREE_DEVELOPMENT_MODEL
        if not model_id.endswith(":free"):
            raise ValueError("Development model must be a pinned :free variant")
        with urllib.request.urlopen(
            OPENROUTER_BASE + "/models", timeout=25
        ) as response:
            models = json.load(response)["data"]
        matching = [model for model in models if model.get("id") == model_id]
        if len(matching) != 1:
            raise ValueError("Free model unavailable; no automatic substitute")
        model = matching[0]
        rates = [model["pricing"], *model.get("pricing_tiers", [])]
        if any(
            not {"prompt", "completion"} <= rate.keys()
            or any(float(value) != 0 for value in rate.values())
            for rate in rates
        ):
            raise ValueError("Free model has nonzero or invalid pricing")
        if not {"reasoning", "response_format", "temperature", "max_tokens"} <= set(
            model.get("supported_parameters", [])
        ):
            raise ValueError("Free model lacks required pipeline parameters")
        if (
            not isinstance(model.get("context_length"), int)
            or model["context_length"] <= 0
        ):
            raise ValueError("Invalid free model context length")
        request = urllib.request.Request(
            OPENROUTER_BASE + "/key", headers={"Authorization": f"Bearer {key}"}
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            quota = json.load(response)["data"].get("free_model_daily_requests")
        remaining = quota.get("remaining") if isinstance(quota, dict) else None
        if type(remaining) is not int or remaining <= 0:
            raise ValueError("Free daily quota unavailable or exhausted")
        with patch.object(
            module, "OPENROUTER_URL", OPENROUTER_BASE + "/chat/completions"
        ):
            yield {
                "api_key": key,
                "pricing": (0.0, 0.0),
                "base_url": OPENROUTER_BASE,
                "catalog_model": model,
                "free_quota": quota,
                "client_class": FreeDevelopmentAgent,
                "client_kwargs": {
                    "free_catalog": model,
                    "free_request_limit": remaining,
                },
            }
        return
    if provider == "openrouter":
        yield {
            "api_key": None,
            "pricing": None,
            "base_url": "https://openrouter.ai/api/v1",
        }
        return
    if provider != "bazaarlink":
        raise ValueError("Unknown development provider")
    key = os.getenv("BAZAARLINK_API_KEY")
    if not key:
        raise ValueError("BAZAARLINK_API_KEY is not configured")
    base = "https://api.bazaarlink.ai/v1"
    request = urllib.request.Request(
        base + "/models", headers={"Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        models = json.load(response)["data"]
    matching = [
        model
        for model in models
        if model.get("id") == DEFAULT_MODEL or DEFAULT_MODEL in model.get("aliases", [])
    ]
    if len(matching) != 1:
        raise ValueError(
            "Required model not uniquely available; no automatic substitute"
        )
    model = matching[0]
    rates = [model["pricing"], *model.get("pricing_tiers", [])]
    pricing = tuple(
        max(float(rate[field]) for rate in rates) for field in ("prompt", "completion")
    )
    if not all(math.isfinite(value) and value > 0 for value in pricing):
        raise ValueError("Invalid provider pricing; cannot reserve budget")
    # Set once per experiment, outside all worker threads, then restore on exit.
    with patch.object(module, "OPENROUTER_URL", base + "/chat/completions"):
        yield {
            "api_key": key,
            "pricing": pricing,
            "base_url": base,
            "catalog_model": model,
        }
