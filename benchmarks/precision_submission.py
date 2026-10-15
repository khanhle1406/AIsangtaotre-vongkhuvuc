"""Experimental robust CLI; uses the required Qwen/OpenRouter, never the dev gateway."""

import argparse
import json
import time
from pathlib import Path

from run import run_queries, validate_queries, write_submission
from src.llm_agent import DEFAULT_MODEL, BudgetLedger

from .qwen_signoff import CandidateAgent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Robust workbook candidate; official Qwen verification is required before promotion"
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/xlsx_files"))
    parser.add_argument("--queries", type=Path, default=Path("data/queries.json"))
    parser.add_argument("--output", type=Path, default=Path("candidate_submission.csv"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4], default=2)
    parser.add_argument("--deadline-seconds", type=float, default=2300)
    parser.add_argument("--total-budget", type=float, default=1.8)
    parser.add_argument("--query-budget", type=float, default=0.09)
    parser.add_argument("--reasoning-tokens", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()
    if not 0 < args.deadline_seconds <= 2300 or not 0 < args.total_budget <= 1.8:
        parser.error("Invalid competition deadline or total budget")
    queries = validate_queries(args.queries, args.input_dir)
    protected = {
        args.queries.resolve(),
        *(path.resolve() for path in args.input_dir.glob("*.xlsx")),
    }
    artifacts = {
        args.output.resolve(),
        args.output.with_suffix(".trace.jsonl").resolve(),
        args.output.with_suffix(".metrics.json").resolve(),
    }
    if protected & artifacts:
        parser.error("Output artifacts must not overwrite input data")
    write_submission(args.output, queries, {})
    agent = CandidateAgent(
        api_key=args.api_key,
        model=DEFAULT_MODEL,
        precision_profile="robust",
        ledger=BudgetLedger(args.total_budget),
        query_budget=args.query_budget,
        reasoning_tokens=args.reasoning_tokens,
        max_tokens=args.max_tokens,
        deadline=time.monotonic() + args.deadline_seconds,
        worker_memory_mb=128 if args.concurrency == 4 else 256,
    )
    metrics = run_queries(args.input_dir, queries, args.output, agent, args.concurrency)
    print(
        json.dumps(
            {
                "status": "experimental candidate; not implicitly Qwen-validated",
                "model": DEFAULT_MODEL,
                "metrics": metrics,
            },
            ensure_ascii=False,
        )
    )
    if metrics["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
