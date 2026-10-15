"""Gateway routing, streaming, quotas and resume must fail closed without paid calls."""

import io
import json
import time
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from benchmarks.gateway import BatchLimits, GatewayAgent, gateway_base, gateway_settings
from benchmarks.gateway_runner import checkpoint, fingerprint, select_profile
from src.llm_agent import DEFAULT_MODEL, BudgetExceeded, QueryState


class Response(io.BytesIO):
    def __init__(self, data: bytes, content_type: str = "application/json") -> None:
        super().__init__(data)
        self.headers = {"Content-Type": content_type}


def make_agent(tmp_path: Path, **kwargs: Any) -> GatewayAgent:
    return GatewayAgent(
        api_key="test-placeholder",
        gateway_url="https://gateway.invalid/v1",
        gateway_model="ag/gemini-3-flash",
        batch_limits=BatchLimits(tmp_path / "batch.json"),
        **kwargs,
    )


def completion(usage: dict[str, Any] | None = None) -> Response:
    return Response(
        json.dumps(
            {
                "model": "gemini-3-flash",
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": usage,
            }
        ).encode()
    )


def test_gateway_payload_and_missing_usage_are_explicit(tmp_path: Path) -> None:
    a = make_agent(tmp_path)
    s = QueryState(time.monotonic() + 60, 0.09)
    with patch.object(a, "_open_request", return_value=completion()) as request:
        assert a._request([{"role": "user", "content": "hello"}], s) == "{}"
    req = request.call_args.args[0]
    body = json.loads(req.data)
    assert req.full_url == "https://gateway.invalid/v1/chat/completions"
    assert body["reasoning_effort"] == "low" and body["temperature"] == 1
    assert "reasoning" not in body and "usage" not in body
    assert s.calls[0]["tokens_estimated"] and s.tokens > 8192
    assert s.calls[0]["provider_cost_usd"] is None
    assert DEFAULT_MODEL == "qwen/qwen3.7-flash"


def test_adaptive_thinking_is_per_query_and_does_not_change_fixed_baseline(
    tmp_path: Path,
) -> None:
    agent = make_agent(tmp_path, adaptive_thinking=True)
    states = [
        QueryState(
            time.monotonic() + 60, 0.09, question="How many more across all categories?"
        ),
        QueryState(time.monotonic() + 60, 0.09, requests=2, question="Lookup value"),
        QueryState(time.monotonic() + 60, 0.09, question="Lookup value"),
    ]
    with patch.object(
        agent, "_open_request", side_effect=[completion() for _ in states]
    ) as calls:
        for state in states:
            agent._request([{"role": "user", "content": "Return JSON"}], state)
    assert [
        json.loads(call.args[0].data)["reasoning_effort"]
        for call in calls.call_args_list
    ] == ["low", "high", "low"]
    assert [state.calls[-1]["thinking"] for state in states] == ["low", "high", "low"]
    fixed = make_agent(tmp_path / "fixed")
    with patch.object(fixed, "_open_request", return_value=completion()) as call:
        fixed._request(
            [{"role": "user", "content": "Return JSON"}],
            QueryState(time.monotonic() + 60, 0.09, requests=1),
        )
    assert json.loads(call.call_args.args[0].data)["reasoning_effort"] == "low"


def test_stream_heartbeats_cannot_extend_the_attempt_deadline(tmp_path: Path) -> None:
    a = make_agent(tmp_path)
    a.request_local.response_deadline = time.monotonic() - 1
    assert a.deadline > time.monotonic()
    with pytest.raises(TimeoutError, match="deadline"):
        a._read_response(Response(b": keepalive\n\n", "text/event-stream"))


def test_timed_out_stream_retains_unknown_usage_in_totals(tmp_path: Path) -> None:
    a = make_agent(tmp_path)

    class Heartbeat(Response):
        def __init__(self) -> None:
            super().__init__(b"", "text/event-stream")
            a.request_local.response_deadline = time.monotonic() - 1

        def __iter__(self) -> Any:
            yield b": keepalive\n"

    state = QueryState(time.monotonic() + 60, 0.09)
    with (
        patch.object(
            a,
            "_open_request",
            side_effect=lambda *args, **kwargs: Heartbeat(),
        ),
        patch("src.llm_agent.time.sleep"),
        pytest.raises(TimeoutError),
    ):
        a._request([{"role": "user", "content": "Read workbook"}], state)
    assert state.requests == 5 and state.tokens > 0
    assert state.tokens == sum(call["reserved_token_bound"] for call in state.calls)
    assert all(
        call["usage_missing"] and call["provider_total_tokens"] is None
        for call in state.calls
    )


def test_streaming_gateway_preserves_usage_and_detects_truncation(
    tmp_path: Path,
) -> None:
    a = make_agent(tmp_path)
    chunks = [
        {
            "model": "gemini-3-flash",
            "choices": [{"delta": {"content": '{"ok":'}, "index": 0}],
        },
        {
            "choices": [{"delta": {"content": "true}"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 2000,
                "completion_tokens": 5,
                "total_tokens": 2005,
            },
        },
    ]
    body = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)
    with patch.object(
        a, "_open_request", return_value=Response(body, "text/event-stream")
    ):
        s = QueryState(time.monotonic() + 60, 0.09)
        assert json.loads(a._request([{"role": "user", "content": "hello"}], s)) == {
            "ok": True
        }
    assert s.tokens == 2005 and not s.calls[0]["tokens_estimated"]
    with pytest.raises(ValueError, match="missing finish"):
        a._read_response(Response(b'data: {"choices":[]}\n\n', "text/event-stream"))


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_gateway_retries_count_against_same_batch(tmp_path: Path, code: int) -> None:
    a = make_agent(tmp_path)
    error = urllib.error.HTTPError(
        "https://gateway.invalid", code, "temporary", {}, io.BytesIO(b"{}")
    )
    with (
        patch.object(
            a, "_open_request", side_effect=[error, completion({"total_tokens": 20})]
        ),
        patch("time.sleep"),
    ):
        a._request(
            [{"role": "user", "content": "x"}], QueryState(time.monotonic() + 60, 0.09)
        )
    assert a.batch_limits.update()["attempts"] == 2
    assert a.batch_limits.update()["usage_missing_attempts"] == 1


@pytest.mark.parametrize("code", [401, 402, 403])
def test_gateway_auth_and_quota_stop_without_fallback(
    tmp_path: Path, code: int
) -> None:
    a = make_agent(tmp_path)
    error = urllib.error.HTTPError(
        "https://gateway.invalid", code, "denied", {}, io.BytesIO(b"{}")
    )
    with (
        patch.object(a, "_open_request", side_effect=error) as request,
        pytest.raises(ValueError),
    ):
        a._request(
            [{"role": "user", "content": "x"}], QueryState(time.monotonic() + 60, 0.09)
        )
    assert request.call_count == 1 and a.fatal_error


def test_positive_gateway_cost_stops_batch(tmp_path: Path) -> None:
    a = make_agent(tmp_path)
    with (
        patch.object(
            a,
            "_open_request",
            return_value=completion({"cost": 0.001, "total_tokens": 4}),
        ),
        pytest.raises(BudgetExceeded),
    ):
        a._request(
            [{"role": "user", "content": "x"}], QueryState(time.monotonic() + 60, 0.09)
        )
    assert a.fatal_error and a.batch_limits.update()["fatal_error"]
    assert a.total_cost == 0.001


def test_timeout_keeps_conservative_reservations(tmp_path: Path) -> None:
    a = make_agent(tmp_path)
    with (
        patch.object(a, "_open_request", side_effect=TimeoutError),
        patch("time.sleep"),
        pytest.raises(TimeoutError),
    ):
        a._request(
            [{"role": "user", "content": "x"}], QueryState(time.monotonic() + 60, 0.09)
        )
    data = a.batch_limits.update()
    assert (
        data["attempts"] == 5
        and data["usage_missing_attempts"] == 5
        and data["token_upper"] > 0
    )


def test_persistent_limits_survive_resume_and_reject_overflow(tmp_path: Path) -> None:
    b = BatchLimits(tmp_path / "batch.json", attempts=2, tokens=50)
    first = b.update(bound=40)
    with pytest.raises(TimeoutError):
        b.update(bound=11)
    b.update(ticket=first["ticket"], actual=10)
    b = BatchLimits(tmp_path / "batch.json")
    b.update(bound=30)
    with pytest.raises(TimeoutError):
        b.update(bound=1)
    assert b.update()["attempts"] == 2 and b.update()["token_upper"] == 40


def test_checkpoint_rejects_source_data_model_config_changes(tmp_path: Path) -> None:
    (tmp_path / "one.xlsx").write_bytes(b"workbook")
    q = [{"id": "x", "file_name": "one.xlsx", "query": "question"}]
    config = {"helper_contract": False, "model": "one"}
    first = fingerprint(tmp_path, q, config)
    path = tmp_path / "checkpoint.json"
    path.write_text(
        json.dumps({"fingerprint": first, "records": {"x": {"answer": "a"}}})
    )
    assert checkpoint(path, first)["records"]["x"]["answer"] == "a"
    config["model"] = "two"
    with pytest.raises(ValueError, match="mismatch"):
        checkpoint(path, fingerprint(tmp_path, q, config))
    config["model"] = "one"
    (tmp_path / "one.xlsx").write_bytes(b"changed")
    with pytest.raises(ValueError, match="mismatch"):
        checkpoint(path, fingerprint(tmp_path, q, config))


def test_selection_requires_complete_runs_and_prioritizes_exact_match() -> None:
    report = {
        "generation_complete": True,
        "fatal_error": None,
        "score": {"correct": 8},
        "mean_query_seconds": 5,
        "tokens": 100,
    }
    reports = {
        "A": report,
        "B": {**report, "mean_query_seconds": 1, "score": {"correct": 7}},
        "C": {**report, "mean_query_seconds": 0.5, "generation_complete": False},
    }
    assert select_profile(reports) == "A"


@pytest.mark.parametrize(
    "base",
    [
        "http://gateway.invalid/v1",
        "https://u:p@gateway.invalid/v1",
        "https://gateway.invalid/v1?token=x",
    ],
)
def test_gateway_rejects_unsafe_base(base: str) -> None:
    with pytest.raises(ValueError):
        gateway_base(base)


def test_gateway_never_uses_judge_key() -> None:
    with (
        patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": "judge-placeholder"}, clear=True
        ),
        pytest.raises(ValueError, match="DEV_LLM"),
    ):
        gateway_settings()


def test_c_contract_reaches_the_final_user_message_without_mutation(
    tmp_path: Path,
) -> None:
    from benchmarks.gateway_runner import HELPER_CONTRACT, PromptedGatewayAgent

    agent = PromptedGatewayAgent(
        api_key="test-placeholder",
        gateway_url="https://gateway.invalid/v1",
        gateway_model="ag/gemini-3-flash",
        batch_limits=BatchLimits(tmp_path / "batch.json"),
    )
    agent.helper_instructions = HELPER_CONTRACT
    messages = [
        {"role": "system", "content": "original"},
        {"role": "user", "content": "task"},
    ]
    with patch.object(
        agent, "_open_request", return_value=completion({"total_tokens": 42})
    ) as request:
        agent._request(messages, QueryState(time.monotonic() + 60, 0.09))
    payload = json.loads(request.call_args.args[0].data)
    assert "Return ONE JSON object" in payload["messages"][-1]["content"]
    assert messages[-1]["content"] == "task"


def test_resume_does_not_send_a_completed_question_again(tmp_path: Path) -> None:
    import csv

    import openpyxl

    from benchmarks.gateway_runner import run_stage

    files = tmp_path / "xlsx_files"
    files.mkdir()
    wb = openpyxl.Workbook()
    wb.active.title = "Data"
    wb.active.append(["Group", "Units"])
    wb.active.append(["Alpha", 7])
    wb.save(files / "renamed.xlsx")
    wb.close()
    queries = [
        {
            "id": "changed",
            "file_name": "renamed.xlsx",
            "query": "How many units for Alpha? Answer with only the integer.",
        }
    ]
    refs = tmp_path / "gold.csv"
    with refs.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "answer"])
        writer.writeheader()
        writer.writerow({"id": "changed", "answer": "7"})
    program = json.dumps(
        {"code": "result=num('Data','B2')", "format": {"kind": "integer"}}
    )

    def response(*_args: Any, **_kwargs: Any) -> Response:
        return Response(
            json.dumps(
                {
                    "model": "gemini-3-flash",
                    "choices": [
                        {"message": {"content": program}, "finish_reason": "stop"}
                    ],
                    "usage": {"total_tokens": 50},
                }
            ).encode()
        )

    environment = {
        "DEV_LLM_BASE_URL": "https://gateway.invalid/v1",
        "DEV_LLM_API_KEY": "test-placeholder",
        "DEV_LLM_MODEL": "ag/gemini-3-flash",
    }
    limits = BatchLimits(tmp_path / "batch.json")
    with (
        patch.dict("os.environ", environment),
        patch.object(GatewayAgent, "_open_request", side_effect=response) as request,
    ):
        first = run_stage(tmp_path / "stage", files, queries, refs, "C", limits)
        resumed = run_stage(tmp_path / "stage", files, queries, refs, "C", limits)
    assert first["score"]["correct"] == 1 and resumed["score"]["correct"] == 1
    assert request.call_count == 1 and limits.update()["attempts"] == 1


def test_qwen_credit_failure_sends_no_inference(tmp_path: Path) -> None:
    from benchmarks.compare import source_hash
    from benchmarks.qwen_signoff import signoff

    (tmp_path / "candidate_lock.json").write_text(
        json.dumps({"source_sha256": source_hash()})
    )
    credits = {"data": {"total_credits": 0, "total_usage": 0.2}}
    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "judge-placeholder"}),
        patch(
            "urllib.request.urlopen",
            return_value=Response(json.dumps(credits).encode()),
        ) as request,
    ):
        report = signoff(tmp_path)
    assert (
        report["status"] == "blocked_credit"
        and report["new_generations"] == 0
        and not report["promoted"]
    )
    assert request.call_count == 1 and request.call_args.args[0].full_url.endswith(
        "/credits"
    )


def test_transformation_oracles_use_changed_values_and_preserve_invariants(
    tmp_path: Path,
) -> None:
    from benchmarks.metamorphic import generate
    from evaluate import read_answers

    queries, refs = generate(tmp_path / "mutations")
    questions = json.loads(queries.read_text())
    gold = read_answers(refs)
    assert len(questions) == 6 and len({q["id"] for q in questions}) == 6
    assert [gold[q["id"]] for q in questions] == ["37"] * 5 + ["48"]


def test_iterator_candidate_is_opt_in_and_lazy() -> None:
    from src.executor import execute_program

    code = "result=next(10/x for x in [2,0])"
    disabled = execute_program(code)
    enabled = execute_program(code, iterator_helpers=True)
    assert not disabled.success and "Unknown name: next" in disabled.error
    assert enabled.success and enabled.result == 5
    empty = execute_program("result=next((x for x in []),9)", iterator_helpers=True)
    assert empty.success and empty.result == 9
    exhausted = execute_program("result=next(x for x in [])", iterator_helpers=True)
    assert not exhausted.success and "StopIteration" in exhausted.error


def test_iterator_candidate_preserves_local_scope_and_blocks_introspection() -> None:
    from src.executor import execute_program

    scoped = execute_program(
        "x=9\nresult=[next(x+y for x in [1,2]) for y in [3,4]]+[x]",
        iterator_helpers=True,
    )
    assert scoped.success and scoped.result == [4, 5, 9]
    blocked = execute_program("result=iter([1]).__class__", iterator_helpers=True)
    assert not blocked.success and "Private" in blocked.error
