"""Screen Gemini effort/concurrency on known data, with one bounded shared ledger."""

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


def compare(root: Path) -> dict[str, Any]:
    """Screen only; no automatic promotion or claim of unseen private accuracy."""
    if root.exists():
        raise ValueError("Preserve existing parameter experiment")
    root.mkdir(parents=True)
    source = source_manifest()
    configurations = [
        ("low_c4", "low", 4),
        ("medium_c4", "medium", 4),
        ("low_c8", "low", 8),
        ("medium_c8", "medium", 8),
    ]
    datasets = [
        ("public", Path("data"), "sample_submission.csv"),
        (
            "regression_32",
            Path("reports/optimization/efficiency_v4/sealed_challenge"),
            "references.csv",
        ),
        (
            "generalization",
            Path("reports/optimization/generalization_v1_holdout"),
            "references.csv",
        ),
    ]
    summary: dict[str, Any] = {
        "source": source,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "independent_validation": False,
        "promoted": False,
        "thinking_control": "requested gateway effort; internal model implementation unverified",
        "stages": {},
    }
    atomic_json(root / "summary.json", summary)
    for name in [*source, "benchmarks/parameter_ablation.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    limits = BatchLimits(root / "batch.json")
    for index, (dataset_name, dataset, reference) in enumerate(datasets):
        ordered = configurations[index:] + configurations[:index]
        for label, effort, concurrency in ordered:
            if source != source_manifest():
                raise ValueError("Runtime changed during parameter experiment")
            destination = root / label / dataset_name
            queries = validate_queries(dataset / "queries.json", dataset / "xlsx_files")
            with workspace_budget().stage(str(destination.resolve()), 0.001) as ledger:
                report = run_batched_stage(
                    destination,
                    dataset / "xlsx_files",
                    queries,
                    dataset / reference,
                    limits,
                    ledger,
                    concurrency=concurrency,
                    thinking=effort,
                    agent_class=StructuredBatchedAgent,
                )
            if source != source_manifest():
                raise ValueError("Runtime changed during parameter experiment")
            summary["stages"][f"{label}/{dataset_name}"] = report
            atomic_json(root / "summary.json", summary)
            print(
                json.dumps(
                    {
                        "stage": f"{label}/{dataset_name}",
                        "score": report["score"],
                        "seconds": report["wall_seconds"],
                        "tokens": report["provider_tokens_known"],
                    }
                ),
                flush=True,
            )
            if report["fatal_error"]:
                summary["stopped"] = "Operational failure, not model-quality evidence"
                atomic_json(root / "summary.json", summary)
                return summary
    ranking = []
    for label, effort, concurrency in configurations:
        reports = [summary["stages"][f"{label}/{name}"] for name, _, _ in datasets]
        ranking.append(
            {
                "configuration": label,
                "complete": all(r["complete"] for r in reports),
                "correct": sum(r["score"]["correct"] for r in reports),
                "total": sum(r["score"]["total"] for r in reports),
                "seconds": sum(r["wall_seconds"] for r in reports),
                "tokens_known": sum(r["provider_tokens_known"] for r in reports),
                "usage_complete": all(
                    r["usage_missing_attempts"] == 0 for r in reports
                ),
                "peak_rss_bytes": max(r["peak_total_rss_bytes"] for r in reports),
            }
        )
    summary["ranking"] = sorted(
        ranking,
        key=lambda r: (
            not r["complete"],
            -r["correct"],
            r["seconds"],
            r["tokens_known"],
        ),
    )
    atomic_json(root / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    compare(parser.parse_args().root)
