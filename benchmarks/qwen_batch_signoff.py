"""Bounded official-model transfer check; never promote from Gemini or replay scores."""

import argparse
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import run_queries, validate_queries
from src.llm_agent import DEFAULT_MODEL, get_pricing

from .batched_submission import run_batched_queries
from .budget import workspace_budget
from .compare import score
from .gateway import atomic_json
from .qwen_batched import QwenBatchedAgent
from .qwen_signoff import acceptance_verdict


def source_manifest() -> dict[str, str]:
    paths = [
        Path("run.py"),
        *Path("src").glob("*.py"),
        *[
            Path("benchmarks") / name
            for name in (
                "batched.py",
                "structured_batch.py",
                "qwen_batched.py",
                "batched_submission.py",
                "gateway.py",
                "precision.py",
                "efficient.py",
                "gateway_runner.py",
                "packed.py",
                "backend_view.py",
            )
        ],
    ]
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def inference_counts(trace: Path) -> dict[str, int]:
    """Count each live shared HTTP event once, including failed/truncated responses."""
    calls: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(trace.read_text().splitlines()):
        row = json.loads(line)
        for call in row.get("planning_event", row).get("calls", []):
            identity = (
                call.get("shared_http_id")
                or f"{row.get('id', index)}:{call['request']}"
            )
            calls.setdefault(identity, call)
    return {
        "http_attempts": len(calls),
        "model_responses": sum(
            call.get("finish_reason") is not None for call in calls.values()
        ),
    }


def signoff(root: Path, *, attempt: str | None = None) -> dict[str, Any]:
    if attempt is not None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", attempt):
            raise ValueError("Invalid official attempt label")
        for path in root.glob("qwen_batch_signoff*.json"):
            previous = json.loads(path.read_text())
            if (
                previous.get("new_generations", 0)
                or previous.get("http_attempts", 0)
                or previous.get("status")
                not in {
                    "blocked_credit",
                    "blocked_credit_preflight",
                    "blocked_credentials",
                }
            ):
                raise ValueError(
                    "New attempt may only resume a preflight with no prior inference; preserve the paid acceptance cap"
                )
    suffix = "" if attempt is None else "_" + attempt
    destination = root / f"qwen_batch_signoff{suffix}.json"
    if destination.exists():
        raise ValueError("Preserve the prior official acceptance report")
    lock = json.loads((root / "source_lock.json").read_text())
    candidate_flags = {
        flag: lock.get("configuration", {}).get(flag, False)
        for flag in ("review_candidate", "deduplicate_headers", "boundary_contract")
    }
    if any(type(value) is not bool for value in candidate_flags.values()):
        raise ValueError("Invalid locked candidate feature flags")
    if lock["modules"] != source_manifest():
        raise ValueError("Candidate implementation changed after lock")
    report: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "provider": "openrouter",
        "maximum_usd": 0.05,
        "new_generations": 0,
        "promoted": False,
        "gate_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_lock": lock,
    }
    if (
        lock.get("configuration", {}).get("planning_profile", "same-book")
        != "same-book"
    ):
        report.update(
            status="blocked_unsupported_planning_profile",
            reason="Official transport does not implement the locked experimental planning profile",
        )
        atomic_json(destination, report)
        return report
    if lock.get("assessment_only") or lock.get("qualification_passed") is False:
        report.update(
            status="blocked_assessment_only",
            reason="Exploratory holdout evidence cannot qualify a final submission",
        )
        atomic_json(destination, report)
        return report
    requirements = [
        ("public_1", 20),
        ("public_2", 20),
        ("public_3", 20),
        ("regression_60", 60),
        ("regression_32", 32),
        ("known_18", 18),
        ("synthetic_24", 24),
    ]
    extensions = lock.get("regression_extensions", {})
    if not isinstance(extensions, dict):
        raise TypeError("Invalid locked regression extensions")
    for label, spec in extensions.items():
        if (
            not isinstance(label, str)
            or not isinstance(spec, dict)
            or type(spec.get("count")) is not int
            or spec["count"] <= 0
            or label in dict(requirements)
        ):
            raise ValueError("Invalid locked regression extension")
        requirements.append((label, spec["count"]))
    for label, count in requirements:
        path = root / label / "report.json"
        result = json.loads(path.read_text()) if path.exists() else None
        if (
            result is None
            or not result["complete"]
            or result["score"]["total"] != count
            or result["score"]["correct"] != result["score"]["total"]
            or any(
                result.get("config", {}).get(flag, False) != value
                for flag, value in candidate_flags.items()
            )
        ):
            report.update(
                status="blocked_qualification",
                dataset=label,
                reason="Current Gemini candidate has not passed all locked regressions",
            )
            atomic_json(destination, report)
            return report
    validation = Path("reports/optimization/efficiency_v4/sealed_challenge")
    if "validation_dataset" in lock:
        validation = Path(lock["validation_dataset"])
        manifest_path = validation / "manifest.json"
        if (
            hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            != lock["validation_manifest_sha256"]
        ):
            raise ValueError("Validation manifest changed after lock")
        manifest = json.loads(manifest_path.read_text())
        for name, expected in manifest["hashes"].items():
            path = validation / name
            if (
                not path.resolve().is_relative_to(validation.resolve())
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                raise ValueError("Validation dataset changed after lock")
        path = root / "heldout_proof" / "candidate" / "report.json"
        result = json.loads(path.read_text()) if path.exists() else None
        if (
            result is None
            or not result["complete"]
            or result["score"]["total"] != manifest["questions"]
            or result["score"]["correct"] != manifest["questions"]
            or any(
                result.get("config", {}).get(flag, False) != value
                for flag, value in candidate_flags.items()
            )
        ):
            report.update(
                status="blocked_qualification",
                dataset="heldout_proof",
                reason="Frozen independent comparison has not passed",
            )
            atomic_json(destination, report)
            return report
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        report["status"] = "blocked_credentials"
        atomic_json(destination, report)
        return report
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            credit = json.load(response)["data"]
        available = float(credit["total_credits"]) - float(credit["total_usage"])
        if not math.isfinite(available):
            raise ValueError("Invalid official credit balance")
        report["credit_preflight"] = {
            "total_credits": credit["total_credits"],
            "total_usage": credit["total_usage"],
            "available_usd": available,
        }
    except (urllib.error.URLError, ValueError, KeyError) as error:
        report.update(status="blocked_credit_preflight", error=type(error).__name__)
        atomic_json(destination, report)
        return report
    if available <= 0:
        report["status"] = "blocked_credit"
        atomic_json(destination, report)
        return report
    budget = workspace_budget()
    allowance = min(0.05, available, budget.remaining)
    if allowance <= 0:
        report["status"] = "blocked_budget"
        atomic_json(destination, report)
        return report
    report["reserved_limit_usd"] = allowance
    pricing = get_pricing(DEFAULT_MODEL)
    report["pricing_upper_usd_per_token"] = pricing
    datasets = [
        ("public", Path("data"), "sample_submission.csv"),
        (
            "validation",
            validation,
            "references.csv",
        ),
    ]
    report["scope"] = (
        "Official cross-model validation on already-consumed data; no new independent holdout claim"
    )
    stages = {}
    with budget.stage(
        str(root.resolve()) + ":qwen-batch-acceptance", allowance
    ) as ledger:
        deadline = time.monotonic() + 1800
        for name, folder, reference in datasets:
            files = folder / "xlsx_files"
            queries = validate_queries(folder / "queries.json", files)
            for label in ("baseline", "candidate"):
                client = QwenBatchedAgent(
                    ledger=ledger,
                    pricing=pricing,
                    deadline=deadline,
                    worker_memory_mb=128 if label == "candidate" else 256,
                    **{
                        flag: value if label == "candidate" else False
                        for flag, value in candidate_flags.items()
                    },
                )
                output = root / f"qwen{suffix}_{label}_{name}.csv"
                if label == "baseline":
                    metrics = run_queries(files, queries, output, client, 2)
                else:
                    metrics = run_batched_queries(files, queries, output, client, 4)
                stages[label + "_" + name] = {
                    "metrics": metrics,
                    "score": score(
                        output,
                        read_answers(folder / reference),
                        {str(q["id"]) for q in queries},
                    ),
                    "fatal_error": client.fatal_error,
                }
                counts = inference_counts(output.with_suffix(".trace.jsonl"))
                report["new_generations"] += counts["model_responses"]
                report["http_attempts"] = (
                    report.get("http_attempts", 0) + counts["http_attempts"]
                )
                report["stages"] = stages
                atomic_json(destination, report)
                if client.fatal_error or metrics["failures"]:
                    report.update(
                        status="incomplete_official_check",
                        spent_upper_usd=ledger.spent + ledger.reserved,
                    )
                    atomic_json(destination, report)
                    return report
        report["spent_upper_usd"] = ledger.spent + ledger.reserved
    report.update(
        status="evaluated",
        **acceptance_verdict(stages, [name for name, *_ in datasets]),
    )
    # Eligibility is evidence for the user; this command never edits run.py or ZIP defaults.
    atomic_json(destination, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--attempt", help="New label to resume a blocked zero-inference preflight"
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            signoff(arguments.root, attempt=arguments.attempt),
            ensure_ascii=False,
            indent=2,
        )
    )
