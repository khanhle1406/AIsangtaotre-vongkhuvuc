"""Small source-frozen regression after a runtime fix; never a qualification report."""

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from run import validate_queries

from .batched import run_batched_stage
from .budget import workspace_budget
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage
from .qwen_batch_signoff import source_manifest
from .structured_batch import StructuredBatchedAgent
from .transfer_qualification import batch_stop_reason


def check(root: Path) -> dict[str, Any]:
    """Measure public repetitions plus consumed decision cases within one fixed budget."""
    if root.exists():
        raise ValueError("Preserve existing focused regression")
    root.mkdir(parents=True)
    source = source_manifest()
    report: dict[str, Any] = {
        "modules": source,
        "qualification": False,
        "independent_validation": False,
        "promoted": False,
        "stages": {},
        "unassessed": {},
    }
    atomic_json(root / "diagnostic_lock.json", report)
    for name in [*source, "benchmarks/focused_regression.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    limits = BatchLimits(root / "batch.json")
    datasets = [
        ("baseline_public", Path("data"), "sample_submission.csv"),
        *[(f"public_{i}", Path("data"), "sample_submission.csv") for i in range(1, 4)],
        (
            "decision_regression",
            Path("reports/optimization/decision_v1_holdout"),
            "references.csv",
        ),
    ]
    stopped = None
    for label, folder, reference in datasets:
        reason = stopped or batch_stop_reason(limits.update())
        if reason:
            report["unassessed"][label] = reason
            atomic_json(root / "summary.json", report)
            continue
        if source != source_manifest():
            raise ValueError("Source changed during focused regression")
        destination = root / label
        queries = validate_queries(folder / "queries.json", folder / "xlsx_files")
        with workspace_budget().stage(str(destination.resolve()), 0.001) as ledger:
            if label == "baseline_public":
                stage = run_stage(
                    destination,
                    folder / "xlsx_files",
                    queries,
                    folder / reference,
                    "B",
                    limits,
                    cost_ledger=ledger,
                    iterator_helpers=True,
                    precision_profile="robust",
                )
            else:
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
            raise ValueError("Source changed during focused regression")
        report["stages"][label] = stage
        stopped = batch_stop_reason(limits.update()) or stage.get("fatal_error")
        if any(
            "Gateway batch request/token allowance exhausted" in str(error)
            for error in stage.get("errors", {}).values()
        ):
            stopped = "Insufficient remaining request/token allowance"
        atomic_json(root / "summary.json", report)
        print(json.dumps({"stage": label, "score": stage["score"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    check(parser.parse_args().root)
