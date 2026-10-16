"""Unchanged v30 checks on all previously consumed challenge datasets."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from benchmarks.batched import run_batched_stage
from benchmarks.budget import workspace_budget
from benchmarks.gateway import BatchLimits, atomic_json
from benchmarks.qwen_batch_signoff import source_manifest
from benchmarks.structured_batch import StructuredBatchedAgent
from run import validate_queries


def main() -> None:
    root = Path(__file__).resolve().parent
    if (root / "summary.json").exists():
        raise ValueError("Preserve existing regression evidence")
    modules = source_manifest()
    parent = json.loads(
        Path("reports/optimization/compositional_v1_proof/source_lock.json").read_text()
    )
    if parent["modules"] != modules:
        raise ValueError("Runtime changed since independent proof")
    summary: dict[str, Any] = {
        "modules": modules,
        "independent_validation": False,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "stages": {},
    }
    atomic_json(root / "summary.json", summary)
    for name in modules:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    limits = BatchLimits(root / "batch.json")
    for label, folder in [
        ("structural_18", "structural_v1_holdout"),
        ("generalization_18", "generalization_v1_holdout"),
        ("transfer_24", "efficiency_v5_holdout"),
    ]:
        if modules != source_manifest():
            raise ValueError("Runtime changed during regression")
        dataset = Path("reports/optimization") / folder
        destination = root / label
        with workspace_budget().stage(str(destination), 0.001) as ledger:
            report = run_batched_stage(
                destination,
                dataset / "xlsx_files",
                validate_queries(dataset / "queries.json", dataset / "xlsx_files"),
                dataset / "references.csv",
                limits,
                ledger,
                agent_class=StructuredBatchedAgent,
            )
        if modules != source_manifest():
            raise ValueError("Runtime changed during regression")
        summary["stages"][label] = report
        atomic_json(root / "summary.json", summary)
        print(
            json.dumps(
                {
                    "stage": label,
                    "score": report["score"],
                    "seconds": report["wall_seconds"],
                    "tokens": report["provider_tokens_known"],
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
