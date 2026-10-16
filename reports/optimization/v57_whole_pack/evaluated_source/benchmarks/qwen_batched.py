"""Opt-in official Qwen transport for the same keyed workbook planning pipeline."""

import math
import threading
from typing import Any

from src.llm_agent import DEFAULT_MODEL, LLMAgent, QueryState

from .batched import BatchPlanningMixin
from .precision import ACCURACY_CONTRACT
from .structured_batch import StructuredPlanningMixin


class QwenBatchedAgent(StructuredPlanningMixin, BatchPlanningMixin, LLMAgent):
    """No Gemini routing/settings; paid calls retain the ordinary conservative ledger."""

    def __init__(self, *, model: str = DEFAULT_MODEL, **kwargs: Any) -> None:
        if model != DEFAULT_MODEL:
            raise ValueError("Official batching requires the competition Qwen model")
        kwargs.update(compact_prompt=True, iterator_helpers=True, json_schema=False)
        super().__init__(model=model, **kwargs)
        self.usage_state = threading.local()

    def _request(self, messages: list[dict[str, str]], state: QueryState) -> str:
        augmented = [dict(message) for message in messages]
        augmented[-1]["content"] += "\n" + ACCURACY_CONTRACT
        try:
            return super()._request(augmented, state)
        finally:
            # Failed/unknown requests are accounted in _request_finished too;
            # include them in per-question totals, not only successful responses.
            state.tokens = sum(call["tokens"] for call in state.calls)

    def _before_request(self, payload: dict[str, Any], state: QueryState) -> None:
        super()._before_request(payload, state)
        self.usage_state.token_bound = math.ceil(
            1.1
            * (
                sum(len(m["content"].encode()) + 64 for m in payload["messages"])
                + payload["max_tokens"]
            )
        )

    def _response_received(self, data: dict[str, Any], record: dict[str, Any]) -> None:
        super()._response_received(data, record)
        raw = data.get("usage")
        if raw is not None and not isinstance(raw, dict):
            raise TypeError("Invalid OpenRouter usage object")
        usage = dict(raw or {})
        actual = usage.get("total_tokens")
        if actual is None and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("prompt_tokens", "completion_tokens")
        ):
            actual = usage["prompt_tokens"] + usage["completion_tokens"]
        if actual is not None and (type(actual) is not int or actual < 0):
            raise ValueError("Invalid OpenRouter token count")
        cost = usage.get("cost")
        if cost is not None:
            if isinstance(cost, bool):
                raise ValueError("Invalid billed cost")
            cost = float(cost)
            if not math.isfinite(cost) or cost < 0:
                raise ValueError("Invalid billed cost")
            usage["cost"] = cost
            if cost > record["reserved_usd"] + 1e-12:
                self.fatal_error = "Billed cost exceeded the reserved upper bound"
        record.update(
            provider_total_tokens=actual,
            usage_missing=actual is None,
            tokens_estimated=actual is None,
            provider_cost_usd=cost,
        )
        usage["total_tokens"] = (
            actual if actual is not None else self.usage_state.token_bound
        )
        data["usage"] = usage

    def _request_finished(self, record: dict[str, Any]) -> None:
        record["reserved_token_bound"] = self.usage_state.token_bound
        if "usage_missing" not in record:
            record.update(
                provider_total_tokens=None,
                usage_missing=True,
                tokens_estimated=True,
                tokens=self.usage_state.token_bound,
            )
        record["provider"] = "openrouter"
