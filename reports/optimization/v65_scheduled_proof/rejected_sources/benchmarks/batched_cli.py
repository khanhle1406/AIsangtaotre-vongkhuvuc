"""Run the Gemini development candidate on arbitrary inputs without reference answers."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from run import ResourceMonitor, validate_queries, write_submission

from .batched import BatchedAgent
from .budget import workspace_budget
from .gateway import BatchLimits, atomic_json, gateway_settings
from .packed import PLANNING_PROFILES, planning_agent


def solve(
    input_dir: Path,
    queries_path: Path,
    output: Path,
    concurrency: int = 4,
    seconds: float = 1800,
    structured: bool = True,
    planning_profile: str = "same-book",
) -> dict[str, Any]:
    """Use the measured planning/execution engine; never load any reference CSV."""
    if concurrency not in {1, 2, 4} or not 0 < seconds <= 1800:
        raise ValueError("Invalid development concurrency/deadline")
    if not structured and planning_profile != "same-book":
        raise ValueError("Workbook packing requires keyed planning")
    agent_class = planning_agent(planning_profile) if structured else BatchedAgent
    queries = validate_queries(queries_path, input_dir)
    trace_path = output.with_suffix(".trace.jsonl")
    metrics_path = output.with_suffix(".metrics.json")
    batch_path = output.with_suffix(".batch.json")
    protected = {
        queries_path.resolve(),
        *(p.resolve() for p in input_dir.glob("*.xlsx")),
    }
    artifacts = {p.resolve() for p in (output, trace_path, metrics_path, batch_path)}
    if len(artifacts) != 4 or protected & artifacts:
        raise ValueError("Output artifacts must differ and cannot overwrite input data")
    output.parent.mkdir(parents=True, exist_ok=True)
    chunks = agent_class.planning_chunks(queries, agent_class.maximum_group_size)
    limits = BatchLimits(batch_path, seconds=seconds)
    answers: dict[str, str] = {}
    failures: dict[str, str] = {}
    start = time.monotonic()
    write_submission(output, queries, answers)
    with workspace_budget().stage(
        str(output.resolve()) + f":{time.time_ns()}", 0.001
    ) as ledger:
        agent = agent_class(
            **gateway_settings(),
            batch_limits=limits,
            thinking="low",
            review_candidate=planning_profile != "same-book",
            **(
                {"repair_concurrency": concurrency}
                if getattr(agent_class, "concurrent_repairs", False)
                else {}
            ),
            max_tokens=2048,
            ledger=ledger,
            worker_memory_mb=128 if concurrency == 4 else 256,
            deadline=time.monotonic() + limits.update()["deadline_unix"] - time.time(),
        )
        with (
            ResourceMonitor() as monitor,
            trace_path.open("w", encoding="utf-8") as trace,
            ThreadPoolExecutor(max_workers=concurrency) as pool,
        ):
            cursor = 0
            pending: dict[Any, list[dict[str, Any]]] = {}
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
                    workbook = agent_class.load_group(input_dir, items)
                    if pending and workbook.estimated_bytes > 32 * 1024**2:
                        break
                    cursor += 1
                    pending[pool.submit(agent.solve_group, workbook, items)] = items
                    if workbook.estimated_bytes > 32 * 1024**2:
                        break
                if not pending:
                    break
                future = next(as_completed(pending))
                pending.pop(future)
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
            for question in queries:
                if str(question["id"]) not in answers:
                    failures[str(question["id"])] = (
                        agent.fatal_error
                        or "Development resource/deadline allowance reached"
                    )
        metrics = {
            "planning_format": "keyed" if structured else "indexed",
            "planning_profile": planning_profile,
            "temperature": agent.temperature,
            "planning_strategy": agent_class.planning_strategy,
            "group_size": agent_class.maximum_group_size,
            "repair_concurrency": concurrency
            if getattr(agent_class, "concurrent_repairs", False)
            else 1,
            "planning_max_tokens": agent_class.planning_max_tokens or 2048,
            "model": agent.model,
            "provider": "gateway",
            "queries": len(queries),
            "answered": sum(bool(a) for a in answers.values()),
            "failures": failures,
            "elapsed_seconds": time.monotonic() - start,
            "tokens": agent.total_tokens_used,
            "cost_usd": agent.total_cost,
            "peak_total_rss_bytes": monitor.peak,
            "batch": limits.update(),
            "qwen_confirmed": False,
        }
    write_submission(output, queries, answers)
    atomic_json(metrics_path, metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4], default=4)
    parser.add_argument("--deadline-seconds", type=float, default=1800)
    parser.add_argument(
        "--planning-format", choices=["keyed", "indexed"], default="keyed"
    )
    parser.add_argument(
        "--planning-profile", choices=list(PLANNING_PROFILES), default="same-book"
    )
    args = parser.parse_args()
    metrics = solve(
        args.input_dir,
        args.queries,
        args.output,
        args.concurrency,
        args.deadline_seconds,
        args.planning_format == "keyed",
        args.planning_profile,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if metrics["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
