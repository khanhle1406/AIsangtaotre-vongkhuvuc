"""Opt-in official-model CLI; shared planning still requires live Qwen acceptance."""

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from run import ResourceMonitor, validate_queries, write_submission
from src.excel_parser import load_workbook_data
from src.llm_agent import DEFAULT_MODEL, BudgetLedger

from .gateway import atomic_json
from .qwen_batched import QwenBatchedAgent


def run_batched_queries(
    input_dir: Path,
    queries: list[dict[str, Any]],
    output: Path,
    agent: QwenBatchedAgent,
    concurrency: int = 4,
) -> dict[str, Any]:
    """Produce an ordinary CSV without gold; bound live workbooks and checkpoint answers."""
    if concurrency not in {1, 2, 4}:
        raise ValueError("Unsupported concurrency")
    trace_path = output.with_suffix(".trace.jsonl")
    metrics_path = output.with_suffix(".metrics.json")
    if len({output.resolve(), trace_path.resolve(), metrics_path.resolve()}) != 3:
        raise ValueError("Output, trace and metrics paths must differ")
    if {output.resolve(), trace_path.resolve(), metrics_path.resolve()} & {
        path.resolve() for path in input_dir.glob("*.xlsx")
    }:
        raise ValueError("Output artifacts cannot overwrite a workbook")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in queries:
        groups[item["file_name"]].append(item)
    chunks = [
        items[i : i + 4] for items in groups.values() for i in range(0, len(items), 4)
    ]
    answers: dict[str, str] = {}
    failures: dict[str, str] = {}
    write_submission(output, queries, answers)
    with (
        ResourceMonitor() as monitor,
        trace_path.open("w", encoding="utf-8") as trace,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        pending: dict[Any, list[dict[str, Any]]] = {}
        cursor = 0
        while cursor < len(chunks) or pending:
            while cursor < len(chunks) and len(pending) < concurrency:
                if (
                    agent.fatal_error
                    or monitor.exceeded.is_set()
                    or time.monotonic() >= agent.deadline
                ):
                    break
                items = chunks[cursor]
                try:
                    workbook = load_workbook_data(
                        input_dir / items[0]["file_name"], max_bytes=64 * 1024**2
                    )
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    MemoryError,
                    BadZipFile,
                ) as error:
                    cursor += 1
                    for item in items:
                        failures[str(item["id"])] = f"{type(error).__name__}: {error}"
                    trace.write(
                        json.dumps(
                            {
                                "question_ids": [str(item["id"]) for item in items],
                                "error": str(error),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    trace.flush()
                    continue
                if pending and workbook.estimated_bytes > 32 * 1024**2:
                    break
                cursor += 1
                pending[pool.submit(agent.solve_group, workbook, items)] = items
                if workbook.estimated_bytes > 32 * 1024**2:
                    break
            if not pending:
                break
            future = next(as_completed(pending))
            items = pending.pop(future)
            records, event = future.result()
            trace.write(
                json.dumps({"planning_event": event}, ensure_ascii=False) + "\n"
            )
            for record in records:
                key = record["id"]
                answers[key] = record["answer"]
                if record["error"]:
                    failures[key] = record["error"]
                trace.write(json.dumps(record, ensure_ascii=False) + "\n")
                trace.flush()
                write_submission(output, queries, answers)
        for item in queries:
            key = str(item["id"])
            if key not in answers and key not in failures:
                failures[key] = (
                    agent.fatal_error or "Run resource/deadline limit reached"
                )
    write_submission(output, queries, answers)
    metrics = {
        "model": agent.model,
        "provider": "openrouter",
        "planning_format": "keyed-json-object",
        "queries": len(queries),
        "answered": sum(bool(value) for value in answers.values()),
        "failures": failures,
        "elapsed_seconds": time.monotonic() - agent.started_at,
        "cost_usd": agent.total_cost,
        "tokens": agent.total_tokens_used,
        "peak_total_rss_bytes": monitor.peak,
        "concurrency": concurrency,
        "qwen_live_acceptance": False,
    }
    atomic_json(metrics_path, metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4], default=4)
    parser.add_argument("--deadline-seconds", type=float, default=2300)
    parser.add_argument("--total-budget", type=float, default=1.8)
    parser.add_argument("--query-budget", type=float, default=0.09)
    parser.add_argument("--reasoning-tokens", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()
    if not 0 < args.deadline_seconds <= 2300 or not 0 < args.total_budget <= 1.8:
        parser.error("Invalid competition deadline or total budget")
    queries = validate_queries(args.queries, args.input_dir)
    if args.queries.resolve() in {
        args.output.resolve(),
        args.output.with_suffix(".trace.jsonl").resolve(),
        args.output.with_suffix(".metrics.json").resolve(),
    }:
        parser.error("Output artifacts cannot overwrite queries")
    agent = QwenBatchedAgent(
        api_key=args.api_key,
        model=DEFAULT_MODEL,
        ledger=BudgetLedger(args.total_budget),
        query_budget=args.query_budget,
        reasoning_tokens=args.reasoning_tokens,
        max_tokens=args.max_tokens,
        deadline=time.monotonic() + args.deadline_seconds,
        worker_memory_mb=128 if args.concurrency == 4 else 256,
    )
    metrics = run_batched_queries(
        args.input_dir, queries, args.output, agent, args.concurrency
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if metrics["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
