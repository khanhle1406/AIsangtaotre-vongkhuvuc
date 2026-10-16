"""CLI with bounded concurrency, per-answer checkpoints and resource telemetry."""

import argparse
import csv
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Self
from zipfile import BadZipFile

import psutil

from src.excel_parser import WorkbookData, load_workbook_data
from src.llm_agent import DEFAULT_MODEL, BudgetLedger, LLMAgent, SolveResult


def validate_queries(path: Path, input_dir: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as stream:
        queries = json.load(stream)
    if not isinstance(queries, list):
        raise TypeError("queries.json must be a list")
    ids = set()
    for item in queries:
        if (
            not isinstance(item, dict)
            or not {"id", "file_name", "query"} <= item.keys()
        ):
            raise ValueError("Every query needs id, file_name, query")
        if (
            isinstance(item["id"], bool)
            or not isinstance(item["id"], (str, int))
            or str(item["id"]) == ""
        ):
            raise ValueError("ID must be a nonempty string or integer")
        key = str(item["id"])
        if key in ids:
            raise ValueError(f"Duplicate ID: {key}")
        ids.add(key)
        if not isinstance(item["query"], str) or not item["query"].strip():
            raise ValueError("Query must be nonempty text")
        if not isinstance(item["file_name"], str):
            raise TypeError("file_name must be text")
        candidate = (input_dir / item["file_name"]).resolve()
        if (
            not candidate.is_relative_to(input_dir.resolve())
            or candidate.suffix.lower() != ".xlsx"
        ):
            raise ValueError("Workbook path must be an .xlsx inside input-dir")
    return queries


def write_submission(
    path: Path, queries: list[dict[str, Any]], results: dict[str, str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "answer"])
        writer.writeheader()
        writer.writerows(
            {"id": query["id"], "answer": results.get(str(query["id"]), "")}
            for query in queries
        )
    os.replace(temp, path)


def validate_artifact_paths(
    input_dir: Path,
    queries_path: Path,
    queries: list[dict[str, Any]],
    output: Path,
    trace_path: Path | None,
    save_diagnostics: bool,
) -> None:
    """Reject input writes and aliasing before creating directories/checkpoints."""
    artifacts = [output, output.with_name(output.name + ".tmp")]
    if save_diagnostics:
        artifacts.extend(
            [
                trace_path or output.with_suffix(".trace.jsonl"),
                output.with_suffix(".metrics.json"),
            ]
        )
    resolved = [path.resolve() for path in artifacts]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Output, temporary, trace and metrics paths must differ")
    protected = [queries_path, *(input_dir / item["file_name"] for item in queries)]
    for path in artifacts:
        target = path.resolve()
        if (
            target.is_relative_to(input_dir.resolve())
            or target.is_relative_to(Path("/input").resolve())
            or any(
                target == source.resolve()
                or path.exists()
                and source.exists()
                and path.samefile(source)
                for source in protected
            )
        ):
            raise ValueError("Output artifacts must not modify input data")


class ResourceMonitor:
    def __init__(self, limit_mb: int = 800) -> None:
        self.limit = limit_mb * 1024**2
        self.peak = 0
        self.exceeded = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        parent = psutil.Process()
        while not self.stop.wait(0.02):
            rss = 0
            try:
                children = parent.children(recursive=True)
                for process in [parent, *children]:
                    try:
                        rss += process.memory_info().rss
                    except psutil.NoSuchProcess:
                        continue
                self.peak = max(self.peak, rss)
                if rss > self.limit:
                    self.exceeded.set()
                    # Children are only our isolated AST workers. Cancel them before the 1 GB ceiling.
                    for process in children:
                        try:
                            process.kill()
                        except psutil.NoSuchProcess:
                            continue
            except psutil.NoSuchProcess:
                return

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop.set()
        self.thread.join()


def run_queries(
    input_dir: Path,
    queries: list[dict[str, Any]],
    output: Path,
    agent: LLMAgent,
    concurrency: int = 2,
    trace_path: Path | None = None,
    save_diagnostics: bool = True,
) -> dict[str, Any]:
    start = agent.started_at
    trace_path = trace_path or output.with_suffix(".trace.jsonl")
    if save_diagnostics:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
    if save_diagnostics and (
        len(
            {
                output.resolve(),
                trace_path.resolve(),
                output.with_suffix(".metrics.json").resolve(),
            }
        )
        != 3
    ):
        raise ValueError("Output, trace and metrics paths must differ")
    cache: OrderedDict[str, WorkbookData] = OrderedDict()
    cache_bytes = 0
    results: dict[str, str] = {}
    failures: dict[str, str] = {}
    pending: dict[Future[SolveResult], dict[str, Any]] = {}
    cursor = 0
    write_submission(output, queries, results)
    with (
        ResourceMonitor() as monitor,
        (
            trace_path.open("w", encoding="utf-8")
            if save_diagnostics
            else nullcontext(sys.stderr)
        ) as trace,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        while cursor < len(queries) or pending:
            while cursor < len(queries) and len(pending) < concurrency:
                item = queries[cursor]
                cursor += 1
                key = str(item["id"])
                if monitor.exceeded.is_set() or time.monotonic() >= agent.deadline:
                    failures[key] = "Run resource/deadline limit reached"
                    trace.write(
                        json.dumps({"id": item["id"], "error": failures[key]}) + "\n"
                    )
                    continue
                if agent.fatal_error:
                    failures[key] = agent.fatal_error
                    trace.write(
                        json.dumps({"id": item["id"], "error": failures[key]}) + "\n"
                    )
                    trace.flush()
                    continue
                name = item["file_name"]
                try:
                    if name in cache:
                        workbook = cache.pop(name)
                        cache[name] = workbook
                    else:
                        workbook = load_workbook_data(
                            input_dir / name, max_bytes=64 * 1024**2
                        )
                        while (
                            cache
                            and cache_bytes + workbook.estimated_bytes > 128 * 1024**2
                        ):
                            _, old = cache.popitem(last=False)
                            cache_bytes -= old.estimated_bytes
                        cache[name] = workbook
                        cache_bytes += workbook.estimated_bytes
                    # Large workbook payloads use one live question at a time.
                    if pending and workbook.estimated_bytes > 32 * 1024**2:
                        cursor -= 1
                        break
                    pending[
                        pool.submit(agent.solve_workbook, workbook, item["query"])
                    ] = item
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    MemoryError,
                    BadZipFile,
                ) as error:
                    failures[key] = f"{type(error).__name__}: {error}"
                    trace.write(
                        json.dumps({"id": item["id"], "error": failures[key]}) + "\n"
                    )
                    trace.flush()
            if not pending:
                continue
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                item = pending.pop(future)
                key = str(item["id"])
                result = future.result()
                results[key] = result.answer
                if result.error:
                    failures[key] = result.error
                trace.write(
                    json.dumps(
                        {
                            "id": item["id"],
                            "file_name": item["file_name"],
                            **result.trace(),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n"
                )
                trace.flush()
                write_submission(output, queries, results)
                print(
                    f"{key}: {result.answer!r}, {result.elapsed:.2f}s, ${result.cost:.6f}"
                    + (f" ERROR: {result.error}" if result.error else ""),
                    flush=True,
                )
    metrics = {
        "queries": len(queries),
        "answered": sum(bool(value) for value in results.values()),
        "elapsed_seconds": time.monotonic() - start,
        "cost_usd": agent.total_cost,
        "tokens": agent.total_tokens_used,
        "peak_total_rss_bytes": monitor.peak,
        "model": agent.model,
        "reasoning_tokens": agent.reasoning_tokens,
        "max_tokens": agent.max_tokens,
        "concurrency": concurrency,
        "compact_prompt": agent.compact_prompt,
        "adaptive_reasoning": agent.adaptive_reasoning,
        "worker_memory_mb": agent.worker_memory_mb,
        "failures": failures,
    }
    if save_diagnostics:
        output.with_suffix(".metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    write_submission(output, queries, results)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Workbook-grounded Excel QA")
    parser.add_argument(
        "--xlsx-dir",
        "--input-dir",
        dest="input_dir",
        type=Path,
        default=Path("data/xlsx_files"),
    )
    parser.add_argument("--queries", type=Path, default=Path("data/queries.json"))
    parser.add_argument("--output", type=Path, default=Path("submission.csv"))
    parser.add_argument("--openrouter-key", "--api-key", dest="api_key", default=None)
    parser.add_argument(
        "--openrouter-model", "--model", dest="model", default=DEFAULT_MODEL
    )
    parser.add_argument("--openrouter-base-url", default=None)
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4], default=2)
    parser.add_argument(
        "--compact-prompt",
        action="store_true",
        help="Lossless shorter cell notation; experimental until live validation",
    )
    parser.add_argument(
        "--adaptive-reasoning",
        action="store_true",
        help="Increase reasoning/output on repair or verification, within the same budget",
    )
    parser.add_argument("--deadline-seconds", type=float, default=2300)
    parser.add_argument("--total-budget", type=float, default=1.8)
    parser.add_argument("--query-budget", type=float, default=0.09)
    parser.add_argument("--reasoning-tokens", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--trace", type=Path, default=None)
    parser.add_argument(
        "--save-diagnostics",
        action="store_true",
        help="Also save trace/metrics beside CSV; default logs use stdout/stderr only",
    )
    args = parser.parse_args()
    if (
        not args.input_dir.is_dir()
        or not 0 < args.deadline_seconds <= 2300
        or args.total_budget <= 0
    ):
        parser.error("Invalid input directory, deadline or total budget")
    try:
        queries = validate_queries(args.queries, args.input_dir)
        save_diagnostics = args.save_diagnostics or args.trace is not None
        validate_artifact_paths(
            args.input_dir,
            args.queries,
            queries,
            args.output,
            args.trace,
            save_diagnostics,
        )
        write_submission(args.output, queries, {})
        deadline = time.monotonic() + args.deadline_seconds
        agent = LLMAgent(
            args.api_key,
            args.model,
            BudgetLedger(args.total_budget),
            args.query_budget,
            args.reasoning_tokens,
            args.max_tokens,
            deadline,
            compact_prompt=args.compact_prompt,
            adaptive_reasoning=args.adaptive_reasoning,
            worker_memory_mb=128 if args.concurrency == 4 else 256,
            base_url=args.openrouter_base_url,
        )
        metrics = run_queries(
            args.input_dir,
            queries,
            args.output,
            agent,
            args.concurrency,
            args.trace,
            save_diagnostics=save_diagnostics,
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"Error: {error}\n")
    if metrics["failures"] or metrics["answered"] != len(queries):
        parser.exit(
            1, "Submission saved; some questions failed. Inspect diagnostic logs.\n"
        )


if __name__ == "__main__":
    main()
