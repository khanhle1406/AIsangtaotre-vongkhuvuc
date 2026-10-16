"""Concurrent repairs preserve ownership, request accounting and one global limit."""

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from benchmarks.gateway import BatchLimits
from benchmarks.packed import ParallelPackedAgent, ScheduledPackedAgent, namespace_books
from src.excel_parser import CellData, SheetData, WorkbookData
from src.executor import execute_program


def settings(tmp_path: Path) -> dict[str, Any]:
    return {
        "api_key": "test-placeholder",
        "gateway_url": "https://gateway.invalid/v1",
        "gateway_model": "ag/gemini-3-flash",
        "batch_limits": BatchLimits(tmp_path / "batch.json"),
    }


def test_planning_messages_and_chunks_are_identical_to_serial_control(
    tmp_path: Path,
) -> None:
    kwargs = settings(tmp_path)
    control = ParallelPackedAgent(**kwargs)
    candidate = ScheduledPackedAgent(**kwargs, repair_concurrency=2)
    source = WorkbookData(
        {"Same": SheetData("Same", cells={"B2": CellData(23, "number")})}
    )
    book = namespace_books({"arbitrary.xlsx": source})
    questions = [
        {"id": f"new-{i}", "file_name": "arbitrary.xlsx", "query": "Read the measure."}
        for i in range(10)
    ]
    assert candidate.planning_chunks(questions, 8) == control.planning_chunks(
        questions, 8
    )
    assert candidate.planning_messages(
        book, questions[:8], "unchanged actual data"
    ) == control.planning_messages(book, questions[:8], "unchanged actual data")
    assert candidate.system_prompt == control.system_prompt
    assert candidate.planning_max_tokens == control.planning_max_tokens == 4096
    for invalid in [0, 3, 8, True]:
        with pytest.raises(ValueError, match="Repair concurrency"):
            ScheduledPackedAgent(**kwargs, repair_concurrency=invalid)


def test_global_slots_cover_both_planners_workers_and_repair_requests(
    tmp_path: Path,
) -> None:
    agent = ScheduledPackedAgent(**settings(tmp_path), repair_concurrency=4)
    book = namespace_books(
        {
            name: WorkbookData(
                {"Same": SheetData("Same", cells={"B2": CellData(value, "number")})}
            )
            for name, value in [("left.xlsx", 7), ("right.xlsx", 13)]
        }
    )
    questions = [
        {
            "id": f"renamed-{i}",
            "file_name": "left.xlsx" if i % 2 == 0 else "right.xlsx",
            "query": "Read the measure.",
        }
        for i in range(8)
    ]
    active = peak = attempts = 0
    lock = threading.Lock()
    repairs = threading.Barrier(4, timeout=10)

    def enter() -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            assert active <= 4

    def leave() -> None:
        nonlocal active
        with lock:
            active -= 1

    def worker(*args: Any, **kwargs: Any) -> Any:
        enter()
        try:
            return execute_program(*args, **kwargs)
        finally:
            leave()

    def response(request: Any, timeout: float) -> Any:
        nonlocal attempts
        payload = json.loads(request.data)
        enter()
        try:
            with lock:
                attempts += 1
            schema = payload["response_format"].get("json_schema", {}).get("schema", {})
            if "programs" in schema.get("properties", {}):
                keys = schema["properties"]["programs"]["properties"]
                content = {
                    "programs": {
                        key: {"code": "result=undefined", "format": {"kind": "integer"}}
                        for key in keys
                    }
                }
            else:
                repairs.wait()
                data = payload["messages"][1]["content"]
                allowed = [
                    name
                    for name in ["W0::Same", "W1::Same"]
                    if f'SHEET "{name}"' in data
                ]
                assert len(allowed) == 1
                content = {
                    "code": f"result=num({allowed[0]!r},'B2')",
                    "format": {"kind": "integer"},
                }
            stream = io.BytesIO(
                json.dumps(
                    {
                        "model": "ag/gemini-3-flash",
                        "choices": [
                            {
                                "message": {"content": json.dumps(content)},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"total_tokens": 101},
                    }
                ).encode()
            )
            stream.headers = {"Content-Type": "application/json"}
            return stream
        finally:
            leave()

    with (
        patch("benchmarks.gateway.GatewayAgent._open_request", side_effect=response),
        patch("src.llm_agent.execute_program", side_effect=worker),
        ThreadPoolExecutor(max_workers=2) as groups,
    ):
        results = [
            future.result()
            for future in [
                groups.submit(agent.solve_group, book, questions[:4]),
                groups.submit(agent.solve_group, book, questions[4:]),
            ]
        ]
    records = [row for rows, _ in results for row in rows]
    assert [row["id"] for row in records] == [q["id"] for q in questions]
    assert [row["answer"] for row in records] == ["7", "13"] * 4
    assert all(row["requests"] == 2 and row["error"] is None for row in records)
    assert attempts == 10 and peak == 4 and active == 0
    assert sum(row["tokens"] for row in records) == agent.total_tokens_used == 1010
    assert sum(row["cost"] for row in records) == 0
    shared = {
        call["shared_http_id"]
        for row in records
        for call in row["calls"]
        if call.get("shared_http_id")
    }
    assert len(shared) == 2
    assert (
        len(
            [
                call
                for row in records
                for call in row["calls"]
                if not call.get("shared_http_id")
            ]
        )
        == 8
    )
    allowance = agent.batch_limits.update()
    assert (
        allowance["attempts"] == 10
        and not allowance["reservations"]
        and allowance["token_upper"] == 1010
    )
