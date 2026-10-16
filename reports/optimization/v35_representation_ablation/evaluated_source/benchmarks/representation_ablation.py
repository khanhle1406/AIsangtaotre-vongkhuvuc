"""Bounded A/B/C comparison of lossless header reuse and general postconditions."""

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
    """Freeze source and vary one feature per arm on the same consumed datasets."""
    if root.exists():
        raise ValueError("Preserve existing representation experiment")
    root.mkdir(parents=True)
    source = source_manifest()
    summary: dict[str, Any] = {
        "source": source,
        "independent_validation": False,
        "promoted": False,
        "stages": {},
    }
    for name in [*source, "benchmarks/representation_ablation.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    atomic_json(root / "summary.json", summary)
    limits = BatchLimits(root / "batch.json")
    arms = [("A", False, False), ("B", True, False), ("C", True, True)]
    datasets = [
        ("public", Path("data"), "sample_submission.csv"),
        (
            "structural",
            Path("reports/optimization/structural_v1_holdout"),
            "references.csv",
        ),
        (
            "generalization",
            Path("reports/optimization/generalization_v1_holdout"),
            "references.csv",
        ),
        (
            "synthetic",
            Path("reports/optimization/gemini_gateway/synthetic"),
            "answers.csv",
        ),
    ]
    for index, (label, dataset, reference) in enumerate(datasets):
        ordered = arms[index % len(arms) :] + arms[: index % len(arms)]
        for arm, deduplicate, boundaries in ordered:
            if source != source_manifest():
                raise ValueError("Runtime changed during representation experiment")
            destination = root / arm / label
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
                    review_candidate=True,
                    deduplicate_headers=deduplicate,
                    boundary_contract=boundaries,
                )
            if source != source_manifest():
                raise ValueError("Runtime changed during representation experiment")
            summary["stages"][f"{arm}/{label}"] = report
            atomic_json(root / "summary.json", summary)
            print(
                json.dumps({"stage": f"{arm}/{label}", "score": report["score"]}),
                flush=True,
            )
            if report["fatal_error"]:
                summary["stopped"] = "Operational failure; not model-quality evidence"
                atomic_json(root / "summary.json", summary)
                return summary
    ranking = []
    for arm, deduplicate, boundaries in arms:
        reports = [summary["stages"][f"{arm}/{label}"] for label, _, _ in datasets]
        ranking.append(
            {
                "arm": arm,
                "deduplicate_headers": deduplicate,
                "boundary_contract": boundaries,
                "correct": sum(r["score"]["correct"] for r in reports),
                "total": sum(r["score"]["total"] for r in reports),
                "complete": all(
                    r.get("generation_complete", r["complete"]) for r in reports
                ),
                "seconds": sum(r["wall_seconds"] for r in reports),
                "tokens": sum(r["provider_tokens_known"] for r in reports),
                "usage_missing_attempts": sum(
                    r["usage_missing_attempts"] for r in reports
                ),
            }
        )
    summary["ranking"] = sorted(
        ranking,
        key=lambda r: (not r["complete"], -r["correct"], r["seconds"], r["tokens"]),
    )
    atomic_json(root / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    compare(parser.parse_args().root)
