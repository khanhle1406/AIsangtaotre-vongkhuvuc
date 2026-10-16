"""Share a live workbook planning request; independently execute and verify each answer."""

import hashlib
import json
import re
import statistics
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, ClassVar

from evaluate import read_answers
from run import ResourceMonitor, validate_queries, write_submission
from src.context import project_workbook
from src.excel_parser import WorkbookData, load_workbook_data
from src.llm_agent import BudgetLedger, LLMAgent, Program, QueryState, SolveResult
from src.verification import age_reference_columns, latest_reference_columns

from .budget import workspace_budget
from .compare import score
from .efficient import dense_text
from .gateway import BatchLimits, atomic_json, gateway_settings
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
Omit optional selection: actual reads are traced and checked by the application.
cell/num/label require a CELL ADDRESS, not a column. age_order/data_rows/find_rows
require COLUMN LETTERS, not ranges: age_order(sheet,'E','F'), not 'E3:E30'.
Typed dates require data_rows kind 'datetime', not 'string'.
Use original coordinates. Return the programs JSON now.
"""


def parse_plans(text: str, count: int, questions: list[str] | None = None) -> list[str]:
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
        if "query" in item:
            echoed = item.pop("query")
            if questions is None or echoed != questions[index]:
                raise ValueError("Echoed question disagrees with its assigned index")
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


class BatchPlanningMixin:
    """Reuse only newly generated plans; repairs retain all existing per-question guards."""

    maximum_group_size: ClassVar[int] = 4
    planning_max_tokens: ClassVar[int | None] = None
    planning_strategy: ClassVar[str] = "live-workbook-plan"

    def __init__(
        self,
        *,
        column_catalog: bool = True,
        deduplicate_headers: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.column_catalog = column_catalog
        self.deduplicate_headers = deduplicate_headers
        self.prepared = threading.local()

    @staticmethod
    def planning_chunks(
        queries: list[dict[str, Any]], size: int
    ) -> list[list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in queries:
            groups[item["file_name"]].append(item)
        return [
            items[i : i + size]
            for items in groups.values()
            for i in range(0, len(items), size)
        ]

    @staticmethod
    def load_group(files: Path, questions: list[dict[str, Any]]) -> WorkbookData:
        return load_workbook_data(files / questions[0]["file_name"])

    def question_workbook(
        self, workbook: WorkbookData, question: dict[str, Any]
    ) -> WorkbookData:
        return workbook

    def planning_question(
        self, workbook: WorkbookData, index: int, question: dict[str, Any]
    ) -> dict[str, Any]:
        return {"index": index, "query": question["query"]}

    def solve_workbook(
        self, workbook: WorkbookData, query: str, max_retries: int = 2
    ) -> SolveResult:
        """Use the same lossless encoding for individual repairs as shared planning."""
        wire = workbook.wire()
        text = dense_text(
            workbook,
            wire,
            column_catalog=self.column_catalog,
            deduplicate_headers=self.deduplicate_headers,
        )
        if len(text.encode()) > 800_000:
            text = project_workbook(wire, query)
        return self._solve(text, wire, query, max_retries)

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
        independent = [
            item
            for item in questions
            if re.search(r"\bacross all\b", item["query"], re.IGNORECASE)
            and re.search(
                r"\b(?:more|less|difference|change|ratio)\b",
                item["query"],
                re.IGNORECASE,
            )
        ]
        if len(questions) > 1 and independent:
            remaining = [item for item in questions if item not in independent]
            records, event = (
                self.solve_group(workbook, remaining)
                if remaining
                else ([], {"calls": [], "question_ids": []})
            )
            for item in independent:
                result = self.solve_workbook(
                    self.question_workbook(workbook, item), item["query"]
                )
                records.append(
                    {
                        "id": str(item["id"]),
                        "file_name": item["file_name"],
                        **result.trace(),
                    }
                )
            order = {str(item["id"]): index for index, item in enumerate(questions)}
            records.sort(key=lambda record: order[record["id"]])
            event["mode"] = "shared-plan-with-independent-multi-axis-comparisons"
            event["independent_question_ids"] = [
                str(item["id"]) for item in independent
            ]
            return records, event
        state = QueryState(self.deadline, self.query_budget)
        state.max_tokens = self.planning_max_tokens
        wire = workbook.wire()
        text = dense_text(
            workbook,
            wire,
            column_catalog=self.column_catalog,
            deduplicate_headers=self.deduplicate_headers,
        )
        date_hints = []
        for index, question in enumerate(questions):
            owned_book = self.question_workbook(workbook, question)
            hint_wire = wire if owned_book is workbook else owned_book.wire()
            for name, sheet in hint_wire.items():
                latest = latest_reference_columns(sheet, question["query"])
                if latest is not None:
                    key_col, time_col = latest
                    date_hints.append(
                        f"Question {index}: latest_rows({name!r},{key_col!r},{time_col!r}) selects maximum timestamp rows per entity using verified headers. Follow the question's filter-before/after order; typed timestamps require no parsing or pandas."
                    )
                reference = age_reference_columns(sheet, question["query"])
                if reference is not None:
                    birth, event = reference
                    date_hints.append(
                        f"Question {index}: age means EACH person's elapsed date difference. "
                        f"age_order({name!r},{birth!r},{event!r},descending=False) sorts YOUNGEST first; "
                        "descending=True sorts OLDEST first. Do not reverse those meanings."
                    )
        if date_hints:
            text += "\nQUESTION DATE INTERPRETATION:\n" + "\n".join(date_hints)
        # Large books retain the solver's expandable per-question context path.
        if len(text.encode()) > 800_000:
            records = []
            for item in questions:
                result = self.solve_workbook(
                    self.question_workbook(workbook, item), item["query"]
                )
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
                        self.planning_question(workbook, i, q)
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
        response = ""
        try:
            response = LLMAgent._request(self, messages, state)
            programs = parse_plans(
                response, len(questions), [q["query"] for q in questions]
            )
        except (ValueError, TypeError, TimeoutError, KeyError) as exc:
            # Preserve the actual failed call, then spend a normal repair turn per question.
            error = f"{type(exc).__name__}: {exc}"
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
            result = self.solve_workbook(
                self.question_workbook(workbook, item), item["query"]
            )
            result.elapsed += plan_seconds
            records.append(
                {
                    "id": str(item["id"]),
                    "file_name": item["file_name"],
                    **result.trace(),
                }
            )
        return records, event


class BatchedAgent(BatchPlanningMixin, PrecisionAgent):
    """Gemini transport for the provider-independent shared planning pipeline."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("adaptive_thinking", True)
        super().__init__(**kwargs)


def run_batched_stage(
    root: Path,
    files: Path,
    queries: list[dict[str, Any]],
    references: Path,
    limits: BatchLimits,
    ledger: BudgetLedger,
    concurrency: int = 4,
    group_size: int = 4,
    agent_class: type[BatchedAgent] = BatchedAgent,
    thinking: str = "low",
    review_candidate: bool = False,
    deduplicate_headers: bool = False,
    boundary_contract: bool = False,
) -> dict[str, Any]:
    """Checkpoint whole planned groups and evaluate only after generation finishes."""
    if (
        concurrency not in {1, 2, 4, 8}
        or not 1 <= group_size <= agent_class.maximum_group_size
    ):
        raise ValueError("Invalid planning concurrency or group size")
    if thinking not in {"minimal", "low", "medium", "high"}:
        raise ValueError("Unsupported development thinking effort")
    settings = gateway_settings()
    config = {
        "model": settings["gateway_model"],
        "base_url": settings["gateway_url"],
        "helper_contract": False,
        "thinking": thinking,
        "verification_thinking": getattr(agent_class, "verification_thinking", None),
        "adaptive_thinking": f"high only after two prior HTTP attempts; otherwise {thinking}",
        "max_tokens": 2048,
        "planning_max_tokens": agent_class.planning_max_tokens or 2048,
        "concurrency": concurrency,
        "group_size": group_size,
        "strategy": agent_class.planning_strategy,
        "verification_mode": "candidate-audit"
        if review_candidate
        else "fresh-selection",
        "review_candidate": review_candidate,
        "deduplicate_headers": deduplicate_headers,
        "boundary_contract": boundary_contract,
        "modules": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("batched.py", "efficient.py", "precision.py", "gateway.py")
        },
    }
    if agent_class is not BatchedAgent:
        import inspect

        implementation = Path(inspect.getfile(agent_class))
        config["agent_class"] = agent_class.__name__
        config["agent_sha256"] = hashlib.sha256(implementation.read_bytes()).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    saved = checkpoint(root / "checkpoint.json", fingerprint(files, queries, config))
    saved.setdefault("events", [])
    remaining = [q for q in queries if str(q["id"]) not in saved["records"]]
    chunks = agent_class.planning_chunks(remaining, group_size)
    agent = agent_class(
        **settings,
        batch_limits=limits,
        thinking=thinking,
        review_candidate=review_candidate,
        deduplicate_headers=deduplicate_headers,
        **({"boundary_contract": True} if boundary_contract else {}),
        max_tokens=2048,
        ledger=ledger,
        worker_memory_mb=128 if concurrency >= 4 else 256,
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
                workbook = agent_class.load_group(files, items)
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
