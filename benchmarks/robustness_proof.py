"""Evaluate an unchanged qualified source once on a new independent dataset."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from run import validate_queries

from .batched import run_batched_stage
from .budget import workspace_budget
from .gateway import BatchLimits, atomic_json
from .gateway_runner import fingerprint, run_stage
from .qwen_batch_signoff import source_manifest
from .structured_batch import StructuredBatchedAgent


def proof(qualified: Path, dataset: Path, output: Path) -> dict[str, Any]:
    """Copies qualification evidence with its provenance, never fabricates new runs."""
    if output.exists() or (dataset / "evaluated.json").exists():
        raise ValueError("Preserve existing proof and consumed independent data")
    parent = json.loads((qualified / "source_lock.json").read_text())
    modules = source_manifest()
    if parent["modules"] != modules:
        raise ValueError("Candidate source differs from qualified source")
    configuration = parent.get("configuration", {"thinking": "low", "concurrency": 4})
    if (
        not isinstance(configuration, dict)
        or set(configuration) != {"thinking", "concurrency"}
        or configuration["thinking"] not in {"minimal", "low", "medium", "high"}
        or configuration["concurrency"] not in {1, 2, 4, 8}
    ):
        raise ValueError("Invalid qualified development configuration")
    prerequisites: dict[str, Path] = {}
    sources = {
        **{f"public_{i}": (Path("data"), 20) for i in range(1, 4)},
        "regression_60": (
            Path("reports/optimization/efficiency_v3/sealed_holdout"),
            60,
        ),
        "regression_32": (
            Path("reports/optimization/efficiency_v4/sealed_challenge"),
            32,
        ),
        "known_18": (Path("reports/optimization/frozen_holdout"), 18),
        "synthetic_24": (Path("reports/optimization/gemini_gateway/synthetic"), 24),
        "consumed_validation": (Path(parent["validation_dataset"]), 24),
    }
    for label in (
        "public_1",
        "public_2",
        "public_3",
        "regression_60",
        "regression_32",
        "known_18",
        "synthetic_24",
        "consumed_validation",
    ):
        path = qualified / label / "report.json"
        result = json.loads(path.read_text())
        source, count = sources[label]
        if (
            not result["complete"]
            or result["score"]["total"] != count
            or result["score"]["correct"] != result["score"]["total"]
        ):
            raise ValueError(
                f"Qualification failed on {label}; new holdout stays unused"
            )
        if any(
            result["config"].get(key) != value for key, value in configuration.items()
        ):
            raise ValueError(f"Qualification configuration changed on {label}")
        if result["fingerprint"] != fingerprint(
            source / "xlsx_files",
            validate_queries(source / "queries.json", source / "xlsx_files"),
            result["config"],
        ):
            raise ValueError(f"Qualification data/config changed on {label}")
        prerequisites[label] = path
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["hashes"].items():
        path = dataset / name
        if (
            not path.resolve().is_relative_to(dataset.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Frozen independent dataset changed")
    lock = {
        "modules": modules,
        "scope": "New independent comparison, unchanged runtime source; qualification copied from measured parent with hashes",
        "independent_validation": True,
        "qualification_parent": str(qualified),
        "configuration": configuration,
        "qualification_reports_sha256": {
            label: hashlib.sha256(path.read_bytes()).hexdigest()
            for label, path in prerequisites.items()
        },
        "validation_dataset": str(dataset),
        "validation_manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    output.mkdir(parents=True)
    atomic_json(output / "source_lock.json", lock)
    for label, path in prerequisites.items():
        target = output / label / "report.json"
        target.parent.mkdir(parents=True)
        shutil.copy2(path, target)
    for name in modules:
        path = Path(name)
        target = output / "evaluated_source" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    atomic_json(dataset / "evaluated.json", lock)
    limits = BatchLimits(output / "batch.json")
    files = dataset / "xlsx_files"
    queries = validate_queries(dataset / "queries.json", files)
    summary: dict[str, Any] = {
        "lock": lock,
        "stages": {},
        "btc_private_verified": False,
        "qwen_confirmed": False,
    }
    for label in ("baseline", "candidate"):
        if modules != source_manifest():
            raise ValueError("Source changed during proof")
        folder = output / "heldout_proof" / label
        with workspace_budget().stage(str(folder.resolve()), 0.001) as ledger:
            if label == "baseline":
                report = run_stage(
                    folder,
                    files,
                    queries,
                    dataset / "references.csv",
                    "B",
                    limits,
                    cost_ledger=ledger,
                    iterator_helpers=True,
                    precision_profile="robust",
                )
            else:
                report = run_batched_stage(
                    folder,
                    files,
                    queries,
                    dataset / "references.csv",
                    limits,
                    ledger,
                    agent_class=StructuredBatchedAgent,
                    **lock["configuration"],
                )
        if modules != source_manifest():
            raise ValueError("Source changed during proof")
        summary["stages"][label] = report
        atomic_json(output / "summary.json", summary)
        print(
            json.dumps(
                {
                    "stage": label,
                    "score": report["score"],
                    "seconds": report["wall_seconds"],
                    "tokens_known": report["provider_tokens_known"],
                }
            ),
            flush=True,
        )
    baseline, candidate = (
        summary["stages"][label] for label in ("baseline", "candidate")
    )
    summary["comparison"] = {
        "both_complete": baseline["complete"] and candidate["complete"],
        "correct_gain": candidate["score"]["correct"] - baseline["score"]["correct"],
        "wall_reduction": 1 - candidate["wall_seconds"] / baseline["wall_seconds"],
        "token_reduction_known": 1
        - candidate["provider_tokens_known"] / baseline["provider_tokens_known"]
        if baseline["provider_tokens_known"]
        else None,
        "usage_complete": baseline["usage_missing_attempts"]
        == candidate["usage_missing_attempts"]
        == 0,
        "independent_test_consumed": True,
    }
    atomic_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualified", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    proof(arguments.qualified, arguments.dataset, arguments.output)
