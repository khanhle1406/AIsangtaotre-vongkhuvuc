"""Explicit Gemini development transport with persistent, conservative batch limits."""

import fcntl
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.llm_agent import LLMAgent, QueryState

HELPER_CONTRACT = """
HELPER RETURN CONTRACTS (same workbook semantics as above):
cell(sheet,address): one scalar, including strings and typed dates.
cells(sheet,range): a 2D list, even for one cell; values(sheet,range): a flat list.
num(sheet,address): one numeric measure; do not apply it to a header or label.
Find rows from their full labels and section/header paths, not adjacency guesses.
data_rows(sheet, {'A':'string','B':'number'}) supports mixed column types.
Assign the final scalar/list to result; declare matching format and result_variable.
For a single text cell use result=cell('Example','C7').
For a numeric range use result=sum(values('Example','D8:D10')).
These are API shape examples, not workbook coordinates to copy.
"""


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(path)


def gateway_base(base: str) -> str:
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise ValueError("Gateway requires an HTTPS /v1 base without credentials")
    return base.rstrip("/")


def gateway_opener() -> urllib.request.OpenerDirector:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    return urllib.request.build_opener(NoRedirect())


class BatchLimits:
    """Reserve every attempt before sending; unknown usage keeps its upper bound."""

    def __init__(
        self,
        path: Path,
        seconds: float = 1800,
        attempts: int = 200,
        tokens: int = 2_000_000,
    ) -> None:
        if (
            not 0 < seconds <= 1800
            or not 0 < attempts <= 200
            or not 0 < tokens <= 2_000_000
        ):
            raise ValueError("Invalid gateway batch limits")
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self.lock, path.with_suffix(".lock").open("a") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            if not path.exists():
                atomic_json(
                    path,
                    {
                        "deadline_unix": time.time() + seconds,
                        "attempt_limit": attempts,
                        "token_limit": tokens,
                        "attempts": 0,
                        "token_upper": 0,
                        "reservations": {},
                        "usage_missing_attempts": 0,
                        "fatal_error": None,
                    },
                )

    def update(
        self,
        bound: int | None = None,
        ticket: str | None = None,
        actual: int | None = None,
        fatal: str | None = None,
    ) -> dict[str, Any]:
        with self.lock, self.path.with_suffix(".lock").open("a") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text())
            if bound is not None:
                if data["fatal_error"] or time.time() >= data["deadline_unix"]:
                    raise TimeoutError(
                        data["fatal_error"] or "Gateway batch deadline reached"
                    )
                if (
                    data["attempts"] >= data["attempt_limit"]
                    or data["token_upper"] + bound > data["token_limit"]
                ):
                    raise TimeoutError(
                        "Gateway batch request/token allowance exhausted"
                    )
                data["attempts"] += 1
                ticket = str(data["attempts"])
                data["reservations"][ticket] = bound
                data["token_upper"] += bound
            elif ticket is not None:
                reserved = data["reservations"].pop(ticket)
                if actual is None:
                    data["usage_missing_attempts"] += 1
                else:
                    data["token_upper"] += actual - reserved
                    if actual > reserved:
                        data["fatal_error"] = (
                            "Provider tokens exceeded conservative reservation"
                        )
            if fatal:
                data["fatal_error"] = fatal
            atomic_json(self.path, data)
            return {**data, "ticket": ticket}


class GatewayAgent(LLMAgent):
    """No paid fallback, no OpenRouter parameters, no implicit model changes."""

    def __init__(
        self,
        *,
        gateway_url: str,
        gateway_model: str,
        batch_limits: BatchLimits,
        thinking: str | None = "low",
        **kwargs: Any,
    ) -> None:
        if thinking not in {None, "low", "minimal"}:
            raise ValueError("Unsupported gateway thinking profile")
        if not kwargs.get("api_key"):
            raise ValueError("DEV_LLM_API_KEY is required; judge key is never used")
        self.gateway_url = gateway_base(gateway_url)
        self.batch_limits, self.thinking = batch_limits, thinking
        self.request_local = threading.local()
        kwargs.update(model=gateway_model, pricing=(0.0, 0.0), reasoning_tokens=0)
        super().__init__(**kwargs)

    def _request_url(self) -> str:
        return self.gateway_url + "/chat/completions"

    def _open_request(self, request: urllib.request.Request, timeout: float) -> Any:
        request.add_header("Connection", "close")
        return gateway_opener().open(request, timeout=timeout)

    def _read_response(self, response: Any) -> dict[str, Any]:
        if "text/event-stream" not in response.headers.get("Content-Type", ""):
            return super()._read_response(response)
        result: dict[str, Any] = {"choices": []}
        content: list[str] = []
        finish = None
        size = 0
        for line in response:
            size += len(line)
            if size > 4 * 1024**2 or time.monotonic() >= self.deadline:
                raise TimeoutError("Gateway response exceeded size/deadline limit")
            if not line.startswith(b"data:"):
                continue
            body = line[5:].strip()
            if body == b"[DONE]":
                break
            chunk = json.loads(body)
            if not isinstance(chunk, dict) or chunk.get("error"):
                raise ValueError("Gateway returned an invalid/error stream event")
            if chunk.get("model"):
                result["model"] = chunk["model"]
            if chunk.get("usage") is not None:
                result["usage"] = chunk["usage"]
            for choice in chunk.get("choices", []):
                if choice.get("index", 0) != 0:
                    raise ValueError("Unexpected multiple gateway completions")
                delta = choice.get("delta", {}).get("content")
                if delta is not None:
                    if not isinstance(delta, str):
                        raise TypeError("Invalid gateway text delta")
                    content.append(delta)
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
            usage = result.get("usage")
            if (
                finish is not None
                and isinstance(usage, dict)
                and (
                    type(usage.get("total_tokens")) is int
                    or all(
                        type(usage.get(key)) is int
                        for key in ("prompt_tokens", "completion_tokens")
                    )
                )
            ):
                # A complete response need not wait for a proxy to close its SSE
                # connection. Separate post-finish usage events remain supported.
                break
        if finish is None:
            raise ValueError("Incomplete gateway stream: missing finish reason")
        result["choices"] = [
            {"message": {"content": "".join(content)}, "finish_reason": finish}
        ]
        return result

    def _before_request(self, payload: dict[str, Any], state: QueryState) -> None:
        payload.pop("reasoning", None)
        payload.pop("usage", None)
        payload["temperature"] = 1.0
        if self.thinking is not None:
            payload["reasoning_effort"] = self.thinking
        bound = (
            sum(len(m["content"].encode()) + 64 for m in payload["messages"])
            + payload["max_tokens"]
            + len(json.dumps(payload.get("response_format", {})).encode())
            + 8192  # Gateway-added instructions/framing observed by the probe.
        )
        data = self.batch_limits.update(bound=bound)
        self.request_local.ticket = data["ticket"]
        self.request_local.bound = bound
        state.deadline = min(
            state.deadline, time.monotonic() + data["deadline_unix"] - time.time()
        )

    def _response_received(self, data: dict[str, Any], record: dict[str, Any]) -> None:
        usage = data.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise TypeError("Invalid gateway usage object")
        usage = dict(usage or {})
        actual = usage.get("total_tokens")
        if actual is None and all(
            type(usage.get(k)) is int for k in ("prompt_tokens", "completion_tokens")
        ):
            actual = usage["prompt_tokens"] + usage["completion_tokens"]
            usage["total_tokens"] = actual
        if actual is not None and (type(actual) is not int or actual < 0):
            raise ValueError("Invalid gateway token usage")
        record["usage_missing"] = actual is None
        record["tokens_estimated"] = actual is None
        record["provider_total_tokens"] = actual
        record["provider_cost_usd"] = usage.get("cost")
        record["cost_basis"] = "user-confirmed-free; provider cost recorded separately"
        if actual is None:
            usage["total_tokens"] = self.request_local.bound
        if usage.get("cost") is not None:
            cost = float(usage["cost"])
            if not math.isfinite(cost) or cost < 0:
                raise ValueError("Invalid gateway billed cost")
            if cost > 0:
                self.fatal_error = (
                    "Gateway reported positive cost; reconciliation required"
                )
                self.batch_limits.update(fatal=self.fatal_error)
        data["usage"] = usage

    def _request_finished(self, record: dict[str, Any]) -> None:
        record["reserved_token_bound"] = self.request_local.bound
        record["thinking"] = self.thinking or "unknown"
        record["temperature"] = 1.0
        self.batch_limits.update(
            ticket=self.request_local.ticket, actual=record.get("provider_total_tokens")
        )


def gateway_settings(development_model: str | None = None) -> dict[str, str]:
    values = {
        name: os.getenv(name)
        for name in ("DEV_LLM_BASE_URL", "DEV_LLM_API_KEY", "DEV_LLM_MODEL")
    }
    if not all(values.values()):
        raise ValueError(
            "DEV_LLM_BASE_URL, DEV_LLM_API_KEY and DEV_LLM_MODEL are required"
        )
    return {
        "gateway_url": gateway_base(values["DEV_LLM_BASE_URL"]),
        "api_key": values["DEV_LLM_API_KEY"],
        "gateway_model": development_model or values["DEV_LLM_MODEL"],
    }
