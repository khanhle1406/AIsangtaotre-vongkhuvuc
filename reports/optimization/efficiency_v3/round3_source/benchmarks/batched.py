"""Share a live workbook planning request; independently execute and verify each answer."""

import hashlib
import json
import statistics
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import ResourceMonitor, validate_queries, write_submission
from src.excel_parser import WorkbookData, load_workbook_data
from src.llm_agent import BudgetLedger, Program, QueryState

from .budget import workspace_budget
from .compare import score
from .efficient import dense_text
from .gateway import BatchLimits, GatewayAgent, atomic_json, gateway_settings
from .gateway_runner import checkpoint, fingerprint
from .precision import ACCURACY_CONTRACT, PrecisionAgent

PLAN_CONTRACT = """Answer ALL numbered QUESTIONS independently from this workbook.
Return ONE JSON object {"programs":[{"index":0,"code":"Python assigning result",
"result_variable":"result","format":{"kind":"integer"},"assumptions":[],"needs_verification":false}, ...]}.
Include exactly one program for EACH question index, preserving its requested label,
scope, output kind and order. Each code must read real workbook cells; do not copy numeric
measures. Programs are executed independently and CANNOT use variables/results from others.
Do NOT return standalone Python or a single answer. For requested lists result must be a
list, not a joined string. For options supplied by a question, preserve those option names.
Omit selection unless complete; use original coordinates. Return the programs JSON now.
"""


def parse_plans(text: str, count: int) -> list[str]:
    """Validate the envelope before associating any program with a question."""
    if text.strip().startswith("```"):
        text = text.strip().split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(text)
    if not isinstance(data, dict) or set(data) != {"programs"}:
        raise ValueError("Expected only the programs envelope")
    programs = data["programs"]
    if not isinstance(programs, list) or len(programs) != count:
        raise ValueError("Missing or extra question programs")
    indexed: dict[int, str] = {}
    for entry in programs:
        if not isinstance(entry, dict):
            raise TypeError("Program entry must be an object")
        item = dict(entry)
        index = item.pop("index", None)
        if type(index) is not int or not 0 <= index < count or index in indexed:
            raise ValueError("Invalid, duplicate or unknown question index")
        indexed[index] = Program.model_validate(item).model_dump_json()
    return [indexed[index] for index in range(count)]


def apportioned_calls(
    calls: list[dict[str, Any]], index: int, count: int
) -> list[dict[str, Any]]:
    """Allocate integer tokens exactly, retaining original event IDs for deduplication."""
    shared = []
    for original in calls:
        call = dict(original)
        for key in (
            "tokens",
            "provider_total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "reserved_token_bound",
        ):
            value = call.get(key)
            if type(value) is int:
                call[key] = value // count + int(index < value % count)
        for key in ("cost_usd", "reserved_usd", "provider_cost_usd"):
            if call.get(key) is not None:
                call[key] /= count
        call["shared_questions"] = count
        call["allocation_index"] = index
        shared.append(call)
    return shared


class BatchedAgent(PrecisionAgent):
    """Reuse only newly generated plans; repairs retain all existing per-question guards."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.prepared = threading.local()

    def _request(self, messages: list[dict[str, str]], state: QueryState) -> str:
        packet = getattr(self.prepared, "packet", None)
        if packet is None:
            return super()._request(messages, state)
        self.prepared.packet = None
        response, calls = packet
        state.calls.extend(calls)
        state.requests += len(calls)
        state.tokens += sum(c["tokens"] for c in calls)
        state.cost += sum(c["cost_usd"] for c in calls)
        return response

    def solve_group(
        self, workbook: WorkbookData, questions: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        start = time.monotonic()
        state = QueryState(self.deadline, self.query_budget)
        wire = workbook.wire()
        text = dense_text(workbook, wire)
        # Large books retain the solver's expandable per-question context path.
        if len(text.encode()) > 800_000:
            records = []
            for item in questions:
                result = self.solve_workbook(workbook, item["query"])
                records.append(
                    {
                        "id": str(item["id"]),
                        "file_name": item["file_name"],
                        **result.trace(),
                    }
                )
            return records, {"mode": "individual-large-workbook", "calls": []}
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": "WORKBOOK DATA:\n"
                + text
                + "\nQUESTIONS:\n"
                + json.dumps(
                    [
                        {"index": i, "query": q["query"]}
                        for i, q in enumerate(questions)
                    ],
                    ensure_ascii=False,
                )
                + "\n"
                + ACCURACY_CONTRACT
                + "\n"
                + PLAN_CONTRACT,
            },
        ]
        error = None
        try:
            response = GatewayAgent._request(self, messages, state)
            programs = parse_plans(response, len(questions))
        except (ValueError, TypeError, TimeoutError, KeyError) as exc:
            # Preserve the actual failed call, then spend a normal repair turn per question.
            error = f"{type(exc).__name__}: {exc}"
            response = ""
            programs = [json.dumps({"planning_error": error})] * len(questions)
        plan_seconds = time.monotonic() - start
        event = {
            "mode": "live-shared-workbook-plan",
            "calls": state.calls,
            "elapsed": plan_seconds,
            "error": error,
            "model_output": response,
            "question_ids": [str(q["id"]) for q in questions],
        }
        for call in state.calls:
            call["shared_http_id"] = uuid.uuid4().hex
        records = []
        for index, (item, program) in enumerate(zip(questions, programs, strict=True)):
            self.prepared.packet = (
                program,
                apportioned_calls(state.calls, index, len(questions)),
            )
            result = self.solve_workbook(workbook, item["query"])
            result.elapsed += plan_seconds
            records.append(
                {
                    "id": str(item["id"]),
                    "file_name": item["file_name"],
                    **result.trace(),
                }
            )
        return records, event


def run_batched_stage(
    root: Path,
    files: Path,
    queries: list[dict[str, Any]],
    references: Path,
    limits: BatchLimits,
    ledger: BudgetLedger,
    concurrency: int = 4,
    group_size: int = 4,
) -> dict[str, Any]:
    """Checkpoint whole planned groups and evaluate only after generation finishes."""
    if concurrency not in {1, 2, 4} or not 1 <= group_size <= 4:
        raise ValueError("Invalid planning concurrency or group size")
    settings = gateway_settings()
    config = {
        "model": settings["gateway_model"],
        "base_url": settings["gateway_url"],
        "helper_contract": False,
        "thinking": "low",
        "max_tokens": 2048,
        "concurrency": concurrency,
        "group_size": group_size,
        "strategy": "live-workbook-plan",
        "modules": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("batched.py", "efficient.py", "precision.py")
        },
    }
    root.mkdir(parents=True, exist_ok=True)
    saved = checkpoint(root / "checkpoint.json", fingerprint(files, queries, config))
    saved.setdefault("events", [])
    remaining = [q for q in queries if str(q["id"]) not in saved["records"]]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in remaining:
        groups[item["file_name"]].append(item)
    chunks = [
        items[i : i + group_size]
        for items in groups.values()
        for i in range(0, len(items), group_size)
    ]
    agent = BatchedAgent(
        **settings,
        batch_limits=limits,
        thinking="low",
        max_tokens=2048,
        ledger=ledger,
        worker_memory_mb=128 if concurrency == 4 else 256,
        deadline=time.monotonic() + limits.update()["deadline_unix"] - time.time(),
    )
    start = time.monotonic()
    with (
        ResourceMonitor() as monitor,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        pending: dict[Any, list[dict[str, Any]]] = {}
        cursor = 0
        while cursor < len(chunks) or pending:
            while cursor < len(chunks) and len(pending) < concurrency:
                allowance = limits.update()
                if (
                    agent.fatal_error
                    or monitor.exceeded.is_set()
                    or time.time() >= allowance["deadline_unix"]
                    or allowance["fatal_error"]
                    or allowance["attempts"] >= allowance["attempt_limit"]
                ):
                    break
                items = chunks[cursor]
                cursor += 1
                workbook = load_workbook_data(files / items[0]["file_name"])
                pending[pool.submit(agent.solve_group, workbook, items)] = items
            if not pending:
                break
            future = next(as_completed(pending))
            items = pending.pop(future)
            records, event = future.result()
            saved["events"].append(event)
            for record in records:
                key = record.pop("id")
                saved["records"][key] = record
                print(
                    f"{root.name} {key}: {record['answer']!r} ({record['elapsed']:.2f}s)",
                    flush=True,
                )
            saved["wall_seconds"] = (
                saved.get("wall_seconds", 0) + time.monotonic() - start
            )
            start = time.monotonic()
            atomic_json(root / "checkpoint.json", saved)
            write_submission(
                root / "submission.csv",
                queries,
                {k: r["answer"] for k, r in saved["records"].items()},
            )
    saved["peak_total_rss_bytes"] = max(
        saved.get("peak_total_rss_bytes") or 0, monitor.peak
    )
    records = saved["records"]
    saved["complete"] = len(records) == len(queries) and all(
        not r.get("error") for r in records.values()
    )
    atomic_json(root / "checkpoint.json", saved)
    output = root / "submission.csv"
    write_submission(output, queries, {k: r["answer"] for k, r in records.items()})
    all_calls = [c for r in records.values() for c in r["calls"]]
    shared_events = {c["shared_http_id"] for c in all_calls if c.get("shared_http_id")}
    unknown_events = {
        c.get("shared_http_id", f"single-{i}")
        for i, c in enumerate(all_calls)
        if c.get("provider_total_tokens") is None
    }
    report = {
        "config": config,
        "fingerprint": saved["fingerprint"],
        "complete": saved["complete"],
        "score": score(
            output, read_answers(references), {str(q["id"]) for q in queries}
        ),
        "wall_seconds": saved.get("wall_seconds", 0),
        "mean_query_seconds": statistics.mean(r["elapsed"] for r in records.values())
        if records
        else None,
        "tokens": sum(r["tokens"] for r in records.values()),
        "provider_tokens_known": sum(
            c.get("provider_total_tokens") or 0 for c in all_calls
        ),
        "usage_missing_attempts": len(unknown_events),
        "tokens_conservative_upper": sum(
            c.get("provider_total_tokens")
            if c.get("provider_total_tokens") is not None
            else c.get("reserved_token_bound", c["tokens"])
            for c in all_calls
        ),
        "http_attempts": len(shared_events)
        + sum(not c.get("shared_http_id") for c in all_calls),
        "peak_total_rss_bytes": saved["peak_total_rss_bytes"],
        "fatal_error": agent.fatal_error,
        "errors": {key: r["error"] for key, r in records.items() if r.get("error")},
        "provenance": "new live model plans; shared call tokens allocated exactly once, each program independently executed/verified; no prior trace replay",
        "cost_basis": "user-confirmed free gateway; provider cost in calls; missing usage stays unknown",
    }
    atomic_json(root / "report.json", report)
    return report


if __name__ == "__main__":
    out = Path("reports/optimization/efficiency_v3/round3_public_c4")
    with workspace_budget().stage(str(out.resolve()), 0.001) as budget:
        result = run_batched_stage(
            out,
            Path("data/xlsx_files"),
            validate_queries(Path("data/queries.json"), Path("data/xlsx_files")),
            Path("data/sample_submission.csv"),
            BatchLimits(out.parent / "round3_batch.json"),
            budget,
        )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "score",
                        "wall_seconds",
                        "tokens",
                        "http_attempts",
                        "usage_missing_attempts",
                    )
                },
                ensure_ascii=False,
            )
        )
