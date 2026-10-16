"""Bounded fresh-generation comparison, with per-question fingerprinted checkpoints."""

import argparse
import hashlib
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import ResourceMonitor, validate_queries, write_submission
from src.excel_parser import load_workbook_data
from src.llm_agent import SYSTEM_PROMPT, BudgetLedger, QueryState

from .budget import workspace_budget
from .compare import score, source_hash
from .fixtures import generate_fixtures
from .gateway import (
    HELPER_CONTRACT,
    BatchLimits,
    GatewayAgent,
    atomic_json,
    gateway_settings,
)

# Reinforce the output envelope at the end of the short helper contract.
HELPER_CONTRACT += '\nReturn ONE JSON object, not a Python markdown block: {"code":"result=cell(\'Example\',\'C7\')","result_variable":"result","format":{"kind":"text"},"assumptions":[],"needs_verification":false}. Use your actual workbook coordinates.\n'

PROFILES = {
    "A": {"compact_prompt": False, "helper_contract": False},
    "B": {"compact_prompt": True, "helper_contract": False},
    "C": {"compact_prompt": True, "helper_contract": True},
}


class PromptedGatewayAgent(GatewayAgent):
    """Repeat the C contract next to the task to test output-envelope adherence."""

    helper_instructions = ""

    def _request(self, messages: list[dict[str, str]], state: QueryState) -> str:
        if self.helper_instructions:
            messages = [dict(message) for message in messages]
            messages[-1]["content"] += "\n" + self.helper_instructions
        return super()._request(messages, state)


def fingerprint(
    files: Path, queries: list[dict[str, Any]], config: dict[str, Any]
) -> str:
    manifest = {
        "source": source_hash(),
        "transport": hashlib.sha256(
            Path(__file__).with_name("gateway.py").read_bytes()
        ).hexdigest(),
        "queries": queries,
        "config": config,
        "prompt": SYSTEM_PROMPT,
        "helper": HELPER_CONTRACT if config["helper_contract"] else "",
        "workbooks": {
            q["file_name"]: hashlib.sha256(
                (files / q["file_name"]).read_bytes()
            ).hexdigest()
            for q in queries
        },
    }
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def checkpoint(path: Path, expected: str) -> dict[str, Any]:
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["fingerprint"] != expected:
            raise ValueError("Checkpoint source/data/model/config mismatch")
        return saved
    return {"fingerprint": expected, "records": {}, "complete": False}


def run_stage(
    root: Path,
    files: Path,
    queries: list[dict[str, Any]],
    references: Path,
    profile: str,
    limits: BatchLimits,
    thinking: str | None = "low",
    max_tokens: int = 2048,
    cost_ledger: BudgetLedger | None = None,
) -> dict[str, Any]:
    settings = gateway_settings()
    config = {
        **PROFILES[profile],
        "model": settings["gateway_model"],
        "base_url": settings["gateway_url"],
        "thinking": thinking,
        "max_tokens": max_tokens,
        "temperature": 1.0,
        "concurrency": 2,
    }
    if config["helper_contract"]:
        config["contract_placement"] = "system and final user message"
    root.mkdir(parents=True, exist_ok=True)
    saved = checkpoint(root / "checkpoint.json", fingerprint(files, queries, config))
    remaining = [q for q in queries if str(q["id"]) not in saved["records"]]
    deadline = limits.update()["deadline_unix"]
    agent = PromptedGatewayAgent(
        **settings,
        batch_limits=limits,
        thinking=thinking,
        max_tokens=max_tokens,
        ledger=cost_ledger,
        compact_prompt=config["compact_prompt"],
        deadline=time.monotonic() + deadline - time.time(),
    )
    if config["helper_contract"]:
        agent.system_prompt += HELPER_CONTRACT
        agent.helper_instructions = HELPER_CONTRACT
    # References enter only the evaluator, after all generation for this stage.
    started = time.monotonic()
    with ResourceMonitor() as monitor, ThreadPoolExecutor(max_workers=2) as pool:
        # At most two live workbook objects; preserve the solver's 800 MiB RSS guard.
        pending: dict[Any, dict[str, Any]] = {}
        cursor = 0
        while cursor < len(remaining) or pending:
            while cursor < len(remaining) and len(pending) < 2:
                item = remaining[cursor]
                if (
                    agent.fatal_error
                    or time.time() >= deadline
                    or monitor.exceeded.is_set()
                ):
                    break
                try:
                    allowance = limits.update()
                    if (
                        allowance["fatal_error"]
                        or allowance["attempts"] >= allowance["attempt_limit"]
                        or allowance["token_upper"] >= allowance["token_limit"]
                    ):
                        raise TimeoutError("Gateway batch allowance exhausted")
                except TimeoutError:
                    break
                cursor += 1
                workbook = load_workbook_data(
                    files / item["file_name"], max_bytes=64 * 1024**2
                )
                pending[pool.submit(agent.solve_workbook, workbook, item["query"])] = (
                    item
                )
            if not pending:
                break
            future = next(as_completed(pending))
            item = pending.pop(future)
            result = future.result()
            if result.requests:
                saved["records"][str(item["id"])] = {
                    "file_name": item["file_name"],
                    **result.trace(),
                }
                saved["wall_seconds"] = (
                    saved.get("wall_seconds", 0) + time.monotonic() - started
                )
                started = time.monotonic()
                atomic_json(root / "checkpoint.json", saved)
                print(
                    f"{root.name} {item['id']}: {result.answer!r} ({result.elapsed:.2f}s)",
                    flush=True,
                )
            else:
                agent.fatal_error = result.error or "No inference completed"
    records = saved["records"]
    predictions = {key: value["answer"] for key, value in records.items()}
    output = root / "submission.csv"
    write_submission(output, queries, predictions)
    saved["complete"] = len(records) == len(queries) and all(
        not r.get("error") for r in records.values()
    )
    report = {
        "profile": profile,
        "config": config,
        "source_sha256": source_hash(),
        "fingerprint": saved["fingerprint"],
        "complete": saved["complete"],
        "generation_complete": len(records) == len(queries),
        "score": score(
            output, read_answers(references), {str(q["id"]) for q in queries}
        ),
        "mean_query_seconds": statistics.mean(r["elapsed"] for r in records.values())
        if records
        else None,
        "wall_seconds": saved.get("wall_seconds", 0),
        "tokens": sum(r["tokens"] for r in records.values()),
        "http_attempts": sum(r["requests"] for r in records.values()),
        "peak_total_rss_bytes": monitor.peak,
        "fatal_error": agent.fatal_error,
        "errors": {key: r["error"] for key, r in records.items() if r.get("error")},
        "tokens_estimated": any(
            c.get("tokens_estimated", True)
            for r in records.values()
            for c in r["calls"]
        ),
        "cost_basis": "user-confirmed-free; see calls for provider-reported cost",
        "provider_cost_available": any(
            c.get("provider_cost_usd") is not None
            for r in records.values()
            for c in r["calls"]
        ),
        "provider_reported_cost_usd": sum(
            c.get("provider_cost_usd") or 0
            for r in records.values()
            for c in r["calls"]
        )
        if any(
            c.get("provider_cost_usd") is not None
            for r in records.values()
            for c in r["calls"]
        )
        else None,
    }
    atomic_json(root / "checkpoint.json", saved)
    atomic_json(root / "report.json", report)
    return report


def select_profile(reports: dict[str, dict[str, Any]]) -> str | None:
    eligible = [
        p
        for p, r in reports.items()
        if r["generation_complete"] and not r.get("fatal_error")
    ]
    return (
        min(
            eligible,
            key=lambda p: (
                -reports[p]["score"]["correct"],
                reports[p]["mean_query_seconds"],
                reports[p]["tokens"],
                p,
            ),
        )
        if eligible
        else None
    )


def execute(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    limits = BatchLimits(root / "batch.json")
    probe = json.loads((root / "probe.json").read_text())
    if not probe.get("ok"):
        raise ValueError("Successful gateway probe required before benchmarking")
    thinking = probe.get("thinking")
    synthetic = root / "synthetic"
    if not (synthetic / "queries.json").exists():
        generate_fixtures(synthetic)
    synth_queries = validate_queries(
        synthetic / "queries.json", synthetic / "xlsx_files"
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for query in synth_queries:
        groups.setdefault(query["family"], []).append(query)
    tuning = []
    while len(tuning) < 8:
        for family in sorted(groups):
            if groups[family] and len(tuning) < 8:
                tuning.append(groups[family].pop(0))
    atomic_json(root / "tuning_manifest.json", {"queries": tuning})
    public = validate_queries(Path("data/queries.json"), Path("data/xlsx_files"))
    sets = {
        "public": (Path("data/xlsx_files"), public, Path("data/sample_submission.csv")),
        "synthetic": (
            synthetic / "xlsx_files",
            synth_queries,
            synthetic / "answers.csv",
        ),
    }
    summary: dict[str, Any] = {
        "fresh_model": gateway_settings()["gateway_model"],
        "stages": {},
        "candidate": None,
    }
    with workspace_budget().stage(
        str(root.resolve()) + f":gateway:{time.time_ns()}", 0.001
    ) as cost_ledger:
        stage = partial(run_stage, cost_ledger=cost_ledger)
        for name, (files, queries, refs) in sets.items():
            summary["stages"]["baseline_" + name] = stage(
                root / ("baseline_" + name), files, queries, refs, "A", limits, thinking
            )
            atomic_json(root / "summary.json", summary)
        screens = {}
        for profile in PROFILES:
            screens[profile] = stage(
                root / ("screen_" + profile),
                synthetic / "xlsx_files",
                tuning,
                synthetic / "answers.csv",
                profile,
                limits,
                thinking,
            )
            summary["stages"]["screen_" + profile] = screens[profile]
            atomic_json(root / "summary.json", summary)
        winner = select_profile(screens)
        if winner is None:
            summary["not_evaluated"] = "No complete screening configuration"
            atomic_json(root / "summary.json", summary)
            return
        # Test a cheaper thinking level only against the locked tuning set.
        low = screens[winner]
        minimal = stage(
            root / "screen_minimal",
            synthetic / "xlsx_files",
            tuning,
            synthetic / "answers.csv",
            winner,
            limits,
            "minimal",
        )
        summary["stages"]["screen_minimal"] = minimal
        if (
            minimal["generation_complete"]
            and not minimal["fatal_error"]
            and minimal["score"]["correct"] >= low["score"]["correct"]
            and (
                minimal["score"]["correct"] > low["score"]["correct"]
                or (minimal["mean_query_seconds"], minimal["tokens"])
                < (low["mean_query_seconds"], low["tokens"])
            )
        ):
            thinking = "minimal"
        output_tokens = 2048
        shorter = stage(
            root / "screen_output1024",
            synthetic / "xlsx_files",
            tuning,
            synthetic / "answers.csv",
            winner,
            limits,
            thinking,
            max_tokens=1024,
        )
        summary["stages"]["screen_output1024"] = shorter
        chosen = minimal if thinking == "minimal" else low
        if (
            shorter["generation_complete"]
            and not shorter["fatal_error"]
            and shorter["score"]["correct"] >= chosen["score"]["correct"]
            and not any(
                "truncated" in error.lower() for error in shorter["errors"].values()
            )
            and (
                shorter["score"]["correct"] > chosen["score"]["correct"]
                or (shorter["mean_query_seconds"], shorter["tokens"])
                < (chosen["mean_query_seconds"], chosen["tokens"])
            )
        ):
            output_tokens = 1024
        summary["screening_batch"] = limits.update()
        # Exactly two predeclared batches; never reset a depleted batch or tune after holdout.
        limits = BatchLimits(root / "validation_batch.json")
        atomic_json(root / "summary.json", summary)
        from .metamorphic import generate

        mutation = root / "metamorphic"
        if not (mutation / "queries.json").exists():
            generate(mutation)
        mq = validate_queries(mutation / "queries.json", mutation / "xlsx_files")
        summary["stages"]["candidate_metamorphic"] = stage(
            root / "candidate_metamorphic",
            mutation / "xlsx_files",
            mq,
            mutation / "references.csv",
            winner,
            limits,
            thinking,
            max_tokens=output_tokens,
        )
        candidate = {
            "profile": winner,
            "thinking": thinking,
            "max_tokens": output_tokens,
            "source_sha256": source_hash(),
            "transport_sha256": hashlib.sha256(
                Path(__file__).with_name("gateway.py").read_bytes()
            ).hexdigest(),
            "helper_sha256": hashlib.sha256(HELPER_CONTRACT.encode()).hexdigest()
            if winner == "C"
            else None,
            "holdout_manifest_sha256": hashlib.sha256(
                Path("reports/optimization/frozen_holdout/manifest.json").read_bytes()
            ).hexdigest(),
        }
        lock_path = root / "candidate_lock.json"
        if lock_path.exists() and json.loads(lock_path.read_text()) != candidate:
            raise ValueError("Candidate already locked; no retuning after holdout")
        summary["candidate"] = candidate
        atomic_json(root / "candidate_lock.json", candidate)
        for name, (files, queries, refs) in sets.items():
            summary["stages"]["candidate_" + name] = stage(
                root / ("candidate_" + name),
                files,
                queries,
                refs,
                winner,
                limits,
                thinking,
                max_tokens=output_tokens,
            )
            atomic_json(root / "summary.json", summary)
        hold = Path("reports/optimization/frozen_holdout")
        hq = validate_queries(hold / "queries.json", hold / "xlsx_files")
        for label, profile, effort in [
            ("baseline", "A", probe.get("thinking")),
            ("candidate", winner, thinking),
        ]:
            summary["stages"][label + "_holdout"] = stage(
                root / (label + "_holdout"),
                hold / "xlsx_files",
                hq,
                hold / "references.csv",
                profile,
                limits,
                effort,
                max_tokens=output_tokens if label == "candidate" else 2048,
            )
            atomic_json(root / "summary.json", summary)
    summary["batch"] = limits.update()
    summary["qwen_confirmation"] = "not yet evaluated; competition defaults unchanged"
    atomic_json(root / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path("reports/optimization/gemini_gateway")
    )
    args = parser.parse_args()
    execute(args.root)
