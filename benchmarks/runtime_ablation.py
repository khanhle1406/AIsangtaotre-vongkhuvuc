"""Bounded fresh A/B runs on consumed datasets; never claim independent validation."""

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


class PreviousStructuredAgent(StructuredBatchedAgent):
    """Identical runtime, with the previously measured keyed prompt contract."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(compact_contract=False, **kwargs)


class CompactStructuredAgent(StructuredBatchedAgent):
    """Rejected experiment retained for reproducible explicit comparisons only."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(compact_contract=True, **kwargs)


def compare(root: Path) -> dict[str, Any]:
    """Alternate fresh controls/candidates under one shared attempt/token/deadline cap."""
    if root.exists():
        raise ValueError("Preserve existing ablation evidence")
    root.mkdir(parents=True)
    source = source_manifest()
    summary: dict[str, Any] = {
        "source": source,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "independent_validation": False,
        "comparison": "same runtime and lossless column catalog; repeated contract retained versus removed",
        "stages": {},
    }
    atomic_json(root / "summary.json", summary)
    for name in [*source, "benchmarks/runtime_ablation.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    limits = BatchLimits(root / "batch.json")
    datasets = [
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
            "robustness",
            Path("reports/optimization/robustness_v1_holdout"),
            "references.csv",
        ),
        ("public", Path("data"), "sample_submission.csv"),
    ]
    for index, (label, dataset, reference) in enumerate(datasets):
        variants = [
            ("previous", PreviousStructuredAgent),
            ("candidate", CompactStructuredAgent),
        ]
        if index % 2:
            variants.reverse()
        for variant, agent_class in variants:
            if source != source_manifest():
                raise ValueError("Runtime changed during ablation")
            destination = root / label / variant
            queries = validate_queries(dataset / "queries.json", dataset / "xlsx_files")
            with workspace_budget().stage(str(destination.resolve()), 0.001) as ledger:
                report = run_batched_stage(
                    destination,
                    dataset / "xlsx_files",
                    queries,
                    dataset / reference,
                    limits,
                    ledger,
                    agent_class=agent_class,
                )
            if source != source_manifest():
                raise ValueError("Runtime changed during ablation")
            summary["stages"][f"{label}/{variant}"] = report
            atomic_json(root / "summary.json", summary)
            print(
                json.dumps(
                    {
                        "stage": f"{label}/{variant}",
                        "score": report["score"],
                        "seconds": report["wall_seconds"],
                        "tokens": report["provider_tokens_known"],
                    }
                ),
                flush=True,
            )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    compare(parser.parse_args().root)
