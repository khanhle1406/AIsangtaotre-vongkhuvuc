"""Compare review policies on consumed data; never promote from one screening run."""

import argparse
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


def compare(root: Path) -> dict[str, Any]:
    """Use identical runtime, data and quotas, alternating policy order by dataset."""
    if root.exists():
        raise ValueError("Preserve existing review experiment")
    root.mkdir(parents=True)
    source = source_manifest()
    summary: dict[str, Any] = {
        "source": source,
        "independent_validation": False,
        "promoted": False,
        "stages": {},
    }
    for name in [*source, "benchmarks/review_ablation.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    atomic_json(root / "summary.json", summary)
    limits = BatchLimits(root / "batch.json")
    datasets = [
        ("public", Path("data"), "sample_submission.csv"),
        (
            "generalization",
            Path("reports/optimization/generalization_v1_holdout"),
            "references.csv",
        ),
        (
            "structural",
            Path("reports/optimization/structural_v1_holdout"),
            "references.csv",
        ),
        (
            "regression_60",
            Path("reports/optimization/efficiency_v3/sealed_holdout"),
            "references.csv",
        ),
    ]
    for index, (label, dataset, reference) in enumerate(datasets):
        policies = [("fresh", False), ("audit", True)]
        if index % 2:
            policies.reverse()
        for policy, audit in policies:
            if source != source_manifest():
                raise ValueError("Runtime changed during review experiment")
            destination = root / policy / label
            queries = validate_queries(dataset / "queries.json", dataset / "xlsx_files")
            with workspace_budget().stage(str(destination.resolve()), 0.001) as ledger:
                report = run_batched_stage(
                    destination,
                    dataset / "xlsx_files",
                    queries,
                    dataset / reference,
                    limits,
                    ledger,
                    agent_class=StructuredBatchedAgent,
                    review_candidate=audit,
                )
            if source != source_manifest():
                raise ValueError("Runtime changed during review experiment")
            summary["stages"][f"{policy}/{label}"] = report
            atomic_json(root / "summary.json", summary)
            print(
                json.dumps({"stage": f"{policy}/{label}", "score": report["score"]}),
                flush=True,
            )
            if report["fatal_error"]:
                summary["stopped"] = "Operational failure; not model-quality evidence"
                atomic_json(root / "summary.json", summary)
                return summary
    summary["comparison"] = {}
    for policy in ("fresh", "audit"):
        reports = [summary["stages"][f"{policy}/{label}"] for label, _, _ in datasets]
        summary["comparison"][policy] = {
            "correct": sum(r["score"]["correct"] for r in reports),
            "total": sum(r["score"]["total"] for r in reports),
            "complete": all(r["complete"] for r in reports),
            "seconds": sum(r["wall_seconds"] for r in reports),
            "tokens": sum(r["provider_tokens_known"] for r in reports),
            "usage_missing_attempts": sum(r["usage_missing_attempts"] for r in reports),
        }
    atomic_json(root / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    compare(parser.parse_args().root)
