"""Measure all consumed nonpublic cases in one bounded candidate-only experiment."""

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
from .qwen_batch_signoff import source_manifest
from .structured_batch import StructuredBatchedAgent
from .transfer_qualification import batch_stop_reason

DATASETS = (
    ("regression_60", "efficiency_v3/sealed_holdout", "references.csv", 60),
    ("regression_32", "efficiency_v4/sealed_challenge", "references.csv", 32),
    ("known_18", "frozen_holdout", "references.csv", 18),
    ("synthetic_24", "gemini_gateway/synthetic", "answers.csv", 24),
    ("structural_18", "structural_v1_holdout", "references.csv", 18),
    ("generalization_18", "generalization_v1_holdout", "references.csv", 18),
    ("transfer_24", "efficiency_v5_holdout", "references.csv", 24),
    ("compositional_18", "compositional_v1_holdout", "references.csv", 18),
    ("robustness_24", "robustness_v1_holdout", "references.csv", 24),
    ("decision_18", "decision_v1_holdout", "references.csv", 18),
)


def measure(root: Path) -> dict[str, Any]:
    """Keep a separate fixed allowance; never fill an exhausted earlier experiment."""
    if root.exists():
        raise ValueError("Preserve existing regression experiment")
    source = source_manifest()
    folders = {}
    dataset_hashes = {}
    for label, directory, reference, count in DATASETS:
        folder = Path("reports/optimization") / directory
        queries = validate_queries(folder / "queries.json", folder / "xlsx_files")
        if len(queries) != count or not (folder / reference).is_file():
            raise ValueError(f"Incomplete regression fixture: {label}")
        paths = [folder / "queries.json", folder / reference]
        paths += sorted((folder / "xlsx_files").glob("*.xlsx"))
        dataset_hashes[label] = {
            str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        folders[label] = (folder, reference, queries)
    root.mkdir(parents=True)
    report: dict[str, Any] = {
        "modules": source,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset_hashes": dataset_hashes,
        "expected_total": sum(count for _, _, _, count in DATASETS),
        "scope": "Candidate-only full consumed regression; no independent validation or matched baseline speed claim",
        "qualification": False,
        "independent_validation": False,
        "promoted": False,
        "complete": False,
        "stages": {},
        "unassessed": {},
    }
    atomic_json(root / "source_lock.json", report)
    for name in [*source, "benchmarks/known_regression.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    limits = BatchLimits(root / "batch.json")
    stopped = None
    for label, _, _, _ in DATASETS:
        reason = stopped or batch_stop_reason(limits.update())
        if reason:
            report["unassessed"][label] = reason
            atomic_json(root / "summary.json", report)
            continue
        if source != source_manifest():
            raise ValueError("Source changed during full regression")
        folder, reference, queries = folders[label]
        destination = root / label
        with workspace_budget().stage(str(destination.resolve()), 0.001) as ledger:
            stage = run_batched_stage(
                destination,
                folder / "xlsx_files",
                queries,
                folder / reference,
                limits,
                ledger,
                agent_class=StructuredBatchedAgent,
                review_candidate=True,
            )
        if source != source_manifest():
            raise ValueError("Source changed during full regression")
        report["stages"][label] = stage
        stopped = batch_stop_reason(limits.update()) or stage.get("fatal_error")
        if any(
            "Gateway batch request/token allowance exhausted" in str(error)
            for error in stage.get("errors", {}).values()
        ):
            stopped = "Insufficient remaining request/token allowance"
        atomic_json(root / "summary.json", report)
        print(json.dumps({"stage": label, "score": stage["score"]}), flush=True)
    reports = list(report["stages"].values())
    report["complete"] = (
        not report["unassessed"]
        and len(reports) == len(DATASETS)
        and all(stage["complete"] and not stage["fatal_error"] for stage in reports)
        and sum(stage["score"]["total"] for stage in reports)
        == report["expected_total"]
    )
    report["aggregate"] = {
        "correct": sum(stage["score"]["correct"] for stage in reports),
        "total": sum(stage["score"]["total"] for stage in reports),
        "wall_seconds": sum(stage["wall_seconds"] for stage in reports),
        "provider_tokens_known": sum(
            stage["provider_tokens_known"] for stage in reports
        ),
        "usage_missing_attempts": sum(
            stage["usage_missing_attempts"] for stage in reports
        ),
        "peak_total_rss_bytes": max(
            (stage["peak_total_rss_bytes"] for stage in reports), default=0
        ),
    }
    atomic_json(root / "summary.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    measure(parser.parse_args().root)
