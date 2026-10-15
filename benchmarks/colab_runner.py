"""Resume-safe local benchmark stages. This process never loads torch/model weights."""

import argparse
import hashlib
import json
import statistics
import time
import urllib.error
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import ResourceMonitor, validate_queries, write_submission
from src.excel_parser import load_workbook_data
from src.llm_agent import SYSTEM_PROMPT

from .colab_io import atomic_json, export_results
from .colab_local import (
    HELPER_CONTRACT,
    LOCAL_MODEL,
    LocalDevelopmentAgent,
    local_json,
)
from .compare import score

PROFILES = {
    "A": {"compact_prompt": False, "helper_contract": False},
    "B": {"compact_prompt": True, "helper_contract": False},
    "C": {"compact_prompt": True, "helper_contract": True},
}


def code_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(
        [
            Path("run.py"),
            Path("evaluate.py"),
            *Path("src").glob("*.py"),
            *Path("benchmarks").glob("*.py"),
        ]
    ):
        digest.update(path.as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def fingerprint(
    profile: str, queries: list[dict[str, Any]], files: Path, metadata: dict[str, Any]
) -> str:
    data = {
        "source_sha256": code_hash(),
        "profile": PROFILES[profile],
        "system_prompt": SYSTEM_PROMPT,
        "helper_contract": HELPER_CONTRACT if profile == "C" else "",
        "queries": queries,
        "workbooks": {
            name: hashlib.sha256((files / name).read_bytes()).hexdigest()
            for name in sorted({q["file_name"] for q in queries})
        },
        "model": {
            key: metadata[key]
            for key in (
                "model",
                "revision",
                "context_length",
                "quantization",
                "compute_dtype",
                "kv_dtype",
                "attention",
                "thinking",
            )
        },
        "max_tokens": 2048,
        "do_sample": False,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def read_checkpoint(path: Path, expected: str) -> dict[str, Any]:
    if not path.exists():
        return {"fingerprint": expected, "records": {}, "complete": False}
    saved = json.loads(path.read_text())
    if saved.get("fingerprint") != expected:
        raise ValueError("Checkpoint fingerprint mismatch; preserve the old run")
    return saved


def choose_profile(reports: dict[str, dict[str, Any]]) -> str | None:
    complete = [
        (key, report) for key, report in reports.items() if report.get("complete")
    ]
    if not complete:
        return None
    return min(
        complete,
        key=lambda item: (
            -item[1]["score"]["correct"],
            item[1]["elapsed_seconds"],
            item[1]["tokens"],
            item[0],
        ),
    )[0]


def warmup(base: str, data: Path, session: Path) -> dict[str, Any]:
    queries = validate_queries(data / "queries.json", data / "xlsx_files")
    client = LocalDevelopmentAgent(local_base_url=base)
    candidates = []
    for query in queries:
        workbook = load_workbook_data(data / "xlsx_files" / query["file_name"])
        text = workbook.to_text()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + HELPER_CONTRACT},
            {
                "role": "user",
                "content": f"WORKBOOK DATA:\n{text}\n\nQUESTION:\n{query['query']}",
            },
        ]
        candidates.append((client.token_count(messages), query, workbook, messages))
    _, query, workbook, messages = max(candidates, key=lambda row: row[0])
    for attempt in range(2):
        client = LocalDevelopmentAgent(local_base_url=base)
        client.local_workbook, client.local_query = workbook.wire(), query["query"]
        fitted = client.fit_context(messages)
        try:
            response = local_json(
                base,
                "/warmup",
                {
                    "model": LOCAL_MODEL,
                    "messages": fitted,
                    "max_tokens": 2048,
                    "temperature": 0,
                },
                timeout=120,
            )
            report = {
                "longest_query": query["id"],
                "metadata": local_json(base, "/models")["local"],
                "generation": response["local"],
                "not_scored": True,
            }
            atomic_json(session / "warmup.json", report)
            return report
        except urllib.error.HTTPError as error:
            metadata = local_json(base, "/models")["local"]
            if not (
                error.code == 507
                and attempt == 0
                and metadata["oom_fallback_used"]
                and not metadata["fatal_error"]
            ):
                raise
    raise RuntimeError("Warm-up did not complete")


def run_stage(
    name: str, profile: str, dataset: Path, base: str, session: Path
) -> dict[str, Any]:
    root = session / name
    root.mkdir(parents=True, exist_ok=True)
    queries = validate_queries(dataset / "queries.json", dataset / "xlsx_files")
    # References are read only by scoring, after inference below.
    metadata = local_json(base, "/models")["local"]
    expected = fingerprint(profile, queries, dataset / "xlsx_files", metadata)
    checkpoint = read_checkpoint(root / "checkpoint.json", expected)
    if checkpoint.get("complete"):
        return json.loads((root / "report.json").read_text())
    pending = [q for q in queries if str(q["id"]) not in checkpoint["records"]]
    client = LocalDevelopmentAgent(
        local_base_url=base,
        compact_prompt=PROFILES[profile]["compact_prompt"],
        deadline=time.monotonic()
        + max(0, metadata["inference_deadline"] - time.time()),
    )
    if PROFILES[profile]["helper_contract"]:
        client.system_prompt += HELPER_CONTRACT
    started = time.monotonic()
    previous_elapsed = checkpoint.get("elapsed_seconds", 0.0)
    with ResourceMonitor() as monitor:
        for query in pending:
            state = local_json(base, "/models")["local"]
            if (
                monitor.exceeded.is_set()
                or client.fatal_error
                or state["fatal_error"]
                or state["generations"] >= 100
                or time.time() >= state["inference_deadline"]
            ):
                break
            workbook = load_workbook_data(dataset / "xlsx_files" / query["file_name"])
            result = client.solve_workbook(workbook, query["query"])
            checkpoint["records"][str(query["id"])] = result.trace()
            checkpoint["elapsed_seconds"] = (
                previous_elapsed + time.monotonic() - started
            )
            checkpoint["peak_app_rss_bytes"] = max(
                checkpoint.get("peak_app_rss_bytes", 0), monitor.peak
            )
            # Save every answer on Drive before continuing, including failed model outputs.
            atomic_json(root / "checkpoint.json", checkpoint)
            write_submission(
                root / "submission.csv",
                queries,
                {
                    key: record["answer"]
                    for key, record in checkpoint["records"].items()
                },
            )
            export_results(session)
            print(
                f"{name} {query['id']}: {result.answer!r} {result.error or ''}",
                flush=True,
            )
            # Do not retain multiple full workbooks while the next one is parsed.
            del workbook
    metadata = local_json(base, "/models")["local"]
    records = checkpoint["records"]
    complete = (
        len(records) == len(queries)
        and not metadata["fatal_error"]
        and not monitor.exceeded.is_set()
    )
    write_submission(
        root / "submission.csv",
        queries,
        {key: record["answer"] for key, record in records.items()},
    )
    references = read_answers(dataset / "references.csv")
    report = {
        "profile": profile,
        "fingerprint": expected,
        "complete": complete,
        "expected": len(queries),
        "completed": len(records),
        "score": score(
            root / "submission.csv", references, {str(q["id"]) for q in queries}
        )
        if complete
        else None,
        "elapsed_seconds": checkpoint.get("elapsed_seconds", 0),
        "tokens": sum(record["tokens"] for record in records.values()),
        "requests": sum(record["requests"] for record in records.values()),
        "cost_usd": 0,
        "judge_model_benchmark": False,
        "peak_app_rss_bytes": checkpoint.get("peak_app_rss_bytes", monitor.peak),
        "local": metadata,
    }
    # Report first; a crash cannot leave a complete checkpoint without its report.
    atomic_json(root / "report.json", report)
    checkpoint["complete"] = complete
    atomic_json(root / "checkpoint.json", checkpoint)
    return report


def estimated_stage_seconds(
    dataset: Path, session: Path, metadata: dict[str, Any]
) -> float:
    durations = [
        row["elapsed_seconds"]
        for row in metadata["history"]
        if "error" not in row and not row.get("timed_out")
    ]
    for path in session.glob("*/checkpoint.json"):
        durations.extend(
            record["elapsed"]
            for record in json.loads(path.read_text())["records"].values()
        )
    per_question = max(10.0, statistics.median(durations) * 1.5) if durations else 120.0
    return len(json.loads((dataset / "queries.json").read_text())) * per_question


def run_session(session: Path, base: str, datasets: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    skipped: dict[str, str] = {}

    def scheduled(name: str, profile: str, data: Path) -> dict[str, Any] | None:
        metadata = local_json(base, "/models")["local"]
        if metadata["fatal_error"]:
            skipped[name] = "local runtime failure"
            return None
        checkpoint = session / name / "checkpoint.json"
        if checkpoint.exists() and json.loads(checkpoint.read_text()).get("complete"):
            reports[name] = run_stage(name, profile, data, base, session)
            return reports[name]
        estimate = estimated_stage_seconds(data, session, metadata)
        if (
            time.time() + estimate >= metadata["inference_deadline"]
            or metadata["generations"] >= 100
        ):
            skipped[name] = (
                "not evaluated: insufficient estimated time or generation allowance"
            )
            return None
        report = run_stage(name, profile, data, base, session)
        reports[name] = report
        atomic_json(session / "progress.json", {"reports": reports, "skipped": skipped})
        return report

    baseline = scheduled("public_A", "A", datasets / "public")
    if baseline and baseline["complete"]:
        tuning = {}
        for profile in PROFILES:
            result = scheduled(f"tuning_{profile}", profile, datasets / "tuning")
            if result:
                tuning[profile] = result
        # All three must have comparable coverage. Do not select a lucky partial run.
        winner = (
            choose_profile(tuning)
            if len(tuning) == 3 and all(r["complete"] for r in tuning.values())
            else None
        )
        if winner:
            selection = {
                "profile": winner,
                "source_sha256": code_hash(),
                "tuning": {
                    key: report["fingerprint"] for key, report in tuning.items()
                },
            }
            selection_path = session / "selection.json"
            if (
                selection_path.exists()
                and json.loads(selection_path.read_text()) != selection
            ):
                raise ValueError("Locked selection changed; holdout cannot be retuned")
            atomic_json(selection_path, selection)
            scheduled("holdout_locked", winner, datasets / "holdout")
            if winner != "A":
                scheduled(f"public_{winner}", winner, datasets / "public")
    result = {
        "reports": reports,
        "skipped": skipped,
        "judge_defaults_changed": False,
        "paid_api_calls": 0,
    }
    atomic_json(session / "summary.json", result)
    export_results(session)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--datasets", type=Path, default=Path("colab_data"))
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()
    if args.warmup:
        warmup(args.base_url, args.datasets / "public", args.session_dir)
    else:
        run_session(args.session_dir, args.base_url, args.datasets)


if __name__ == "__main__":
    main()
