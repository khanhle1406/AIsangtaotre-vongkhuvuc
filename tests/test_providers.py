"""Development transport cannot leak the judge key or silently change models."""

import io
import json
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from benchmarks.providers import (
    FREE_DEVELOPMENT_MODEL,
    FreeDevelopmentAgent,
    provider_transport,
)
from src.llm_agent import DEFAULT_MODEL, LLMAgent, QueryState, retry_after_seconds


def free_catalog() -> dict[str, Any]:
    return {
        "id": FREE_DEVELOPMENT_MODEL,
        "pricing": {"prompt": "0", "completion": "0"},
        "context_length": 262144,
        "supported_parameters": [
            "reasoning",
            "response_format",
            "temperature",
            "max_tokens",
        ],
    }


def test_free_transport_checks_catalog_and_account_quota() -> None:
    module = SimpleNamespace(OPENROUTER_URL="original")
    quota = {"used": 1, "limit": 50, "remaining": 49}
    responses = [
        {"data": [free_catalog()]},
        {"data": {"free_model_daily_requests": quota}},
    ]
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-placeholder"}),
        patch(
            "urllib.request.urlopen",
            side_effect=[io.BytesIO(json.dumps(r).encode()) for r in responses],
        ),
        provider_transport("openrouter-free", module) as transport,
    ):
        assert transport["pricing"] == (0.0, 0.0)
        assert transport["client_kwargs"]["free_request_limit"] == 49
        assert transport["catalog_model"]["id"] == FREE_DEVELOPMENT_MODEL
    assert module.OPENROUTER_URL == "original"
    assert DEFAULT_MODEL == "qwen/qwen3.7-flash"


@pytest.mark.parametrize("price", ["0.0001", "NaN", "-1"])
def test_free_transport_rejects_nonzero_or_invalid_pricing(price: str) -> None:
    model = free_catalog()
    model["pricing"]["completion"] = price
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-placeholder"}),
        patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps({"data": [model]}).encode()),
        ) as request,
        pytest.raises(ValueError, match="pricing"),
        provider_transport(
            "openrouter-free", SimpleNamespace(OPENROUTER_URL="original")
        ),
    ):
        pytest.fail("Paid pricing must never be accepted")
    assert request.call_count == 1


def test_free_transport_rejects_exhausted_quota_before_inference() -> None:
    responses = [
        {"data": [free_catalog()]},
        {"data": {"free_model_daily_requests": {"remaining": 0}}},
    ]
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-placeholder"}),
        patch(
            "urllib.request.urlopen",
            side_effect=[io.BytesIO(json.dumps(r).encode()) for r in responses],
        ) as request,
        pytest.raises(ValueError, match="quota"),
        provider_transport(
            "openrouter-free", SimpleNamespace(OPENROUTER_URL="original")
        ),
    ):
        pytest.fail("No request may be sent after the quota is exhausted")
    assert request.call_count == 2


@pytest.mark.parametrize("model", ["qwen/qwen3.7-flash", "openrouter/free"])
def test_free_transport_requires_a_pinned_free_model(model: str) -> None:
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-placeholder"}),
        patch("urllib.request.urlopen") as request,
        pytest.raises(ValueError, match="pinned"),
        provider_transport("openrouter-free", SimpleNamespace(), model),
    ):
        pytest.fail(
            "Paid variants and random routing are unsuitable for reproducible testing"
        )
    request.assert_not_called()


def test_free_agent_paces_retries_and_enforces_the_run_request_cap() -> None:
    client = FreeDevelopmentAgent(
        free_catalog=free_catalog(),
        free_request_limit=2,
        api_key="test-placeholder",
        pricing=(0.0, 0.0),
    )
    error = urllib.error.HTTPError("https://example.invalid", 429, "Limited", {}, None)
    result = {
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {"cost": 0, "total_tokens": 2},
    }
    state = QueryState(time.monotonic() + 60, 0.09)
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=[error, io.BytesIO(json.dumps(result).encode())],
        ) as request,
        patch("time.sleep") as sleep,
    ):
        assert client._request([{"role": "user", "content": "test"}], state) == "{}"
        assert sleep.call_count == 2
        payload = json.loads(request.call_args.args[0].data)
        assert payload["model"] == FREE_DEVELOPMENT_MODEL
        assert payload["provider"]["max_price"] == {
            "prompt": 0,
            "completion": 0,
            "request": 0,
            "image": 0,
        }
        with pytest.raises(ValueError, match="allowance"):
            client._request([{"role": "user", "content": "next"}], state)
        assert request.call_count == 2 and state.cost == 0


def test_free_agent_checks_the_replacement_context_before_sending() -> None:
    model = free_catalog()
    model["context_length"] = 3000
    client = FreeDevelopmentAgent(
        free_catalog=model,
        free_request_limit=2,
        api_key="test-placeholder",
        pricing=(0.0, 0.0),
    )
    with (
        patch("urllib.request.urlopen") as request,
        pytest.raises(ValueError, match="context"),
    ):
        client._request(
            [{"role": "user", "content": "x" * 1500}],
            QueryState(time.monotonic() + 60, 0.09),
        )
    request.assert_not_called()


def test_development_transport_uses_its_own_key_and_restores_url() -> None:
    module = SimpleNamespace(
        OPENROUTER_URL="https://openrouter.ai/api/v1/chat/completions"
    )
    catalog = {
        "data": [
            {
                "id": "qwen3.7-flash",
                "aliases": ["qwen/qwen3.7-flash"],
                "pricing": {"prompt": "3e-8", "completion": "1.3e-7"},
                "pricing_tiers": [{"prompt": "2e-7", "completion": "8e-7"}],
            }
        ]
    }
    with (
        patch.dict(
            "os.environ",
            {
                "BAZAARLINK_API_KEY": "test-bazaar-placeholder",
                "OPENROUTER_API_KEY": "test-judge-placeholder",
            },
            clear=True,
        ),
        patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(catalog).encode()),
        ) as request,
    ):
        with provider_transport("bazaarlink", module) as transport:
            assert transport["api_key"] == "test-bazaar-placeholder"
            assert transport["pricing"] == (2e-7, 8e-7)
            assert (
                module.OPENROUTER_URL == "https://api.bazaarlink.ai/v1/chat/completions"
            )
        assert (
            request.call_args.args[0].get_header("Authorization")
            == "Bearer test-bazaar-placeholder"
        )
    assert module.OPENROUTER_URL == "https://openrouter.ai/api/v1/chat/completions"


def test_missing_development_key_never_falls_back_to_judge_key() -> None:
    module = SimpleNamespace(OPENROUTER_URL="original")
    with (
        patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": "test-placeholder"}, clear=True
        ),
        pytest.raises(ValueError, match="BAZAARLINK_API_KEY"),
        provider_transport("bazaarlink", module),
    ):
        pytest.fail("Must not use a different provider's credential")


def test_provider_never_substitutes_another_model() -> None:
    module = SimpleNamespace(OPENROUTER_URL="original")
    payload = {
        "data": [
            {"id": "other-model", "pricing": {"prompt": "1e-7", "completion": "1e-7"}}
        ]
    }
    with (
        patch.dict("os.environ", {"BAZAARLINK_API_KEY": "test-placeholder"}),
        patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode()),
        ),
        pytest.raises(ValueError, match="Required model"),
        provider_transport("bazaarlink", module),
    ):
        pytest.fail("No model substitute is authorized")


@pytest.mark.parametrize(
    "header,expected",
    [(None, None), ("invalid", None), ("NaN", None), ("7", 7.0), ("-1", 0.0)],
)
def test_retry_after_parser(header: str | None, expected: float | None) -> None:
    assert retry_after_seconds(header) == expected


def test_retry_respects_server_delay_with_same_request_and_budget_caps() -> None:
    client = LLMAgent("test-placeholder", pricing=(2e-7, 8e-7))
    state = QueryState(time.monotonic() + 60, 0.09)
    error = urllib.error.HTTPError(
        "https://example.invalid", 429, "Limited", {"Retry-After": "7"}, None
    )
    result = {
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {"cost": 0, "total_tokens": 2},
    }
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=[error, io.BytesIO(json.dumps(result).encode())],
        ),
        patch("time.sleep") as sleep,
    ):
        assert client._request([{"role": "user", "content": "test"}], state) == "{}"
    sleep.assert_called_once_with(7.0)
    assert state.requests == 2 and state.cost > 0


def test_daily_quota_stops_all_further_requests_without_long_sleep() -> None:
    client = LLMAgent("test-placeholder", pricing=(2e-7, 8e-7))
    error = urllib.error.HTTPError(
        "https://example.invalid", 429, "Daily quota", {"Retry-After": "79511"}, None
    )
    with (
        patch("urllib.request.urlopen", side_effect=error) as request,
        patch("time.sleep") as sleep,
    ):
        with pytest.raises(TimeoutError, match="Rate limit reset"):
            client._request(
                [{"role": "user", "content": "test"}],
                QueryState(time.monotonic() + 60, 0.09),
            )
        with pytest.raises(ValueError, match="Rate limit reset"):
            client._request(
                [{"role": "user", "content": "next"}],
                QueryState(time.monotonic() + 60, 0.09),
            )
    assert request.call_count == 1
    sleep.assert_not_called()


def test_fresh_holdout_is_grouped_and_formula_oracle_is_independent(
    tmp_path: Path,
) -> None:
    from benchmarks.holdout import generate
    from evaluate import read_answers
    from run import validate_queries
    from src.excel_parser import load_workbook_data
    from src.executor import execute_program

    root = tmp_path / "holdout"
    queries_path, references_path = generate(root, seed=71931)
    queries = validate_queries(queries_path, root / "xlsx_files")
    references = read_answers(references_path)
    assert len(queries) == len(references) == 18
    assert len({query["family"] for query in queries}) == 3
    workbook = load_workbook_data(root / "xlsx_files/joined_projects.xlsx").wire()
    execution = execute_program("result=cell('Checks','B1')", workbook)
    assert execution.success and str(execution.result) == references["unseen-011"]
    with pytest.raises(ValueError, match="Preserve holdout"):
        generate(root)


def test_daily_error_code_is_logged_without_echoing_provider_message() -> None:
    client = LLMAgent("test-placeholder", pricing=(2e-7, 8e-7))
    body = io.BytesIO(
        json.dumps(
            {"error": {"code": "free_daily_limit", "message": "sensitive-placeholder"}}
        ).encode()
    )
    error = urllib.error.HTTPError("https://example.invalid", 429, "Limited", {}, body)
    state = QueryState(time.monotonic() + 60, 0.09)
    with (
        patch("urllib.request.urlopen", side_effect=error),
        pytest.raises(TimeoutError, match="daily quota"),
    ):
        client._request([{"role": "user", "content": "test"}], state)
    assert state.calls[0]["provider_error_code"] == "free_daily_limit"
    assert "sensitive-placeholder" not in json.dumps(state.calls)
